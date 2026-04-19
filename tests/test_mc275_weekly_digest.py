"""
Tests for weekly_digest.py — MC-275.
Uses pytest's tmp_path fixture for clean per-test isolation.
"""
import pytest, os, sqlite3, sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENT_FINDER = PROJECT_ROOT
if RENT_FINDER not in sys.path:
    sys.path.insert(0, RENT_FINDER)

import weekly_digest as wd


def _create_schema(conn):
    """Create all required tables in a fresh DB."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE user_profiles (
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            preferred_beds TEXT DEFAULT '',
            max_price REAL DEFAULT 0,
            neighbourhoods TEXT DEFAULT '',
            status TEXT DEFAULT 'Open to moving',
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
    """)
    cur.execute("""
        CREATE TABLE listings (
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
            pct_under REAL
        )
    """)
    cur.execute("""
        CREATE TABLE price_history (
            ph_id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id TEXT NOT NULL,
            price REAL NOT NULL,
            beds REAL,
            ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
    """)
    conn.commit()


def _insert_listing(conn, lid, title, price, beds, neighborhood, url, score, days_ago, is_active, first_seen, last_seen, pct_under):
    conn.execute("""
        INSERT INTO listings (listing_id, source, title, price, beds, neighborhood, url, score,
                              days_ago, is_active, first_seen, last_seen, pct_under)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (lid, 'test', title, price, beds, neighborhood, url, score, days_ago, is_active, first_seen, last_seen, pct_under))


@pytest.fixture
def empty_db(tmp_path):
    """Fresh DB with schema, no data. Each test gets its own tmp_path."""
    db_path = str(tmp_path / 'listings.db')
    conn = sqlite3.connect(db_path)
    _create_schema(conn)
    conn.close()
    return db_path


@pytest.fixture
def seeded_db(tmp_path):
    """DB with users, listings, price history."""
    db_path = str(tmp_path / 'listings.db')
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).isoformat().replace('+00:00', 'Z')
    two_wks_ago = (now - timedelta(days=14)).isoformat().replace('+00:00', 'Z')
    today = now.isoformat().replace('+00:00', 'Z')

    conn = sqlite3.connect(db_path)
    _create_schema(conn)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO user_profiles (email, preferred_beds, max_price, neighbourhoods, status)
        VALUES
            ('alice@test.com', '2,3', 3000, '["Parkdale","Liberty Village"]', 'Open to moving'),
            ('bob@test.com', '1', 2000, '["Rosedale"]', 'Actively looking'),
            ('charlie@test.com', '', 0, '', 'Just browsing')
    """)
    listings = [
        ('L1', 'Bright 2BR near Parkdale', 2200, 2, 'Parkdale', 'http://x/L1', 0.85, 2, 1, today, today, 15.3),
        ('L2', 'Liberty Village 3BR with parking', 2600, 3, 'Liberty Village', 'http://x/L2', 0.78, 1, 1, today, today, 12.1),
        ('L3', 'Cozy 1BR Rosedale basement', 1800, 1, 'Rosedale', 'http://x/L3', 0.70, 3, 1, today, today, 18.5),
        ('L4', 'Luxury condo', 4500, 2, 'Parkdale', 'http://x/L4', 0.60, 1, 1, today, today, 0.0),
        ('L5', 'New 2BR listing this week', 2400, 2, 'Parkdale', 'http://x/L5', 0.82, 0, 1, today, today, 14.0),
        ('L6', 'Old stale listing', 2000, 2, 'Parkdale', 'http://x/L6', 0.50, 30, 0, today, today, 5.0),
    ]
    for lst in listings:
        _insert_listing(conn, *lst)

    price_rows = [
        ('L1', 2400, 2, week_ago), ('L1', 2500, 2, week_ago), ('L1', 2350, 2, week_ago),
        ('L3', 1900, 1, week_ago), ('L3', 1950, 1, week_ago),
        ('L1', 2550, 2, two_wks_ago), ('L1', 2600, 2, two_wks_ago),
        ('L3', 1850, 1, two_wks_ago), ('L3', 1880, 1, two_wks_ago),
    ]
    cur.executemany(
        "INSERT INTO price_history (listing_id, price, beds, ts) VALUES (?, ?, ?, ?)",
        price_rows
    )
    conn.commit()
    conn.close()
    return db_path


