"""
SQLite persistence layer for Toronto Rent Deal Finder.
MC-262: Replace CSV as primary store with SQLite.

Schema:
  listings:       scraped listing data + first_seen / last_seen / is_active
  scrape_runs:    metadata about each scrape run (timestamp, source, count)
  user_alerts:    user notification preferences (email, filters, threshold)

Inactivity tracking:
  After each scrape, listings NOT seen in last 3 runs are marked is_active=0.
  Active listings (is_active=1) are shown in the app / used for scoring.
"""

from __future__ import annotations

import sqlite3, os, json
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "listings.db")


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS scrape_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ts        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    source        TEXT    NOT NULL,
    listings_seen INTEGER NOT NULL DEFAULT 0,
    listings_new  INTEGER NOT NULL DEFAULT 0,
    listings_inactive INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS listings (
    listing_id      TEXT    PRIMARY KEY,
    source          TEXT    NOT NULL,
    title           TEXT,
    price           REAL    NOT NULL,
    price_str       TEXT,
    beds            REAL,
    baths           REAL,
    sqft            REAL,
    neighborhood    TEXT,
    region          TEXT,
    location        TEXT,
    url             TEXT,
    image_url       TEXT,
    days_ago        INTEGER,
    is_stale        INTEGER NOT NULL DEFAULT 0,
    -- Persistence fields
    first_seen      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    last_seen       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    is_active       INTEGER NOT NULL DEFAULT 1,
    scrape_count    INTEGER NOT NULL DEFAULT 1,   -- how many runs this listing appeared in
    is_new          INTEGER NOT NULL DEFAULT 0,   -- 1 for first 6 hrs after first_seen
    -- Computed fields (refreshed each run)
    fair_value      REAL,
    score           REAL,
    pct_under       REAL
);

