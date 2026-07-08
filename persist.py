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

DATA_DIR = os.environ.get('RENT_DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
DB_PATH = os.path.join(DATA_DIR, "listings.db")


# ── Schema ────────────────────────────────────────────────────────────────────


# ── MC-312: Image URLs helpers ─────────────────────────────────────────────────
def _encode_image_urls(image_urls) -> Optional[str]:
    """Encode a list/tuple of photo URLs to a JSON string for storage.
    Returns None for empty/None input so the column stays NULL for listings
    without photos (cheaper than '[]' and distinguishable from "really empty").
    """
    if not image_urls:
        return None
    if isinstance(image_urls, (list, tuple)):
        cleaned = [u for u in image_urls if isinstance(u, str) and u.startswith("http")]
        if not cleaned:
            return None
        return json.dumps(cleaned, ensure_ascii=False)
    if isinstance(image_urls, str):
        # Already a JSON string? Try to parse and re-encode; else wrap as a list.
        try:
            parsed = json.loads(image_urls)
            if isinstance(parsed, list):
                return _encode_image_urls(parsed)
        except Exception:
            pass
        if image_urls.startswith("http"):
            return json.dumps([image_urls], ensure_ascii=False)
    return None


def _decode_image_urls(raw) -> list[str]:
    """Decode JSON-encoded image URLs from a DB cell. Always returns a list."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [u for u in raw if isinstance(u, str) and u.startswith("http")]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [u for u in parsed if isinstance(u, str) and u.startswith("http")]
        except Exception:
            pass
    return []


SCHEMA = """
CREATE TABLE IF NOT EXISTS scrape_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ts          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    source          TEXT    NOT NULL,
    listings_seen   INTEGER NOT NULL DEFAULT 0,
    listings_new    INTEGER NOT NULL DEFAULT 0,
    listings_inactive INTEGER NOT NULL DEFAULT 0,
    errors          INTEGER NOT NULL DEFAULT 0,
    duration_secs   REAL    NOT NULL DEFAULT 0
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
    image_urls_json TEXT,                       -- MC-312: JSON-encoded list of all photo URLs
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
    filters_json      TEXT    NOT NULL DEFAULT '{}',
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
    saved_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT    NOT NULL,
    listing_id     TEXT    NOT NULL,
    note           TEXT,
    price_at_save  REAL,   -- price when user saved the listing (for drop detection)
    saved_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(email, listing_id)
);

CREATE TABLE IF NOT EXISTS price_history (
    history_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT    NOT NULL,
    price      REAL    NOT NULL,
    seen_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(listing_id, seen_at)
);