# ── get_eligible_users ──────────────────────────────────────────────────────

def test_get_eligible_users_filters_status(empty_db):
    conn = sqlite3.connect(empty_db)
    conn.execute("INSERT INTO user_profiles (email, status) VALUES ('a@t.com', 'Open to moving')")
    conn.execute("INSERT INTO user_profiles (email, status) VALUES ('b@t.com', 'Just browsing')")
    conn.commit(); conn.close()

    with patch.object(wd, 'DB_PATH', empty_db):
        users = wd.get_eligible_users()
    assert len(users) == 1
    assert users[0].email == 'a@t.com'


def test_get_eligible_users_returns_correct_fields(empty_db):
    conn = sqlite3.connect(empty_db)
    conn.execute("INSERT INTO user_profiles (email, preferred_beds, max_price, status) VALUES (?, ?, ?, ?)",
        ('alice@test.com', '2,3', 3000, 'Open to moving'))
    conn.commit(); conn.close()

    with patch.object(wd, 'DB_PATH', empty_db):
        users = wd.get_eligible_users()
    assert users[0].preferred_beds == '2,3'
    assert users[0].max_price == 3000


# ── get_top_deals ────────────────────────────────────────────────────────────

def test_get_top_deals_respects_max_price(empty_db):
    now = datetime.now(timezone.utc)
    today = now.isoformat().replace('+00:00', 'Z')
    conn = sqlite3.connect(empty_db)
    _insert_listing(conn, 'L1', 'Cheap 2BR', 1500, 2, 'Parkdale', 'http://x', 0.9, 1, 1, today, today, 10.0)
    _insert_listing(conn, 'L2', 'Expensive 2BR', 5000, 2, 'Parkdale', 'http://x', 0.8, 1, 1, today, today, 0.0)
    conn.commit(); conn.close()

    profile = wd.DigestUser(1, 'alice@test.com', '2,3', 2500, '[]', 'Open to moving')
    with patch.object(wd, 'DB_PATH', empty_db):
        deals = wd.get_top_deals(profile, limit=10)
    assert len(deals) == 1
    assert deals[0].price == 1500


def test_get_top_deals_respects_bed_filter(empty_db):
    now = datetime.now(timezone.utc)
    today = now.isoformat().replace('+00:00', 'Z')
    conn = sqlite3.connect(empty_db)
    for lid, beds in [('L1', 1), ('L2', 2), ('L3', 3)]:
        _insert_listing(conn, lid, f'L{lid}', 2000, beds, 'Parkdale', 'http://x', 0.8, 1, 1, today, today, 10.0)
    conn.commit(); conn.close()

    profile = wd.DigestUser(1, 'alice@test.com', '1', 5000, '[]', 'Open to moving')
    with patch.object(wd, 'DB_PATH', empty_db):
        deals = wd.get_top_deals(profile, limit=10)
    assert all(d.beds == 1 for d in deals)


def test_get_top_deals_excludes_inactive(empty_db):
    now = datetime.now(timezone.utc)
    today = now.isoformat().replace('+00:00', 'Z')
    conn = sqlite3.connect(empty_db)
    _insert_listing(conn, 'L1', 'Active', 2000, 2, 'Parkdale', 'http://x', 0.8, 1, 1, today, today, 10.0)
    _insert_listing(conn, 'L2', 'Inactive', 2000, 2, 'Parkdale', 'http://x', 0.8, 30, 0, today, today, 10.0)
    conn.commit(); conn.close()

    profile = wd.DigestUser(1, 'alice@test.com', '', 0, '', 'Open to moving')
    with patch.object(wd, 'DB_PATH', empty_db):
        deals = wd.get_top_deals(profile, limit=10)
    assert 'L2' not in [d.listing_id for d in deals]


def test_get_top_deals_respects_limit(empty_db):
    now = datetime.now(timezone.utc)
    today = now.isoformat().replace('+00:00', 'Z')
    conn = sqlite3.connect(empty_db)
    for i in range(8):
        _insert_listing(conn, f'L{i}', f'L{i}', 2000, 2, 'Parkdale', 'http://x', 0.8, 1, 1, today, today, 10.0)
    conn.commit(); conn.close()

    profile = wd.DigestUser(1, 'alice@test.com', '', 0, '', 'Open to moving')
    with patch.object(wd, 'DB_PATH', empty_db):
        deals = wd.get_top_deals(profile, limit=3)
    assert len(deals) == 3


