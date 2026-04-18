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

import sqlite3, os
from datetime import datetime, timezone
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
    is_enabled  INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_listings_active    ON listings(is_active);
CREATE INDEX IF NOT EXISTS idx_listings_source    ON listings(source);
CREATE INDEX IF NOT EXISTS idx_listings_region   ON listings(region);
CREATE INDEX IF NOT EXISTS idx_listings_last_seen ON listings(last_seen);
"""


def _get_conn() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Run schema creation. Idempotent."""
    conn = _get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


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
                    first_seen, last_seen, is_active, scrape_count, fair_value, score, pct_under
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                region    = excluded.region,
                min_beds  = excluded.min_beds,
                max_price = excluded.max_price,
                min_score = excluded.min_score
        """, (email, region, min_beds, max_price, min_score))
        conn.commit()
    finally:
        conn.close()


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


if __name__ == "__main__":
    init_db()
    conn = _get_conn()
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    print("Tables:", [r[0] for r in cur.fetchall()])
    stats = conn.execute("SELECT COUNT(*) FROM listings WHERE is_active = 1").fetchone()
    print(f"Active listings: {stats[0]}")
    conn.close()