CREATE TABLE IF NOT EXISTS price_drop_alerts (
    alert_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    email        TEXT    NOT NULL,
    listing_id   TEXT    NOT NULL,
    price_from   REAL    NOT NULL,
    price_to     REAL    NOT NULL,
    alerted_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(email, listing_id)  -- one alert per listing per user
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

CREATE TABLE IF NOT EXISTS telegram_subscriptions (
    sub_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_chat_id TEXT    NOT NULL UNIQUE,
    email            TEXT    NOT NULL,
    max_price        REAL,
    min_beds         REAL,
    neighbourhood    TEXT,
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    last_alerted     TEXT
);

CREATE TABLE IF NOT EXISTS sms_subscriptions (
    sub_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phone           TEXT    NOT NULL UNIQUE,
    email           TEXT    NOT NULL,
    max_price       REAL,
    min_beds        REAL,
    neighbourhood   TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    last_alerted    TEXT
);

CREATE TABLE IF NOT EXISTS craigslist_photo_cache (
    listing_url  TEXT    PRIMARY KEY,
    image_url    TEXT,                     -- NULL if negative cache (fetch failed)
    fetched_at   INTEGER NOT NULL,         -- unix epoch seconds
    is_negative  INTEGER NOT NULL DEFAULT 0 -- 1 if negative cache (error/404/no image)
);
"""


_cached_conn = [None]

def _get_conn() -> sqlite3.Connection:
    """Return a single cached connection (created on first call).
    If the cached connection is closed or broken, replace it with a new one.
    """
    if _cached_conn[0] is not None:
        try:
            # Test if connection is still open and usable
            _cached_conn[0].execute("SELECT 1")
            return _cached_conn[0]
        except Exception:
            _cached_conn[0] = None
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _cached_conn[0] = conn
    return conn


def _reset_conn() -> None:
    """Close and clear the cached connection. Used by tests."""
    if _cached_conn[0] is not None:
        try:
            _cached_conn[0].close()
        except Exception:
            pass
        _cached_conn[0] = None


def init_db() -> None:
    """Run schema creation. Idempotent. Also runs live migrations for existing DBs."""
    _reset_conn()  # ensure fresh conn for this init
    conn = _get_conn()
    conn.executescript(SCHEMA)
    conn.commit()

    # ── Live migrations: add new columns to existing tables ( idempotent ) ───
    for col, col_type in [
        ("errors",          "INTEGER NOT NULL DEFAULT 0"),
        ("duration_secs",   "REAL    NOT NULL DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE scrape_runs ADD COLUMN {col} {col_type}")
            conn.commit()
        except Exception:
            pass  # column already exists

    # MC-312: Add image_urls_json column to listings table (idempotent).
    # Stores JSON-encoded list of all photo URLs for the gallery carousel;
    # image_url (singular) remains as the first/primary photo for thumbnails.
    try:
        conn.execute("ALTER TABLE listings ADD COLUMN image_urls_json TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists

    # MC-322: Add filters_json column to saved_searches table (idempotent).
    # Stores JSON-encoded object of the *raw* filter state captured from the
    # deals page (buildParams() shape: keys like beds_min, source, sort,
    # hide_stale, max_subway, etc.) so the index.html Save-Current-Filters
    # button + /saved-searches Load button can round-trip a snapshot exactly.
    try:
        conn.execute("ALTER TABLE saved_searches ADD COLUMN filters_json TEXT NOT NULL DEFAULT '{}'")
        conn.commit()
    except Exception:
        pass  # column already exists

    # MC-326: Add notify_on_match + last_notification_sent to saved_searches.
    # Default 0 — users opt in via the bell icon on /saved-searches. Allow
    # NULL on notify_on_match (no NOT NULL) so the COALESCE trick in
    # upsert_saved_search ON CONFLICT can preserve the existing value when
    # the caller doesn't pass the param (older callers + our re-upsert path).
    try:
        conn.execute("ALTER TABLE saved_searches ADD COLUMN notify_on_match INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass  # column already exists
    try:
        conn.execute("ALTER TABLE saved_searches ADD COLUMN last_notification_sent TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists

    # Note: do NOT close conn — it is cached in _cached_conn and reused


# ── Upsert Listings ───────────────────────────────────────────────────────────

def upsert_listings(rows: list[dict], scored_df=None, source_errors: dict = None, source_durations: dict = None) -> dict:
    """
    Upsert a list of listing dicts from the scraper.
    Listings not seen in a run are marked is_active = 0.

    source_errors: dict of {source: error_count} for per-source error tracking.
    source_durations: dict of {source: duration_secs} for per-source timing.

    Returns summary dict with run stats.
    """
    init_db()
    conn = _get_conn()
    run_sources = set(r.get("source", "unknown") for r in rows)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen_ids = set()
    source_errors = source_errors or {}
    source_durations = source_durations or {}

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
                import pandas as _pd
                link_col = row.get("link", "")
                try:
                    matches = scored_df[scored_df["link"] == link_col]
                    if not matches.empty:
                        sr = matches.iloc[0]
                        fair_value = float(sr["fair_value"]) if "fair_value" in sr and _pd.notna(sr["fair_value"]) else None
                        score = float(sr["score"]) if "score" in sr and _pd.notna(sr["score"]) else None
                        pct_under = float(sr["pct_under"]) if "pct_under" in sr and _pd.notna(sr["pct_under"]) else None
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
                    neighborhood, region, location, url, image_url, image_urls_json,
                    days_ago, is_stale,
                    first_seen, last_seen, is_active, scrape_count, is_new,
                    fair_value, score, pct_under
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    image_urls_json = excluded.image_urls_json,
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
                _encode_image_urls(row.get("image_urls")),  # MC-312
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

            # MC-325: Record a price point for this listing so future scrapes
            # can detect price drops (current vs oldest in window). Uses the
            # SAME `now` timestamp and the SAME `conn` as the listings upsert
            # above (don't call upsert_price_history() — that closes the
            # cached connection on its finally clause, which would corrupt
            # the outer transaction in this loop). Skipped silently if price
            # is missing/non-positive (defensive — listings with no usable
            # price shouldn't pollute history).
            try:
                _price = float(row.get("price") or 0)
                if _price > 0:
                    conn.execute("""
                        INSERT INTO price_history (listing_id, price, seen_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(listing_id, seen_at) DO NOTHING
                    """, (listing_id, _price, now))
            except (TypeError, ValueError):
                pass

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

        # Insert one scrape_runs row per source with per-source metrics
        seen_ids_list = list(seen_ids)
        for src in sorted(run_sources):
            src_rows = [r for r in rows if r.get("source") == src]
            src_new = sum(
                1 for r in src_rows
                if r.get("listing_id") and
                conn.execute("SELECT 1 FROM listings WHERE listing_id = ?", (r["listing_id"],)).fetchone() is None
            )
            conn.execute("""
                INSERT INTO scrape_runs (source, listings_seen, listings_new, listings_inactive, errors, duration_secs)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                src,
                len(src_rows),
                src_new,
                0,  # inactive is tracked globally, not per-source
                source_errors.get(src, 0),
                source_durations.get(src, 0),
            ))

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

def get_active_listings(region: Optional[str] = None):
    """Return all currently-active listings as a DataFrame, optionally filtered by region."""
    import pandas as pd
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


def get_listing_history(listing_id: str):
    """Return historical data for a specific listing as a DataFrame."""
    import pandas as pd
    conn = _get_conn()
    try:
        return pd.read_sql_query(
            "SELECT * FROM listings WHERE listing_id = ? ORDER BY last_seen DESC",
            conn, params=(listing_id,)
        )
    finally:
        conn.close()


def get_price_trends(neighborhood: str, beds: float):
    """Return historical price trend for a neighbourhood + bedroom count as a DataFrame."""
    import pandas as pd
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
    filters_json: Optional[str] = None,
    notify_on_match: Optional[bool] = None,
) -> int:
    """
    Create or update a saved search for an email-identified user.
    Returns the search_id.

    MC-322: filters_json is a JSON-encoded object capturing the *raw* state of
    buildParams() keys at Save-Current-Filters time (beds_min, source, sort,
    hide_stale, max_subway, etc.) so /saved-searches Load can round-trip the
    filter bar back to the user verbatim. Existing callers that omit
    filters_json keep working — a default of '{}' is stored.

    MC-326: notify_on_match is an opt-in flag (default None = "don't change").
    The column has DEFAULT 0 in the schema. On INSERT, the column is OMITTED
    from the VALUES list when notify_on_match is None so it picks up the
    column default. On ON CONFLICT, notify_on_match = COALESCE(excluded....,
    notify_on_match) preserves the existing row's value when the caller
    didn't pass the param. Callers who want to flip the flag on/off must
    pass an explicit True/False.
    """
    if filters_json is None or filters_json == '':
        filters_json = '{}'
    conn = _get_conn()
    try:
        # Decide column list dynamically: when caller passes None for the
        # notify flag, the column OMITTED from INSERT so the schema DEFAULT 0
        # takes effect (and on conflict, the existing value is preserved by
        # the COALESCE expression on the SET clause — see below).
        cols = [
            "email", "name",
            "beds_min", "beds_max", "baths_min",
            "price_min", "price_max",
            "neighbourhood", "region",
            "min_score", "max_commute", "commute_dest",
            "filters_json",
        ]
        vals = [
            email, name,
            beds_min, beds_max, baths_min,
            price_min, price_max,
            neighbourhood, region,
            min_score, max_commute, commute_dest,
            filters_json,
        ]
        if notify_on_match is not None:
            cols.append("notify_on_match")
            vals.append(1 if notify_on_match else 0)
        placeholders = ",".join(["?"] * len(cols))

        # COALESCE trick: when excluded.notify_on_match is NULL (column omitted
        # from INSERT), SQLite leaves excluded.notify_on_match as the
        # column's default — which on a fresh insert is 0, but on a
        # conflict-update excluded.* refers to the row that *would* have been
        # inserted. To preserve the existing value on conflict when caller
        # omits the param, we use COALESCE(excluded.notify_on_match,
        # notify_on_match) which falls through to the existing column.
        update_set = """
            beds_min     = excluded.beds_min,
            beds_max     = excluded.beds_max,
            baths_min    = excluded.baths_min,
            price_min    = excluded.price_min,
            price_max    = excluded.price_max,
            neighbourhood= excluded.neighbourhood,
            region       = excluded.region,
            min_score    = excluded.min_score,
            max_commute  = excluded.max_commute,
            commute_dest = excluded.commute_dest,
            filters_json = excluded.filters_json"""
        if notify_on_match is not None:
            update_set += ",\n                notify_on_match = excluded.notify_on_match"

        sql = f"""
            INSERT INTO saved_searches ({", ".join(cols)})
            VALUES ({placeholders})
            ON CONFLICT(email, name) DO UPDATE SET
                {update_set}
        """
        conn.execute(sql, vals)
        conn.commit()
        search_id = conn.execute(
            "SELECT search_id FROM saved_searches WHERE email = ? AND name = ?",
            (email, name)
        ).fetchone()[0]
        return search_id
    finally:
        conn.close()