# ── get_new_listings_since ──────────────────────────────────────────────────

def test_get_new_listings_since_returns_new_listings(empty_db):
    now = datetime.now(timezone.utc)
    recent = now.isoformat().replace('+00:00', 'Z')
    old = (now - timedelta(days=10)).isoformat().replace('+00:00', 'Z')
    conn = sqlite3.connect(empty_db)
    _insert_listing(conn, 'L1', 'New listing', 2000, 2, 'Parkdale', 'http://x', 0.8, 0, 1, recent, recent, 10.0)
    _insert_listing(conn, 'L2', 'Old listing', 2000, 2, 'Parkdale', 'http://x', 0.8, 10, 1, old, old, 10.0)
    conn.commit(); conn.close()

    with patch.object(wd, 'DB_PATH', empty_db):
        new = wd.get_new_listings_since(now - timedelta(days=3))
    ids = [n.listing_id for n in new]
    assert 'L1' in ids
    assert 'L2' not in ids


# ── get_market_summary ────────────────────────────────────────────────────────

def test_get_market_summary_computes_avg_by_beds(empty_db):
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).isoformat().replace('+00:00', 'Z')
    two_wks_ago = (now - timedelta(days=14)).isoformat().replace('+00:00', 'Z')
    today = now.isoformat().replace('+00:00', 'Z')
    conn = sqlite3.connect(empty_db)
    _insert_listing(conn, 'L1', 'L1', 2400, 2, 'Parkdale', 'http://x', 0.8, 1, 1, today, today, 10.0)
    conn.execute("INSERT INTO price_history (ph_id, listing_id, price, beds, ts) VALUES (NULL, ?, ?, ?, ?)", ('L1', 2400, 2, week_ago))
    conn.execute("INSERT INTO price_history (ph_id, listing_id, price, beds, ts) VALUES (NULL, ?, ?, ?, ?)", ('L1', 2550, 2, two_wks_ago))
    conn.commit(); conn.close()

    with patch.object(wd, 'DB_PATH', empty_db):
        summary = wd.get_market_summary()
    assert 2 in summary
    assert summary[2]['current_avg'] < summary[2]['prev_avg']  # price dropped


# ── build_digest_html ─────────────────────────────────────────────────────────

def test_build_digest_html_contains_deals():
    deals = [wd.DigestDeal('L1', 'Test listing', 2200, 2, 'Parkdale', 'http://x', 0.85, 2)]
    summary = {2: {'current_avg': 2400, 'prev_avg': 2500, 'count': 10}}
    new_listings = [wd.DigestDeal('L5', 'New listing', 2400, 2, 'Parkdale', 'http://x', 0.82, 0)]
    html = wd.build_digest_html('alice@test.com', deals, summary, new_listings, 'http://app.com')
    assert 'alice@test.com' in html
    assert 'Test listing' in html
    assert '$2,200' in html
    assert 'Unsubscribe' in html
    assert '/shortlist' in html
    assert '/profile' in html


def test_build_digest_html_empty_deals_hides_market_section():
    deals = []
    summary = {}
    new_listings = []
    html = wd.build_digest_html('alice@test.com', deals, summary, new_listings, 'http://app.com')
    assert 'Market Summary vs Last Week' not in html


def test_build_digest_html_empty_deals_hides_new_section():
    deals = []
    summary = {}
    new_listings = []
    html = wd.build_digest_html('alice@test.com', deals, summary, new_listings, 'http://app.com')
    assert 'New Listings This Week' not in html


def test_build_digest_subject():
    assert '5 deals' in wd.build_digest_subject(5)
    assert 'Toronto rent digest' in wd.build_digest_subject(5)


# ── send_weekly_digest ─────────────────────────────────────────────────────────