CREATE TABLE IF NOT EXISTS user_alerts (
    alert_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT    NOT NULL UNIQUE,
    region      TEXT,
    min_beds    REAL,
    max_price   REAL,
    min_score   REAL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    is_enabled  INTEGER NOT NULL DEFAULT 1,
    last_sent   TEXT    DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS saved_searches (
    search_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email             TEXT    NOT NULL,
    name              TEXT    NOT NULL,
    beds_min          REAL,
    beds_max          REAL,
    baths_min         REAL,
    price_min         REAL,
    price_max         REAL,
    neighbourhood     TEXT,
    region            TEXT,
    min_score         REAL,
    max_commute       REAL,
    commute_dest      TEXT,
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    last_checked      TEXT,
    last_match_count  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(email, name)
);

CREATE INDEX IF NOT EXISTS idx_listings_active    ON listings(is_active);
CREATE INDEX IF NOT EXISTS idx_listings_source    ON listings(source);
CREATE INDEX IF NOT EXISTS idx_listings_region   ON listings(region);
CREATE INDEX IF NOT EXISTS idx_listings_last_seen ON listings(last_seen);

CREATE TABLE IF NOT EXISTS saved_listings (
    saved_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    email        TEXT    NOT NULL,
    listing_id   TEXT    NOT NULL,
    note         TEXT,
    saved_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(email, listing_id)
);

CREATE TABLE IF NOT EXISTS user_profiles (
    profile_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    email        TEXT    NOT NULL UNIQUE,
    preferred_beds    TEXT,
    max_price         REAL,
    neighbourhoods    TEXT,   -- JSON array of neighbourhood names
    commute_dest       TEXT,
    status             TEXT,   -- 'actively_looking' | 'open_to_moving' | 'just_browsing'
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_saved_listings_email ON saved_listings(email);
CREATE INDEX IF NOT EXISTS idx_user_profiles_email   ON user_profiles(email);
"""


_cached_conn = [None]

def _get_conn() -> sqlite3.Connection:
    """Return a single cached connection (created on first call)."""
    if _cached_conn[0] is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _cached_conn[0] = conn
    return _cached_conn[0]


def _reset_conn() -> None:
    """Close and clear the cached connection. Used by tests."""
    if _cached_conn[0] is not None:
        try:
            _cached_conn[0].close()
        except Exception:
            pass
        _cached_conn[0] = None


def init_db() -> None:
    """Run schema creation. Idempotent."""
    conn = _get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    # Note: do NOT close conn — it is cached in _cached_conn and reused


# ── Upsert Listings ───────────────────────────────────────────────────────────

def upsert_listings(rows: list[dict], scored_df: Optional[pd.DataFrame] = None) -> dict:
    """
    Upsert a list of listing dicts from the scraper.
    Listings not seen in a run are marked is_active = 0.

    Returns summary dict with run stats.
    """
    init_db()
    conn = _get_conn()
    run_sources = set(r.get("source", "unknown") for r in rows)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen_ids = set()

    try:
        new_count = 0
        upsert_count = 0

        for row in rows:
            listing_id = row.get("listing_id") or row.get("link", "")
            if not listing_id:
                continue
            seen_ids.add(listing_id)

            # Merge with scored data if provided
            fair_value = None
            score = None
            pct_under = None
            if scored_df is not None:
                link_col = row.get("link", "")
                try:
                    matches = scored_df[scored_df["link"] == link_col]
                    if not matches.empty:
                        sr = matches.iloc[0]
                        fair_value = float(sr["fair_value"]) if "fair_value" in sr and pd.notna(sr["fair_value"]) else None
                        score = float(sr["score"]) if "score" in sr and pd.notna(sr["score"]) else None
                        pct_under = float(sr["pct_under"]) if "pct_under" in sr and pd.notna(sr["pct_under"]) else None
                except (KeyError, ValueError, TypeError):
                    pass

            # Upsert: if already exists, update + increment scrape_count; if new, insert with scrape_count=1
            cur = conn.execute(
                "SELECT 1 FROM listings WHERE listing_id = ?", (listing_id,)
            ).fetchone()
            is_new = cur is None

            conn.execute("""
                INSERT INTO listings (
                    listing_id, source, title, price, price_str, beds, baths, sqft,
                    neighborhood, region, location, url, image_url, days_ago, is_stale,
                    first_seen, last_seen, is_active, scrape_count, is_new,
                    fair_value, score, pct_under
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(listing_id) DO UPDATE SET
                    source          = excluded.source,
                    title           = excluded.title,
                    price           = excluded.price,
                    price_str       = excluded.price_str,
                    beds            = excluded.beds,
                    baths           = excluded.baths,
                    sqft            = excluded.sqft,
                    neighborhood    = excluded.neighborhood,
                    region          = excluded.region,
                    location        = excluded.location,
                    url             = excluded.url,
                    image_url       = excluded.image_url,
                    days_ago        = excluded.days_ago,
                    is_stale        = excluded.is_stale,
                    last_seen       = excluded.last_seen,
                    is_active       = 1,
                    scrape_count    = listings.scrape_count + 1,
                    is_new          = 0,
                    fair_value      = excluded.fair_value,
                    score           = excluded.score,
                    pct_under       = excluded.pct_under
            """, (
                listing_id,
                row.get("source", "unknown"),
                row.get("title", ""),
                row.get("price", 0),
                row.get("price_str", ""),
                row.get("beds"),
                row.get("baths"),
                row.get("sqft"),
                row.get("neighborhood", ""),
                row.get("region", ""),
                row.get("location", ""),
                row.get("link", ""),
                row.get("image_url", ""),
                row.get("days_ago"),
                1 if row.get("is_stale") else 0,
                now, now, 1,  # first_seen, last_seen, is_active
                1,  # scrape_count for new inserts
                1,  # is_new = 1 for first 6 hrs after first_seen
                fair_value, score, pct_under,
            ))
            upsert_count += 1
            if is_new:
                new_count += 1

        # Mark listings not seen this run as inactive
        if seen_ids:
            placeholders = ",".join("?" * len(seen_ids))
            inactive = conn.execute(
                f"UPDATE listings SET is_active = 0 WHERE listing_id NOT IN ({placeholders}) AND is_active = 1",
                list(seen_ids)
            ).rowcount
        else:
            inactive = 0

        total_active = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE is_active = 1"
        ).fetchone()[0]

        conn.execute("""
            INSERT INTO scrape_runs (source, listings_seen, listings_new, listings_inactive)
            VALUES (?, ?, ?, ?)
        """, (",".join(sorted(run_sources)), len(rows), new_count, inactive))

        conn.commit()

        # Refresh is_new: mark listings first_seen within 6 hrs as is_new=1
        six_hrs_ago = (datetime.now(timezone.utc) - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE listings SET is_new = 1 WHERE is_active = 1 AND first_seen >= ?",
            (six_hrs_ago,)
        )
        conn.execute(
            "UPDATE listings SET is_new = 0 WHERE is_active = 1 AND first_seen < ?",
            (six_hrs_ago,)
        )
        conn.commit()

        return {
            "seen": len(rows),
            "upserted": upsert_count,
            "new": new_count,
            "total_active": total_active,
            "inactive_this_run": inactive,
        }
    finally:
        conn.close()


# ── Query Active Listings ──────────────────────────────────────────────────────

def get_active_listings(region: Optional[str] = None) -> pd.DataFrame:
    """Return all currently-active listings, optionally filtered by region."""
    conn = _get_conn()
    try:
        query = "SELECT * FROM listings WHERE is_active = 1"
        params = []
        if region:
            query += " AND region = ?"
            params.append(region)
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def get_listing_history(listing_id: str) -> pd.DataFrame:
    """Return historical data for a specific listing (all scrapes)."""
    conn = _get_conn()
    try:
        return pd.read_sql_query(
            "SELECT * FROM listings WHERE listing_id = ? ORDER BY last_seen DESC",
            conn, params=(listing_id,)
        )
    finally:
        conn.close()


def get_price_trends(neighborhood: str, beds: float) -> pd.DataFrame:
    """
    Return historical price trend for a neighbourhood + bedroom count.
    Useful for seeing how fair_value / prices change over time.
    """
    conn = _get_conn()
    try:
        return pd.read_sql_query("""
            SELECT
                last_seen       AS date,
                price,
                fair_value,
                score,
                pct_under
            FROM listings
            WHERE neighborhood = ?
              AND beds = ?
            ORDER BY last_seen ASC
        """, conn, params=(neighborhood, beds))
    finally:
        conn.close()


# ── Alert Management ──────────────────────────────────────────────────────────

def upsert_alert(email: str, region: Optional[str] = None,
                 min_beds: Optional[float] = None,
                 max_price: Optional[float] = None,
                 min_score: Optional[float] = None) -> None:
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO user_alerts (email, region, min_beds, max_price, min_score)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                region      = excluded.region,
                min_beds   = excluded.min_beds,
                max_price  = excluded.max_price,
                min_score  = excluded.min_score,
                last_sent  = NULL
        """, (email, region, min_beds, max_price, min_score))
        conn.commit()
    finally:
        conn.close()


# ── User Profile ──────────────────────────────────────────────────────────────

def upsert_profile(email: str,
                   preferred_beds: Optional[str] = None,
                   max_price: Optional[float] = None,
                   neighbourhoods: Optional[list[str]] = None,
                   commute_dest: Optional[str] = None,
                   status: Optional[str] = None) -> None:
    """
    Create or update a user profile.
    neighbourhoods: list of neighbourhood name strings, stored as JSON.
    """
    conn = _get_conn()
    neighbourhoods_json = json.dumps(neighbourhoods) if neighbourhoods else None
    conn.execute("""
        INSERT INTO user_profiles (email, preferred_beds, max_price, neighbourhoods, commute_dest, status)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            preferred_beds  = excluded.preferred_beds,
            max_price      = excluded.max_price,
            neighbourhoods = excluded.neighbourhoods,
            commute_dest   = excluded.commute_dest,
            status         = excluded.status,
            updated_at     = strftime('%Y-%m-%dT%H:%M:%SZ','now')
    """, (email, preferred_beds, max_price, neighbourhoods_json, commute_dest, status))
    conn.commit()


def get_profile(email: str) -> Optional[dict]:
    """Return user profile dict or None if not found."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM user_profiles WHERE email = ?", (email,)
    ).fetchone()
    if not row:
        return None
    cols = ['profile_id', 'email', 'preferred_beds', 'max_price', 'neighbourhoods',
            'commute_dest', 'status', 'created_at', 'updated_at']
    result = dict(zip(cols, row))
    # Parse JSON neighbourhoods
    if result.get('neighbourhoods') and isinstance(result['neighbourhoods'], str):
        try:
            result['neighbourhoods'] = json.loads(result['neighbourhoods'])
        except Exception:
            result['neighbourhoods'] = []
    return result


def get_pending_alerts(min_score: float = 0.5) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT a.*, l.listing_id, l.title, l.price, l.neighborhood, l.score, l.url
            FROM user_alerts a
            JOIN listings l ON l.is_active = 1
            WHERE a.is_enabled = 1 AND l.score >= ?
            ORDER BY a.created_at
        """, (min_score,)).fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM user_alerts LIMIT 0").description]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


# ── Saved Searches (MC-266) ───────────────────────────────────────────────────

def upsert_saved_search(
    email: str,
    name: str,
    beds_min: Optional[float] = None,
    beds_max: Optional[float] = None,
    baths_min: Optional[float] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    neighbourhood: Optional[str] = None,
    region: Optional[str] = None,
    min_score: Optional[float] = None,
    max_commute: Optional[float] = None,
    commute_dest: Optional[str] = None,
) -> int:
    """
    Create or update a saved search for an email-identified user.
    Returns the search_id.
    """
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO saved_searches (
                email, name, beds_min, beds_max, baths_min,
                price_min, price_max, neighbourhood, region,
                min_score, max_commute, commute_dest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email, name) DO UPDATE SET
                beds_min     = excluded.beds_min,
                beds_max     = excluded.beds_max,
                baths_min    = excluded.baths_min,
                price_min    = excluded.price_min,
                price_max    = excluded.price_max,
                neighbourhood= excluded.neighbourhood,
                region       = excluded.region,
                min_score    = excluded.min_score,
                max_commute  = excluded.max_commute,
                commute_dest = excluded.commute_dest
        """, (email, name,
              beds_min, beds_max, baths_min,
              price_min, price_max, neighbourhood, region,
              min_score, max_commute, commute_dest))
        conn.commit()
        search_id = conn.execute(
            "SELECT search_id FROM saved_searches WHERE email = ? AND name = ?",
            (email, name)
        ).fetchone()[0]
        return search_id
    finally:
        conn.close()


def get_saved_searches(email: str) -> list[dict]:
    """Return all saved searches for an email, with match counts computed."""
    conn = _get_conn()
    try:
        searches = conn.execute(
            "SELECT * FROM saved_searches WHERE email = ? ORDER BY created_at",
            (email,)
        ).fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM saved_searches LIMIT 0").description]
        results = []
        for row in searches:
            s = dict(zip(cols, row))
            # Count matching listings for this search
            match_count = _count_saved_search_matches(conn, s)
            s['match_count'] = match_count
            # Get top match
            s['top_match'] = _get_top_saved_search_match(conn, s)
            results.append(s)
        return results
    finally:
        conn.close()


def _count_saved_search_matches(conn: sqlite3.Connection, s: dict) -> int:
    """Count active listings matching a saved search's filters."""
    query = "SELECT COUNT(*) FROM listings WHERE is_active = 1"
    params = []
    if s.get('min_score') is not None:
        query += " AND score >= ?"
        params.append(s['min_score'])
    if s.get('region'):
        query += " AND region = ?"
        params.append(s['region'])
    if s.get('beds_min') is not None:
        query += " AND beds >= ?"
        params.append(s['beds_min'])
    if s.get('beds_max') is not None:
        query += " AND beds <= ?"
        params.append(s['beds_max'])
    if s.get('baths_min') is not None:
        query += " AND baths >= ?"
        params.append(s['baths_min'])
    if s.get('price_min') is not None:
        query += " AND price >= ?"
        params.append(s['price_min'])
    if s.get('price_max') is not None:
        query += " AND price <= ?"
        params.append(s['price_max'])
    if s.get('neighbourhood'):
        query += " AND neighborhood LIKE ?"
        params.append(f"%{s['neighbourhood']}%")
    return conn.execute(query, params).fetchone()[0]


def _get_top_saved_search_match(conn: sqlite3.Connection, s: dict) -> Optional[dict]:
    """Return the top-scoring listing matching a saved search's filters."""
    query = """
        SELECT * FROM listings WHERE is_active = 1
    """
    params = []
    if s.get('min_score') is not None:
        query += " AND score >= ?"
        params.append(s['min_score'])
    if s.get('region'):
        query += " AND region = ?"
        params.append(s['region'])
    if s.get('beds_min') is not None:
        query += " AND beds >= ?"
        params.append(s['beds_min'])
    if s.get('beds_max') is not None:
        query += " AND beds <= ?"
        params.append(s['beds_max'])
    if s.get('baths_min') is not None:
        query += " AND baths >= ?"
        params.append(s['baths_min'])
    if s.get('price_min') is not None:
        query += " AND price >= ?"
        params.append(s['price_min'])
    if s.get('price_max') is not None:
        query += " AND price <= ?"
        params.append(s['price_max'])
    if s.get('neighbourhood'):
        query += " AND neighborhood LIKE ?"
        params.append(f"%{s['neighbourhood']}%")
    query += " ORDER BY score DESC LIMIT 1"
    row = conn.execute(query, params).fetchone()
    if row:
        cols = [d[0] for d in conn.execute("SELECT * FROM listings LIMIT 0").description]
        return dict(zip(cols, row))
    return None


def delete_saved_search(search_id: int, email: str) -> bool:
    """Delete a saved search (must match email for ownership). Returns True if deleted."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM saved_searches WHERE search_id = ? AND email = ?",
            (search_id, email)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def touch_saved_search(search_id: int) -> None:
    """Update last_checked timestamp after a match evaluation."""
    conn = _get_conn()
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE saved_searches SET last_checked = ? WHERE search_id = ?",
            (now, search_id)
        )
        conn.commit()
    finally:
        conn.close()


def update_saved_search_match_count(search_id: int, count: int) -> None:
    """Update last_match_count after evaluation."""
    conn = _get_conn()
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE saved_searches SET last_match_count = ?, last_checked = ? WHERE search_id = ?",
            (count, now, search_id)
        )
        conn.commit()
    finally:
        conn.close()


# ── Saved Listings / Shortlist (MC-271) ──────────────────────────────────────

def upsert_saved_listing(email: str, listing_id: str, note: str = None) -> int:
    """
    Save (or update) a listing to the user's shortlist.
    Returns the saved_id.
    """
    init_db()
    conn = _get_conn()
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("""
            INSERT INTO saved_listings (email, listing_id, note, saved_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(email, listing_id) DO UPDATE SET
                note = excluded.note,
                saved_at = excluded.saved_at
        """, (email, listing_id, note, now))
        conn.commit()
        cur = conn.execute(
            "SELECT saved_id FROM saved_listings WHERE email=? AND listing_id=?",
            (email, listing_id)
        )
        row = cur.fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def get_saved_listings(email: str) -> list[dict]:
    """
    Get all saved listings for an email, enriched with listing data.
    Returns list of {saved_id, listing_id, note, saved_at, ...listing fields}.
    """
    conn = _get_conn()
    try:
        cur = conn.execute("""
            SELECT sl.saved_id, sl.listing_id, sl.note, sl.saved_at,
                   l.price, l.beds, l.baths, l.sqft, l.neighborhood,
                   l.region, l.url, l.days_ago, l.is_stale,
                   l.fair_value, l.score, l.pct_under
            FROM saved_listings sl
            JOIN listings l ON l.listing_id = sl.listing_id
            WHERE sl.email = ? AND l.is_active = 1
            ORDER BY sl.saved_at DESC
        """, (email,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def delete_saved_listing(saved_id: int, email: str) -> bool:
    """Remove a saved listing. Must match email for ownership. Returns True if deleted."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM saved_listings WHERE saved_id = ? AND email = ?",
            (saved_id, email)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def is_listing_saved(email: str, listing_id: str) -> bool:
    """Check if a listing is in the user's shortlist."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM saved_listings WHERE email=? AND listing_id=?",
            (email, listing_id)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    conn = _get_conn()
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    print("Tables:", [r[0] for r in cur.fetchall()])
    stats = conn.execute("SELECT COUNT(*) FROM listings WHERE is_active = 1").fetchone()
    print(f"Active listings: {stats[0]}")
    conn.close()


# ── SendGrid Email Alerts (MC-263) ────────────────────────────────────────────

def send_alert_email(
    to_email: str,
    listings: list[dict],
    unsubscribe_url: str,
) -> bool:
    """
    Send deal alert email via SendGrid.
    Returns True on success, False on failure.
    """
    import os
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        return False

    if not listings:
        return False

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content, PersonalizedEmail, EmailAddress
    except ImportError:
        return False

    medal = ["🥇", "🥈", "🥉"]
    lines = [
        f"🏠 <strong>Toronto Rent Deal Alert</strong> — {datetime.now().strftime('%B %d, %Y')}",
        f"<p>Found {len(listings)} matching deal{'s' if len(listings) > 1 else ''}:</p>",
        "<ul>",
    ]
    for i, row in enumerate(listings[:10]):
        emoji = medal[i] if i < 3 else "•"
        bed_str = f"{int(row['beds'])}BR" if row.get("beds", 0) > 0 else "Studio"
        pct = f"+{row['pct_under']:.1f}%" if row.get("pct_under", 0) > 0 else f"{row['pct_under']:.1f}%"
        lines.append(
            f"<li>{emoji} <a href=\"{row['url']}\">{row['neighborhood']}</a> "
            f"{bed_str} @ <strong>${row['price']:,}/mo</strong> "
            f"({pct} under FV ${int(row.get('fair_value', 0)):,}) — "
            f"<a href=\"{row['url']}\">View Listing</a></li>"
        )
    lines.append("</ul>")
    lines.append(
        f"<hr><p><a href=\"{unsubscribe_url}\">Unsubscribe from deal alerts</a> "
        f"| You subscribed with min_score={listings[0].get('min_score', '?')}</p>"
    )

    html_body = "<br>\n".join(lines)
    unsub_html = f"<p><a href=\"{unsubscribe_url}\">Unsubscribe</a></p>"
    full_html = html_body + unsub_html

    try:
        message = Mail(
            from_email=Email("alerts@rentfinder.ca"),
            to_emails=To(to_email),
            subject=f"🏠 Toronto Rent Deals — {len(listings)} new match{'s' if len(listings) > 1 else ''} today!",
            html_content=Content("text/html", full_html),
        )
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        return 200 <= response.status_code < 300
    except Exception:
        return False


def check_and_send_alerts() -> dict:
    """
    MC-263: After a scrape run, check all enabled alerts against active listings.
    For each user, find matching listings and send one email (max 1 per hour per user).
    Returns summary dict with sends, skips, errors.
    """
    from datetime import timedelta as _td
    conn = _get_conn()
    try:
        one_hour_ago = (datetime.now(timezone.utc) - _td(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        alerts = conn.execute("""
            SELECT alert_id, email, region, min_beds, max_price, min_score, last_sent
            FROM user_alerts WHERE is_enabled = 1
        """).fetchall()

        results = {"checked": len(alerts), "sent": 0, "skipped_rate_limit": 0, "skipped_no_matches": 0, "errors": 0}

        for alert in alerts:
            alert_id, email, region, min_beds, max_price, min_score, last_sent = alert

            # Rate limit: skip if last_sent within 1 hour
            if last_sent and last_sent >= one_hour_ago:
                results["skipped_rate_limit"] += 1
                continue

            # Build query for matching listings
            query = "SELECT * FROM listings WHERE is_active = 1 AND score >= ?"
            params = [min_score or 0.0]
            if region:
                query += " AND region = ?"
                params.append(region)
            if min_beds is not None:
                query += " AND beds >= ?"
                params.append(min_beds)
            if max_price is not None:
                query += " AND price <= ?"
                params.append(max_price)

            matches = conn.execute(query, params).fetchall()
            if not matches:
                results["skipped_no_matches"] += 1
                continue

            # Build unsubscribe URL (use app's base URL from env or localhost)
            base_url = os.environ.get("RENT_FINDER_URL", "http://localhost:5000")
            unsub_url = f"{base_url}/api/alerts/{email.replace('@', '%40')}"

            # Send email
            match_rows = [dict(zip([d[0] for d in conn.execute("SELECT * FROM listings LIMIT 0").description], m)) for m in matches]
            for row in match_rows:
                row["min_score"] = min_score

            sent_ok = send_alert_email(email, match_rows, unsub_url)
            if sent_ok:
                conn.execute(
                    "UPDATE user_alerts SET last_sent = ? WHERE alert_id = ?",
                    (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), alert_id)
                )
                conn.commit()
                results["sent"] += 1
            else:
                results["errors"] += 1

        return results
    finally:
        conn.close()