def get_saved_search_by_id(email: str, search_id: int) -> Optional[dict]:
    """
    Return a single saved search by id + email (ownership-gated). MC-322.

    Adds `filters_dict` (parsed JSON) alongside the raw `filters_json` string
    so callers don't have to rediscover parsing semantics. Returns None when
    the row is unknown or doesn't belong to the email.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM saved_searches WHERE search_id = ? AND email = ?",
            (search_id, email)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in conn.execute("SELECT * FROM saved_searches LIMIT 0").description]
        s = dict(zip(cols, row))
        raw = s.get('filters_json') or '{}'
        try:
            s['filters_dict'] = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
        except Exception:
            s['filters_dict'] = {}
        return s
    finally:
        conn.close()


def get_saved_searches(email: str) -> list[dict]:
    """Return all saved searches for an email, with match counts computed.

    MC-322: also parses filters_json and exposes it as filters_dict on each
    row so the /saved-searches page can round-trip filter values verbatim.
    """
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
            # MC-322: parse the snapshot JSON so the management page can render
            # the captured filter state (and the Load button can re-apply it).
            raw = s.get('filters_json') or '{}'
            try:
                s['filters_dict'] = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
            except Exception:
                s['filters_dict'] = {}
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


# ── Saved-Search Notify-On-Match (MC-326) ──────────────────────────────────

def _build_match_query_and_params(s: dict, since_iso: Optional[str] = None) -> tuple[str, list]:
    """
    Build the SQL + params that selects listings satisfying a saved search's
    filter criteria. Used by both count_listings_matching_saved_search and
    get_listings_matching_saved_search. Pure helper — no DB call.

    The 12 filter dimensions covered (matching the saved_searches schema + the
    MC-322 filters_json snapshot) are:
      - beds_min / beds_max
      - baths_min
      - price_min / price_max
      - neighbourhood (case-insensitive substring on neighborhood column)
      - region (exact match — Downtown, Midtown, East End, West End, Etobicoke, North York, Scarborough)
      - min_score (deal_score threshold)
      - filters_json keys (source, is_new=1, price_dropped=1)

    `since_iso`: optional ISO timestamp filter on listings.first_seen. The
    notify worker passes the user's last_notification_sent (or 24h ago if
    never) so only fresh listings trigger a notification.

    Returns (query_str, params_list) ready for `conn.execute(query, params)`.
    """
    query = "SELECT * FROM listings WHERE is_active = 1"
    params: list = []

    # --- Legacy columns ---
    if s.get('min_score') is not None:
        query += " AND score >= ?"
        params.append(float(s['min_score']))
    if s.get('region'):
        query += " AND region = ?"
        params.append(s['region'])
    if s.get('beds_min') is not None:
        query += " AND beds >= ?"
        params.append(float(s['beds_min']))
    if s.get('beds_max') is not None:
        query += " AND beds <= ?"
        params.append(float(s['beds_max']))
    if s.get('baths_min') is not None:
        query += " AND baths >= ?"
        params.append(float(s['baths_min']))
    if s.get('price_min') is not None:
        query += " AND price >= ?"
        params.append(float(s['price_min']))
    if s.get('price_max') is not None:
        query += " AND price <= ?"
        params.append(float(s['price_max']))
    if s.get('neighbourhood'):
        query += " AND neighborhood LIKE ?"
        params.append(f"%{s['neighbourhood']}%")

    # --- MC-322: filters_json snapshot (raw buildParams() keys) ---
    fd = s.get('filters_dict')
    if not fd and s.get('filters_json'):
        try:
            fd = json.loads(s['filters_json']) if isinstance(s['filters_json'], str) else {}
        except Exception:
            fd = {}
    if isinstance(fd, dict):
        # Treat sentinel values for empty filters (the deals page uses
        # '' / 'any' as empty markers) the same as not-set.
        def _nonempty_str(v):
            return v is not None and str(v).strip() not in ('', 'any', 'Any', 'ANY')
        if _nonempty_str(fd.get('source')):
            query += " AND source = ?"
            params.append(str(fd['source']).lower())
        # 'is_new' is the URL param for the Only NEW (6h) toggle on index.html.
        # We honor it only when explicitly True/1 to avoid regression.
        if fd.get('is_new') in (True, 1, 'true', 'True'):
            query += " AND is_new = 1"
        # Note: price_dropped filter (MC-325) is intentionally not wired here
        # because price_dropped is computed at query time via
        # get_price_dropped_listing_ids — there's no `price_dropped` column
        # on listings. A future MC could maintain such a column for fast
        # filtering; for now users on the deals page use the `?price_dropped=`
        # filter on /api/deals which goes through app.py's enrichment path.

    # --- since filter (for the notify worker) ---
    if since_iso:
        query += " AND first_seen >= ?"
        params.append(since_iso)
    return query, params


def count_listings_matching_saved_search(conn: sqlite3.Connection, s: dict, since_iso: Optional[str] = None) -> int:
    """
    Return the count of active listings satisfying a saved search's filters
    (optionally restricted to listings whose first_seen >= since_iso).

    Mirror of get_listings_matching_saved_search — used by the test suite
    and by the JS page to render "N matches" counts.

    MC-326: this function is what check_and_send_saved_search_alerts() walks
    to decide which subscribers should receive an email and what to put in it.
    """
    query, params = _build_match_query_and_params(s, since_iso=since_iso)
    row = conn.execute(query.replace("SELECT *", "SELECT COUNT(*)", 1), params).fetchone()
    return int(row[0]) if row else 0


def get_listings_matching_saved_search(s: dict, since_iso: Optional[str] = None, limit: int = 20) -> list[dict]:
    """
    Return the active listings satisfying a saved search's filters (optionally
    restricted to first_seen >= since_iso), capped at `limit`. Used by the
    notify worker to populate the email body.

    MC-326: returns at most `limit` rows ordered by score DESC then
    first_seen DESC so each email leads with the best / freshest match.
    """
    conn = _get_conn()
    try:
        query, params = _build_match_query_and_params(s, since_iso=since_iso)
        query += " ORDER BY score DESC, first_seen DESC LIMIT ?"
        params.append(int(limit))
        rows = conn.execute(query, params).fetchall()
        if not rows:
            return []
        cols = [d[0] for d in conn.execute("SELECT * FROM listings LIMIT 0").description]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def get_saved_searches_to_notify(conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    """
    Return all saved searches where notify_on_match = 1. The notify worker
    walks this list, builds per-search match lists, sends emails, and stamps
    last_notification_sent on each row it actually emailed.

    MC-326: this is the entry point for check_and_send_saved_search_alerts().
    Each row also exposes the parsed filters_dict (MC-322) so the worker can
    forward it to count_listings_matching_saved_search without re-parsing.
    """
    _conn = conn if conn is not None else _get_conn()
    try:
        rows = _conn.execute(
            "SELECT * FROM saved_searches WHERE notify_on_match = 1 ORDER BY search_id"
        ).fetchall()
        if not rows:
            return []
        cols = [d[0] for d in _conn.execute("SELECT * FROM saved_searches LIMIT 0").description]
        results = []
        for row in rows:
            s = dict(zip(cols, row))
            raw = s.get('filters_json') or '{}'
            try:
                s['filters_dict'] = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
            except Exception:
                s['filters_dict'] = {}
            results.append(s)
        return results
    finally:
        if conn is None:
            _conn.close()


def update_saved_search_notify(search_id: int, email: str, notify: bool) -> Optional[dict]:
    """
    Toggle the notify_on_match flag on a saved search. Returns the updated row
    on success, None if the search doesn't exist or doesn't belong to the
    email. Ownership-gated by email (matches the rest of the API surface).

    MC-326: the /saved-searches page's bell icon calls this via
    /api/saved-searches/<id>/toggle-notify, then refreshes.
    """
    conn = _get_conn()
    try:
        cur = conn.execute(
            "UPDATE saved_searches SET notify_on_match = ? WHERE search_id = ? AND email = ?",
            (1 if notify else 0, int(search_id), email),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM saved_searches WHERE search_id = ? AND email = ?",
            (int(search_id), email)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in conn.execute("SELECT * FROM saved_searches LIMIT 0").description]
        s = dict(zip(cols, row))
        return s
    finally:
        conn.close()


def mark_saved_search_notified(search_id: int) -> None:
    """
    Stamp last_notification_sent = NOW UTC. Called by check_and_send_saved_search_alerts
    after it has actually sent (or queued) the email, so the next run respects
    the rate-limit window.
    """
    conn = _get_conn()
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE saved_searches SET last_notification_sent = ? WHERE search_id = ?",
            (now, int(search_id)),
        )
        conn.commit()
    finally:
        conn.close()


def check_and_send_saved_search_alerts(
    min_hours_between: int = 24,
    send_fn=None,
) -> dict:
    """
    Walk every saved search with notify_on_match = 1. For each, find listings
    matching its filter that were first_seen since last_notification_sent (or
    in the last `min_hours_between` if the user has never been notified), then
    send one email per search listing the matches (subject line includes the
    saved-search name). Rate-limited per search: a search that was emailed
    within `min_hours_between` is skipped silently.

    Returns a summary dict:
      {
        'checked':    N,   # number of notify_on_match=1 rows
        'sent':       N,   # emails actually dispatched
        'skipped_no_matches': N,
        'skipped_rate_limit':  N,
        'errors':          N,
        'details':         [{search_id, email, name, sent, count, reason}, ...]
      }

    send_fn(to_email, search_name, matches, unsub_url) -> bool
      Optional injection for tests. When None, falls back to
      email_alerts.send_saved_search_alert_email. Tests pass a stub to verify
      the worker without touching SendGrid.

    MC-326: this is the function find_deals.py calls at the end of every cron
    run. On Render it runs in the same Python process as the Flask app, so
    SendGrid hits are live; on the test suite the send_fn stub is wired in.
    """
    from datetime import timedelta as _td
    init_db()
    conn = _get_conn()

    if send_fn is None:
        try:
            from email_alerts import send_saved_search_alert_email as _send_fn
            send_fn = _send_fn
        except Exception:
            send_fn = lambda *a, **kw: False

    base_url = os.environ.get("RENT_FINDER_URL", "http://localhost:5000")

    now_dt = datetime.now(timezone.utc)
    fallback_since = (now_dt - _td(hours=min_hours_between)).strftime("%Y-%m-%dT%H:%M:%SZ")

    results = {
        "checked": 0,
        "sent": 0,
        "skipped_no_matches": 0,
        "skipped_rate_limit": 0,
        "errors": 0,
        "details": [],
    }

    try:
        rows = get_saved_searches_to_notify(conn)
        results["checked"] = len(rows)

        for s in rows:
            search_id = s['search_id']
            email = (s.get('email') or '').strip()
            name = s.get('name') or f"Search {search_id}"
            last_sent = s.get('last_notification_sent')

            detail = {
                "search_id": search_id,
                "email": email,
                "name": name,
                "sent": False,
                "count": 0,
                "reason": None,
            }

            if not email:
                detail["reason"] = "no email on row"
                results["errors"] += 1
                results["details"].append(detail)
                continue

            # Rate limit per search
            if last_sent:
                try:
                    last_dt = datetime.strptime(last_sent, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    if (now_dt - last_dt).total_seconds() < min_hours_between * 3600:
                        detail["reason"] = f"rate_limit ({min_hours_between}h)"
                        results["skipped_rate_limit"] += 1
                        results["details"].append(detail)
                        continue
                except Exception:
                    pass  # malformed timestamp → fall through to default since

            since = last_sent if last_sent else fallback_since
            matches = get_listings_matching_saved_search(s, since_iso=since, limit=20)
            detail["count"] = len(matches)
            if not matches:
                detail["reason"] = "no_new_matches"
                results["skipped_no_matches"] += 1
                results["details"].append(detail)
                continue

            unsub_url = f"{base_url}/api/alerts/{email.replace('@', '%40')}"
            try:
                ok = bool(send_fn(email, name, matches, unsub_url))
            except Exception as e:
                detail["reason"] = f"send_error:{type(e).__name__}"
                results["errors"] += 1
                results["details"].append(detail)
                continue
            if not ok:
                detail["reason"] = "send_returned_false"
                results["errors"] += 1
                results["details"].append(detail)
                continue

            try:
                mark_saved_search_notified(search_id)
            except Exception:
                pass  # email sent, can't stamp — fine, will retry next run
            detail["sent"] = True
            detail["reason"] = "ok"
            results["sent"] += 1
            results["details"].append(detail)

        return results
    finally:
        conn.close()


# ── Saved Listings / Shortlist (MC-271) ──────────────────────────────────────

def upsert_saved_listing(email: str, listing_id: str, note: str = None, price_at_save: float = None) -> int:
    """
    Save (or update) a listing to the user's shortlist.
    price_at_save: price at time of saving (used for drop detection).
    Returns the saved_id.
    """
    init_db()
    conn = _get_conn()
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("""
            INSERT INTO saved_listings (email, listing_id, note, price_at_save, saved_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(email, listing_id) DO UPDATE SET
                note = excluded.note,
                price_at_save = COALESCE(excluded.price_at_save, price_at_save),
                saved_at = excluded.saved_at
        """, (email, listing_id, note, price_at_save, now))
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
    Returns list of {saved_id, listing_id, note, saved_at, price_at_save, ...listing fields}.
    """
    conn = _get_conn()
    try:
        cur = conn.execute("""
            SELECT sl.saved_id, sl.listing_id, sl.note, sl.saved_at, sl.price_at_save,
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


# ── Price History (MC-272) ─────────────────────────────────────────────────────

def upsert_price_history(listing_id: str, price: float) -> None:
    """
    Record a price point for a listing. Called after each scrape.
    Uses UNIQUE(listing_id, seen_at) to avoid duplicate entries per scrape run.
    """
    conn = _get_conn()
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("""
            INSERT INTO price_history (listing_id, price, seen_at)
            VALUES (?, ?, ?)
            ON CONFLICT(listing_id, seen_at) DO NOTHING
        """, (listing_id, price, now))
        conn.commit()
    finally:
        conn.close()


def get_listing_price_at_time(listing_id: str, at_iso: str) -> Optional[float]:
    """
    Get the price of a listing closest to (at or before) given ISO timestamp.
    Returns None if no history before that time.
    """
    conn = _get_conn()
    try:
        row = conn.execute("""
            SELECT price FROM price_history
            WHERE listing_id = ? AND seen_at <= ?
            ORDER BY seen_at DESC
            LIMIT 1
        """, (listing_id, at_iso)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_price_history(listing_id: str, days: int = 30) -> list:
    """
    Return price history for a listing over the last `days` days.
    Returns list of {"ts": ISO-str, "price": float} sorted oldest→newest.
    """
    conn = _get_conn()
    try:
        cutoff = (datetime.now(timezone.utc) - __import__('datetime').timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = conn.execute("""
            SELECT seen_at, price FROM price_history
            WHERE listing_id = ? AND seen_at >= ?
            ORDER BY seen_at ASC
        """, (listing_id, cutoff)).fetchall()
        return [{"ts": r[0], "price": r[1]} for r in rows]
    finally:
        conn.close()


def get_all_price_trends(days: int = 30) -> dict:
    """
    MC-282: Return a dict of {listing_id: trend} for all listings with >=2 price points.
    trend is "up", "down", or "stable".
    Uses a single SQL query for efficiency.
    """
    import datetime as _dt
    conn = _get_conn()
    try:
        cutoff = (datetime.now(timezone.utc) - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Get first and last price per listing using window functions (SQLite 3.25+)
        rows = conn.execute("""
            SELECT listing_id, first_price, last_price FROM (
                SELECT listing_id,
                       FIRST_VALUE(price) OVER (PARTITION BY listing_id ORDER BY seen_at ASC) AS first_price,
                       FIRST_VALUE(price) OVER (PARTITION BY listing_id ORDER BY seen_at DESC) AS last_price,
                       COUNT(*) OVER (PARTITION BY listing_id) AS cnt
                FROM price_history
                WHERE seen_at >= ?
            )
            WHERE cnt >= 2
            GROUP BY listing_id
        """, (cutoff,)).fetchall()
    finally:
        conn.close()

    trends = {}
    for row in rows:
        lid, first_p, last_p = row[0], row[1], row[2]
        if first_p is None or last_p is None:
            continue
        delta = last_p - first_p
        if delta < -0.5:
            trends[lid] = 'down'
        elif delta > 0.5:
            trends[lid] = 'up'
        else:
            trends[lid] = 'stable'
    return trends


def record_price_drop_alert(email: str, listing_id: str, price_from: float, price_to: float) -> None:
    """
    Record that we sent a price drop alert for (email, listing_id).
    Prevents duplicate alerts for the same drop.
    """
    conn = _get_conn()
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("""
            INSERT INTO price_drop_alerts (email, listing_id, price_from, price_to, alerted_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(email, listing_id) DO NOTHING
        """, (email, listing_id, price_from, price_to, now))
        conn.commit()
    finally:
        conn.close()


def has_price_drop_alert(email: str, listing_id: str) -> bool:
    """Check if we already sent a price drop alert for this email + listing."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM price_drop_alerts WHERE email=? AND listing_id=?",
            (email, listing_id)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_shortlisted_listings_with_prices(email: str) -> list[dict]:
    """
    Get shortlisted listings for email with current price and price_at_save.
    Returns list of {listing_id, price, price_at_save, ...}.
    """
    conn = _get_conn()
    try:
        cur = conn.execute("""
            SELECT sl.listing_id, l.price,
                   sl.price_at_save,
                   sl.email, sl.saved_id
            FROM saved_listings sl
            JOIN listings l ON l.listing_id = sl.listing_id
            WHERE sl.email = ? AND l.is_active = 1
        """, (email,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
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

# ── Telegram Subscriptions ────────────────────────────────────────────────────

def upsert_telegram_subscription(telegram_chat_id: str, email: str,
                                  max_price=None,
                                  min_beds=None,
                                  neighbourhood=None):
    init_db()
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO telegram_subscriptions
              (telegram_chat_id, email, max_price, min_beds, neighbourhood, active)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(telegram_chat_id) DO UPDATE SET
              email       = excluded.email,
              max_price   = excluded.max_price,
              min_beds    = excluded.min_beds,
              neighbourhood = excluded.neighbourhood,
              active      = 1
        """, (telegram_chat_id, email, max_price, min_beds, neighbourhood))
        conn.commit()
    finally:
        conn.close()


def get_telegram_subscription(telegram_chat_id: str):
    conn = _get_conn()
    try:
        row = conn.execute("""
            SELECT sub_id, telegram_chat_id, email, max_price, min_beds,
                   neighbourhood, active, created_at, last_alerted
            FROM telegram_subscriptions
            WHERE telegram_chat_id = ?
        """, (telegram_chat_id,)).fetchone()
        if not row:
            return None
        cols = ['sub_id', 'telegram_chat_id', 'email', 'max_price', 'min_beds',
                'neighbourhood', 'active', 'created_at', 'last_alerted']
        return dict(zip(cols, row))
    finally:
        conn.close()


def get_active_telegram_subscriptions():
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT sub_id, telegram_chat_id, email, max_price, min_beds,
                   neighbourhood, active, created_at, last_alerted
            FROM telegram_subscriptions
            WHERE active = 1
        """).fetchall()
        cols = ['sub_id', 'telegram_chat_id', 'email', 'max_price', 'min_beds',
                'neighbourhood', 'active', 'created_at', 'last_alerted']
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def deactivate_telegram_subscription(telegram_chat_id: str):
    conn = _get_conn()
    try:
        conn.execute("UPDATE telegram_subscriptions SET active = 0 WHERE telegram_chat_id = ?",
                     (telegram_chat_id,))
        conn.commit()
    finally:
        conn.close()


def update_telegram_last_alerted(telegram_chat_id: str):
    conn = _get_conn()
    try:
        conn.execute("""
            UPDATE telegram_subscriptions
            SET last_alerted = strftime('%Y-%m-%dT%H:%M:%SZ','now')
            WHERE telegram_chat_id = ?
        """, (telegram_chat_id,))
        conn.commit()
    finally:
        conn.close()


# ── SMS Subscriptions ─────────────────────────────────────────────────────────

def upsert_sms_subscription(phone: str, email: str,
                              max_price: float = None,
                              min_beds: float = None,
                              neighbourhood: str = None) -> int:
    """
    Create or update an SMS subscription (phone number).
    phone must be in E.164 format (e.g. +14165551234).

    Returns the sub_id.
    """
    init_db()
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO sms_subscriptions (phone, email, max_price, min_beds, neighbourhood)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                email         = excluded.email,
                max_price     = excluded.max_price,
                min_beds      = excluded.min_beds,
                neighbourhood = excluded.neighbourhood,
                active        = 1
        """, (phone, email, max_price, min_beds, neighbourhood))
        conn.commit()
        row = conn.execute(
            "SELECT sub_id FROM sms_subscriptions WHERE phone = ?", (phone,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_sms_subscription(phone: str) -> Optional[dict]:
    """Return active SMS subscription dict or None."""
    init_db()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM sms_subscriptions WHERE phone = ? AND active = 1",
            (phone,)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in conn.execute(
            "SELECT * FROM sms_subscriptions WHERE 1=0"
        ).description]
        return dict(zip(cols, row))
    finally:
        conn.close()


def get_active_sms_subscriptions() -> list[dict]:
    """Return all active SMS subscriptions."""
    init_db()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM sms_subscriptions WHERE active = 1"
        ).fetchall()
        cols = [d[0] for d in conn.execute(
            "SELECT * FROM sms_subscriptions WHERE 1=0"
        ).description]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def deactivate_sms_subscription(phone: str):
    """Deactivate an SMS subscription."""
    init_db()
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE sms_subscriptions SET active = 0 WHERE phone = ?",
            (phone,)
        )
        conn.commit()
    finally:
        conn.close()


def update_sms_last_alerted(phone: str):
    """Update last_alerted timestamp for an SMS subscription."""
    init_db()
    conn = _get_conn()
    try:
        conn.execute("""
            UPDATE sms_subscriptions
            SET last_alerted = strftime('%Y-%m-%dT%H:%M:%SZ','now')
            WHERE phone = ?
        """, (phone,))
        conn.commit()
    finally:
        conn.close()



# ── Craigslist photo cache (MC-308) ───────────────────────────────────────
#
# On-demand fetch of Craigslist listing photos. Search pages don't include
# thumbnails (MC-307 finding), so each detail-view needs an HTTP fetch of the
# individual listing page. Cached per listing_url with TTL:
#   - Positive hits: POSITIVE_TTL_SECS (14 days)
#   - Negative hits (404/timeout/parse-fail): NEGATIVE_TTL_SECS (1 hour)
#
# Cache row layout: craigslist_photo_cache
#   listing_url TEXT PRIMARY KEY
#   image_url   TEXT NULL                  -- NULL when is_negative=1
#   fetched_at  INTEGER (unix epoch secs)
#   is_negative INTEGER (0/1)

POSITIVE_TTL_SECS = 14 * 24 * 60 * 60      # 14 days
NEGATIVE_TTL_SECS = 60 * 60                # 1 hour


def _cl_photo_cache_fresh(row, now_ts):
    # True if a cached row is still within its TTL window.
    if not row:
        return False
    elapsed = now_ts - int(row[2])
    if int(row[3]) == 1:
        return elapsed < NEGATIVE_TTL_SECS
    return elapsed < POSITIVE_TTL_SECS


def get_craigslist_photo_cache(listing_url, *, now_ts=None):
    # Return cached photo row for listing_url if it exists and is fresh.
    # Negative hits return with image_url=None and is_negative=1 — caller
    # should treat them as 'we know there's no photo for this one, don't retry'.
    if not listing_url:
        return None
    init_db()
    conn = _get_conn()
    try:
        cur = conn.execute(
            'SELECT listing_url, image_url, fetched_at, is_negative '
            'FROM craigslist_photo_cache WHERE listing_url = ?',
            (listing_url,)
        )
        row = cur.fetchone()
        if not row:
            return None
        now = now_ts if now_ts is not None else int(datetime.now(timezone.utc).timestamp())
        if not _cl_photo_cache_fresh(row, now):
            return None
        return {
            'listing_url': row[0],
            'image_url': row[1],
            'fetched_at': int(row[2]),
            'is_negative': int(row[3]),
        }
    finally:
        conn.close()


def upsert_craigslist_photo_cache(
    listing_url,
    image_url,
    *,
    is_negative=False,
    now_ts=None,
):
    # Insert or replace a cache row for listing_url.
    if not listing_url:
        return
    init_db()
    conn = _get_conn()
    try:
        now = now_ts if now_ts is not None else int(datetime.now(timezone.utc).timestamp())
        conn.execute(
            "INSERT INTO craigslist_photo_cache (listing_url, image_url, fetched_at, is_negative)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(listing_url) DO UPDATE SET"
            "     image_url = excluded.image_url,"
            "     fetched_at = excluded.fetched_at,"
            "     is_negative = excluded.is_negative",
            (listing_url, image_url, now, 1 if is_negative else 0),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_cl_photo_fetches(window_secs, *, now_ts=None):
    # Count cache rows written within the last window_secs. Used by the rate
    # limiter to enforce max fetches per cron cycle.
    init_db()
    conn = _get_conn()
    try:
        now = now_ts if now_ts is not None else int(datetime.now(timezone.utc).timestamp())
        cur = conn.execute(
            'SELECT COUNT(*) AS n FROM craigslist_photo_cache '
            'WHERE fetched_at >= ?',
            (now - window_secs,)
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def reset_craigslist_photo_cache():
    # Clear the entire craigslist_photo_cache table. Tests only.
    init_db()
    conn = _get_conn()
    try:
        conn.execute('DELETE FROM craigslist_photo_cache')
        conn.commit()
    finally:
        conn.close()


# ── Price Drop Detection (MC-325) ─────────────────────────────────────────────

def get_listing_price_drop(listing_id: str, days: int = 14, now_ts: Optional[str] = None) -> Optional[dict]:
    """
    MC-325: Compute a price drop for a listing by comparing its current price
    against the OLDEST price recorded in the price_history table within the
    last `days` days. Returns None if fewer than 2 price points exist or if
    the current price isn't cheaper than the oldest recorded price.

    Returned dict (or None):
        {
            'listing_id':     str,
            'from_price':     float,   # oldest price in the window
            'to_price':       float,   # current (latest) price in the window
            'drop_amount':    float,   # from_price - to_price (>= 0)
            'drop_pct':       float,   # drop_amount / from_price * 100 (>= 0)
            'from_ts':        str,     # ISO timestamp of the oldest price
            'to_ts':          str,     # ISO timestamp of the latest price
            'days_ago_from':  int,     # (now - from_ts) in whole days
        }
    """
    import datetime as _dt
    conn = _get_conn()
    try:
        # Use the supplied "now" if given (tests use this to make
        # days_ago_from deterministic). Otherwise use UTC now.
        if now_ts:
            now_dt = _dt.datetime.strptime(now_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
        else:
            now_dt = datetime.now(timezone.utc)
        cutoff = (now_dt - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = conn.execute("""
            SELECT seen_at, price FROM price_history
            WHERE listing_id = ? AND seen_at >= ?
            ORDER BY seen_at ASC
        """, (listing_id, cutoff)).fetchall()
        if len(rows) < 2:
            return None
        first = rows[0]
        last = rows[-1]
        from_price = float(first[1])
        to_price = float(last[1])
        if from_price <= 0 or to_price >= from_price:
            return None
        drop_amount = from_price - to_price
        drop_pct = (drop_amount / from_price) * 100.0
        from_ts = first[0]
        to_ts = last[0]
        # Days ago of the from price
        from_dt = _dt.datetime.strptime(from_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
        days_ago_from = int((now_dt - from_dt).total_seconds() // 86400)
        return {
            'listing_id': listing_id,
            'from_price': from_price,
            'to_price': to_price,
            'drop_amount': drop_amount,
            'drop_pct': drop_pct,
            'from_ts': from_ts,
            'to_ts': to_ts,
            'days_ago_from': days_ago_from,
        }
    finally:
        conn.close()


def get_price_dropped_listing_ids(
    days: int = 14,
    min_drop_pct: float = 5.0,
    now_ts: Optional[str] = None,
) -> set:
    """
    MC-325: Return the set of listing_ids whose price has dropped by at least
    `min_drop_pct` percent over the last `days` days (compared to the OLDEST
    recorded price point in the window).

    Listings with <2 price points in the window are excluded (no drop can be
    proven). Uses the listing_id values from the currently active SQLite
    listings table to bound the scan (only active listings are interesting).
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT listing_id FROM listings WHERE is_active = 1"
        ).fetchall()
        active_ids = [r[0] for r in rows]
    finally:
        conn.close()

    dropped: set = set()
    for lid in active_ids:
        info = get_listing_price_drop(lid, days=days, now_ts=now_ts)
        if info is not None and info['drop_pct'] >= min_drop_pct:
            dropped.add(lid)
    return dropped


def get_all_listing_price_drops(
    days: int = 14,
    min_drop_pct: float = 5.0,
    now_ts: Optional[str] = None,
) -> dict:
    """
    MC-325: Return {listing_id: drop_info} for all active listings with a
    confirmed price drop of >= min_drop_pct. Used by app.py to enrich
    /api/deals rows in a single batched call rather than per-row.
    """
    ids = get_price_dropped_listing_ids(days=days, min_drop_pct=min_drop_pct, now_ts=now_ts)
    return {
        lid: get_listing_price_drop(lid, days=days, now_ts=now_ts)
        for lid in ids
    }


def get_neighborhood_price_history(
    neighborhood: str,
    days: int = 30,
    now_ts: Optional[str] = None,
) -> list:
    """
    MC-328: Aggregate price history for a single neighbourhood across all
    active listings in it, bucketed by calendar day (UTC).

    Joins price_history → listings (active only) on listing_id, filters by
    neighbourhood name (case-insensitive), and returns one row per day with
    median price + median $/sqft for that day. Days with no listings in
    the neighbourhood are simply absent from the output (the chart's job
    to draw a continuous line — empty gaps communicate "no data").

    Returned list is sorted ascending by date and contains dicts:
        {
            'date_iso':               'YYYY-MM-DD',
            'median_price':           float | None,
            'median_price_per_sqft':  float | None,
            'listing_count':          int,
            'dollar_per_sqft_min':    float | None,
            'dollar_per_sqft_max':    float | None,
        }

    Notes / caveats:
    - Listings with NULL sqft are excluded from the $/sqft calculations
      but are still counted in listing_count and included in the price
      median (sqft vs no-sqft are different signals).
    - If the neighbourhood has zero active listings OR zero price_history
      rows in the window, the returned list is `[]` (not None — the
      endpoint interprets an empty list as "no chart, show empty state").
    - The neighbourhood name is matched case-insensitively but stored as
      given in the listings table (the endpoint resolves to the canonical
      name first via _slug_to_neighborhood, so this is always the
      canonical spelling).
    - `now_ts` is exposed for tests that need deterministic date math.
    """
    import datetime as _dt
    if not neighborhood:
        return []

    conn = _get_conn()
    try:
        if now_ts:
            now_dt = _dt.datetime.strptime(now_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
        else:
            now_dt = datetime.now(timezone.utc)
        cutoff = (now_dt - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Pull (date, price, sqft) for every price_history row of an active
        # listing in this neighbourhood within the window. We bucket in
        # Python rather than SQL so the $/sqft median per bucket is easy
        # to compute without window functions across NULL values.
        rows = conn.execute("""
            SELECT ph.seen_at, ph.price, l.sqft
            FROM price_history ph
            JOIN listings l ON l.listing_id = ph.listing_id
            WHERE l.is_active = 1
              AND l.neighborhood IS NOT NULL
              AND lower(l.neighborhood) = lower(?)
              AND ph.seen_at >= ?
            ORDER BY ph.seen_at ASC
        """, (neighborhood, cutoff)).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    buckets: dict = {}
    for seen_at, price, sqft in rows:
        # ISO date prefix = the bucket key (UTC day)
        day = (seen_at or '')[:10]
        if not day or len(day) < 10:
            continue
        if day not in buckets:
            buckets[day] = {'prices': [], 'pps': []}
        # price can be None/NoneType if seeded with NULL (defensive)
        if price is None:
            continue
        try:
            p = float(price)
        except (TypeError, ValueError):
            continue
        if p <= 0:
            continue
        buckets[day]['prices'].append(p)
        # $/sqft: only include rows where sqft is a positive number
        if sqft is None:
            continue
        try:
            s = float(sqft)
        except (TypeError, ValueError):
            continue
        if s > 0:
            buckets[day]['pps'].append(p / s)

    out: list = []
    for day in sorted(buckets.keys()):
        prices = sorted(buckets[day]['prices'])
        pps = sorted(buckets[day]['pps'])
        out.append({
            'date_iso': day,
            'median_price': _median_of(prices),
            'median_price_per_sqft': _median_of(pps) if pps else None,
            'listing_count': len(prices),
            'dollar_per_sqft_min': min(pps) if pps else None,
            'dollar_per_sqft_max': max(pps) if pps else None,
        })
    return out


def _median_of(values: list) -> Optional[float]:
    """Local median helper that returns None for empty input. Kept private
    to this module — app.py has its own _median which returns None too."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    if n % 2:
        return float(s[n // 2])
    return float((s[n // 2 - 1] + s[n // 2]) / 2)


def seed_price_history_for_listing(listing_id: str, price: float, seen_at: str) -> bool:
    """
    MC-325: Insert a single price_history row. Returns True if the row was
    inserted, False if (listing_id, seen_at) already exists. Used by the
    backfill script to seed historical price points so get_listing_price_drop()
    has data to compare against immediately after MC-325 ships.
    """
    conn = _get_conn()
    try:
        cur = conn.execute("""
            INSERT INTO price_history (listing_id, price, seen_at)
            VALUES (?, ?, ?)
            ON CONFLICT(listing_id, seen_at) DO NOTHING
        """, (listing_id, price, seen_at))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