def test_send_weekly_digest_sends_to_eligible_users(seeded_db):
    with patch.object(wd, 'DB_PATH', seeded_db):
        sent = []
        def capture(to_email, html_body, subject):
            sent.append(to_email)
        with patch('weekly_digest.send_digest_email', side_effect=capture):
            stats = wd.send_weekly_digest(base_url='http://app.com')
    assert 'alice@test.com' in sent
    assert 'bob@test.com' in sent
    assert 'charlie@test.com' not in sent
    assert stats['emails_sent'] == 2
    assert stats['skipped_no_deals'] == 0
    assert stats['users_processed'] == 2


def test_send_weekly_digest_skips_users_with_no_matching_deals(empty_db):
    conn = sqlite3.connect(empty_db)
    conn.execute("INSERT INTO user_profiles (email, preferred_beds, max_price, status) VALUES (?, ?, ?, ?)",
        ('lowball@test.com', '10', 500, 'Open to moving'))
    conn.commit(); conn.close()

    with patch.object(wd, 'DB_PATH', empty_db):
        with patch('weekly_digest.send_digest_email') as mock_send:
            stats = wd.send_weekly_digest(base_url='http://app.com')
    assert stats['skipped_no_deals'] == 1
    assert stats['emails_sent'] == 0


def test_send_weekly_digest_records_run_ts(empty_db):
    now = datetime.now(timezone.utc)
    today = now.isoformat().replace('+00:00', 'Z')
    conn = sqlite3.connect(empty_db)
    conn.execute("INSERT INTO user_profiles (email, status) VALUES (?, ?)", ('a@t.com', 'Open to moving'))
    _insert_listing(conn, 'L1', 'Test', 2000, 2, 'Parkdale', 'http://x', 0.8, 1, 1, today, today, 10.0)
    conn.commit(); conn.close()

    with patch.object(wd, 'DB_PATH', empty_db):
        with patch('weekly_digest.send_digest_email'):
            wd.send_weekly_digest(base_url='http://app.com')
    assert os.path.exists(wd.LAST_DIGEST_FILE)


def test_send_weekly_digest_error_isolation(seeded_db):
    with patch.object(wd, 'DB_PATH', seeded_db):
        def fail_on_alice(to_email, html_body, subject):
            if to_email == 'alice@test.com':
                raise Exception("Simulated send failure for Alice")
        with patch('weekly_digest.send_digest_email', side_effect=fail_on_alice):
            stats = wd.send_weekly_digest(base_url='http://app.com')
    # Bob should still get his email despite Alice failing
    assert stats['emails_sent'] == 1
    assert len(stats['errors']) == 1


def test_send_weekly_digest_zero_eligible(empty_db):
    """No users with matching status → zero emails."""
    conn = sqlite3.connect(empty_db)
    conn.execute("INSERT INTO user_profiles (email, status) VALUES (?, ?)",
        ('browse@test.com', 'Just browsing'))
    conn.commit(); conn.close()

    with patch.object(wd, 'DB_PATH', empty_db):
        stats = wd.send_weekly_digest(base_url='http://app.com')
    assert stats['users_processed'] == 0
    assert stats['emails_sent'] == 0


def test_build_digest_html_multiple_deals():
    deals = [
        wd.DigestDeal('L1', 'Bright 2BR near Parkdale', 2200, 2, 'Parkdale', 'http://x/L1', 0.85, 2),
        wd.DigestDeal('L2', 'Liberty Village 3BR', 2600, 3, 'Liberty Village', 'http://x/L2', 0.78, 1),
        wd.DigestDeal('L3', 'Cozy 1BR Rosedale', 1800, 1, 'Rosedale', 'http://x/L3', 0.70, 3),
    ]
    summary = {
        2: {'current_avg': 2450, 'prev_avg': 2550, 'count': 8},
        1: {'current_avg': 1850, 'prev_avg': 1830, 'count': 5}
    }
    new_listings = [wd.DigestDeal('L5', 'New listing this week', 2400, 2, 'Parkdale', 'http://x/L5', 0.82, 0)]
    html = wd.build_digest_html('alice@test.com', deals, summary, new_listings, 'http://app.com')
    assert 'Bright 2BR' in html
    assert 'Liberty Village' in html
    assert '$2,200' in html
    assert '$1,800' in html
    assert 'Market Summary vs Last Week' in html
    assert 'New Listings This Week' in html
    assert '/shortlist' in html
    assert '/profile' in html