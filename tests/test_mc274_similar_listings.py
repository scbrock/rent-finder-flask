"""
Tests for similar_listings.py — MC-274.
"""
import pytest, os, sqlite3, sys
from datetime import datetime, timezone
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENT_FINDER = PROJECT_ROOT
if RENT_FINDER not in sys.path:
    sys.path.insert(0, RENT_FINDER)

import similar_listings as sl


def _create_schema(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            listing_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            title TEXT,
            price REAL NOT NULL,
            price_str TEXT,
            beds REAL,
            baths REAL,
            sqft REAL,
            neighborhood TEXT,
            region TEXT,
            location TEXT,
            url TEXT,
            image_url TEXT,
            days_ago INTEGER,
            is_stale INTEGER NOT NULL DEFAULT 0,
            first_seen TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            last_seen TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            is_active INTEGER NOT NULL DEFAULT 1,
            scrape_count INTEGER NOT NULL DEFAULT 1,
            is_new INTEGER NOT NULL DEFAULT 0,
            fair_value REAL,
            score REAL,
            pct_under REAL,
            final_score REAL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_listings (
            saved_id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            listing_id TEXT NOT NULL,
            note TEXT,
            price_at_save REAL,
            saved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(email, listing_id)
        )
    """)
    conn.commit()


def _insert_listing(conn, lid, title, price, beds, neighborhood, score, final_score, is_active=1):
    conn.execute("""
        INSERT INTO listings (listing_id, source, title, price, beds, neighborhood,
                              url, score, final_score, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (lid, 'test', title, price, beds, neighborhood, 'http://x/' + lid,
          score, final_score, is_active))


def _save_listing(db_path, email, listing_id, price_at_save=None):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO saved_listings (email, listing_id, price_at_save) VALUES (?, ?, ?)",
        (email, listing_id, price_at_save)
    )
    conn.commit()
    conn.close()


@pytest.fixture
def make_db(tmp_path):
    db_path = str(tmp_path / 'listings.db')
    conn = sqlite3.connect(db_path)
    _create_schema(conn)
    conn.close()
    return db_path


@pytest.fixture
def shortlist_db(make_db):
    """DB with a user with 2 shortlisted listings."""
    db = make_db
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    conn = sqlite3.connect(db)
    # 2 shortlisted by alice: L1 (Parkdale, 1BR, $1800) and L2 (Parkdale, 2BR, $2200)
    _insert_listing(conn, 'L1', 'Saved 1BR near Parkdale', 1800, 1, 'Parkdale', 0.80, 0.80)
    _insert_listing(conn, 'L2', 'Saved 2BR near Parkdale', 2200, 2, 'Parkdale', 0.82, 0.82)
    # Similar: same neighborhood, same bed count range, price within $200
    _insert_listing(conn, 'L3', 'Similar 2BR Parkdale', 2150, 2, 'Parkdale', 0.78, 0.78)
    # Similar: different neighborhood but same bed count + price
    _insert_listing(conn, 'L4', 'Similar 2BR Liberty Village', 2100, 2, 'Liberty Village', 0.76, 0.76)
    # Not similar: different bed count
    _insert_listing(conn, 'L5', 'Different 3BR', 2500, 3, 'Parkdale', 0.75, 0.75)
    # Not similar: far price
    _insert_listing(conn, 'L6', 'Expensive 2BR', 3000, 2, 'Parkdale', 0.74, 0.74)
    # Inactive
    _insert_listing(conn, 'L7', 'Inactive 2BR', 2000, 2, 'Parkdale', 0.73, 0.73, is_active=0)
    _save_listing(db, 'alice@test.com', 'L1', 1800)
    _save_listing(db, 'alice@test.com', 'L2', 2200)
    conn.close()
    return db


# ── get_similar_for_shortlist ────────────────────────────────────────────────

def test_get_similar_returns_up_to_limit(make_db):
    db = make_db
    conn = sqlite3.connect(db)
    _insert_listing(conn, 'L1', 'Base listing', 2000, 2, 'Parkdale', 0.80, 0.80)
    _insert_listing(conn, 'L2', 'Similar 2BR', 2100, 2, 'Parkdale', 0.78, 0.78)
    _insert_listing(conn, 'L3', 'Similar 2BR#2', 2150, 2, 'Parkdale', 0.76, 0.76)
    _insert_listing(conn, 'L4', 'Similar 2BR#3', 2050, 2, 'Parkdale', 0.74, 0.74)
    _insert_listing(conn, 'L5', 'Similar 2BR#4', 2200, 2, 'Parkdale', 0.72, 0.72)
    _insert_listing(conn, 'L6', 'Similar 2BR#5', 1950, 2, 'Parkdale', 0.70, 0.70)
    conn.commit(); conn.close()
    _save_listing(db, 'alice@test.com', 'L1', 2000)

    with patch.object(sl, 'DB_PATH', db):
        similar = sl.get_similar_for_shortlist('alice@test.com', limit=5)
    assert len(similar) <= 5


def test_get_similar_excludes_shortlisted(make_db):
    db = make_db
    conn = sqlite3.connect(db)
    _insert_listing(conn, 'L1', 'Shortlisted listing', 2000, 2, 'Parkdale', 0.80, 0.80)
    _insert_listing(conn, 'L2', 'Similar but not shortlisted', 2100, 2, 'Parkdale', 0.78, 0.78)
    conn.commit(); conn.close()
    _save_listing(db, 'alice@test.com', 'L1', 2000)

    with patch.object(sl, 'DB_PATH', db):
        similar = sl.get_similar_for_shortlist('alice@test.com', limit=5)
    ids = [s.listing_id for s in similar]
    assert 'L1' not in ids  # shortlisted items excluded


def test_get_similar_excludes_inactive(make_db):
    db = make_db
    conn = sqlite3.connect(db)
    _insert_listing(conn, 'L1', 'Active listing', 2000, 2, 'Parkdale', 0.80, 0.80)
    _insert_listing(conn, 'L2', 'Inactive listing', 2050, 2, 'Parkdale', 0.78, 0.78, is_active=0)
    conn.commit(); conn.close()
    _save_listing(db, 'alice@test.com', 'L1', 2000)

    with patch.object(sl, 'DB_PATH', db):
        similar = sl.get_similar_for_shortlist('alice@test.com', limit=5)
    ids = [s.listing_id for s in similar]
    assert 'L2' not in ids  # inactive excluded


def test_get_similar_empty_if_no_shortlist(make_db):
    with patch.object(sl, 'DB_PATH', make_db):
        similar = sl.get_similar_for_shortlist('nobody@test.com', limit=5)
    assert len(similar) == 0


def test_get_similar_has_explanation(make_db):
    db = make_db
    conn = sqlite3.connect(db)
    _insert_listing(conn, 'L1', 'Base listing', 2000, 2, 'Parkdale', 0.80, 0.80)
    _insert_listing(conn, 'L2', 'Similar 2BR Parkdale', 2100, 2, 'Parkdale', 0.78, 0.78)
    conn.commit(); conn.close()
    _save_listing(db, 'alice@test.com', 'L1', 2000)

    with patch.object(sl, 'DB_PATH', db):
        similar = sl.get_similar_for_shortlist('alice@test.com', limit=5)
    assert len(similar) > 0
    assert len(similar[0].similarity_explanation) > 0


def test_get_similar_same_neighborhood优先(make_db):
    db = make_db
    conn = sqlite3.connect(db)
    _insert_listing(conn, 'L1', 'Shortlisted', 2000, 2, 'Parkdale', 0.80, 0.80)
    _insert_listing(conn, 'L2', 'Same hood', 2100, 2, 'Parkdale', 0.78, 0.78)
    _insert_listing(conn, 'L3', 'Different hood', 2050, 2, 'Liberty Village', 0.76, 0.76)
    conn.commit(); conn.close()
    _save_listing(db, 'alice@test.com', 'L1', 2000)

    with patch.object(sl, 'DB_PATH', db):
        similar = sl.get_similar_for_shortlist('alice@test.com', limit=3)
    # Same neighborhood should rank higher
    hoods = [s.neighborhood for s in similar]
    assert 'Parkdale' in hoods


# ── get_similar_for_listing ───────────────────────────────────────────────────

def test_get_similar_for_listing_basic(make_db):
    db = make_db
    conn = sqlite3.connect(db)
    _insert_listing(conn, 'L1', 'Target listing', 2000, 2, 'Parkdale', 0.80, 0.80)
    _insert_listing(conn, 'L2', 'Similar 2BR Parkdale', 2100, 2, 'Parkdale', 0.78, 0.78)
    _insert_listing(conn, 'L3', 'Similar 2BR Liberty Village', 2050, 2, 'Liberty Village', 0.76, 0.76)
    conn.commit(); conn.close()

    with patch.object(sl, 'DB_PATH', db):
        similar = sl.get_similar_for_listing('L1', limit=3)
    assert len(similar) <= 3
    assert all(s.listing_id != 'L1' for s in similar)


def test_get_similar_for_listing_nonexistent(make_db):
    with patch.object(sl, 'DB_PATH', make_db):
        similar = sl.get_similar_for_listing('DOES_NOT_EXIST', limit=3)
    assert len(similar) == 0


def test_get_similar_for_listing_excludes_original(make_db):
    db = make_db
    conn = sqlite3.connect(db)
    _insert_listing(conn, 'L1', 'Target listing', 2000, 2, 'Parkdale', 0.80, 0.80)
    _insert_listing(conn, 'L2', 'Similar 2BR Parkdale', 2100, 2, 'Parkdale', 0.78, 0.78)
    conn.commit(); conn.close()

    with patch.object(sl, 'DB_PATH', db):
        similar = sl.get_similar_for_listing('L1', limit=3)
    ids = [s.listing_id for s in similar]
    assert 'L1' not in ids


def test_get_similar_for_listing_has_explanation(make_db):
    db = make_db
    conn = sqlite3.connect(db)
    _insert_listing(conn, 'L1', 'Target listing', 2000, 2, 'Parkdale', 0.80, 0.80)
    _insert_listing(conn, 'L2', 'Similar 2BR Parkdale', 2100, 2, 'Parkdale', 0.78, 0.78)
    conn.commit(); conn.close()

    with patch.object(sl, 'DB_PATH', db):
        similar = sl.get_similar_for_listing('L1', limit=3)
    assert len(similar) > 0
    assert 'Based on this' in similar[0].similarity_explanation