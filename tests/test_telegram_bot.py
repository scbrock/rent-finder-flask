"""
Tests for MC-283: Telegram bot for real-time deal alerts.
Covers: telegram_bot.py functions, persist.py Telegram subscription functions.
"""

import os, sys, sqlite3, tempfile
from datetime import datetime, timezone

APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, APP_DIR)

import persist as _persist


# ── Per-test DB setup/teardown ─────────────────────────────────────────────────

_test_db_files = []  # track for cleanup


def _fresh_test_db() -> str:
    """Create a fresh temp DB file and patch persist to use it. Returns path."""
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    path = tmp.name
    tmp.close()
    _test_db_files.append(path)

    # Patch persist module
    _persist.DB_PATH = path
    _persist._cached_conn[0] = None

    # Create schema
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
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

        CREATE TABLE IF NOT EXISTS listings (
            listing_id   TEXT    PRIMARY KEY,
            source      TEXT    NOT NULL,
            title       TEXT,
            price       REAL    NOT NULL,
            price_str   TEXT,
            beds        REAL,
            baths       REAL,
            sqft        REAL,
            neighborhood TEXT,
            region      TEXT,
            location    TEXT,
            url         TEXT,
            image_url   TEXT,
            days_ago    INTEGER,
            is_stale    INTEGER NOT NULL DEFAULT 0,
            first_seen  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            last_seen   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            is_active   INTEGER NOT NULL DEFAULT 1,
            scrape_count INTEGER NOT NULL DEFAULT 1,
            is_new      INTEGER NOT NULL DEFAULT 0,
            fair_value  REAL,
            score       REAL,
            pct_under   REAL
        );
    """)
    conn.commit()
    conn.close()
    return path


def _seed_deals(path: str) -> list:
    deals = [
        {'listing_id': 'T1', 'title': 'King West 1BR', 'price': 1800.0, 'beds': 1,
         'baths': 1, 'sqft': 550, 'neighborhood': 'King West', 'region': 'Downtown',
         'url': 'http://x.com/1', 'fair_value': 2200.0, 'score': 0.18, 'pct_under': 18.2,
         'days_ago': 1},
        {'listing_id': 'T2', 'title': 'Queen West 2BR', 'price': 2400.0, 'beds': 2,
         'baths': 1, 'sqft': 750, 'neighborhood': 'Queen West', 'region': 'Downtown',
         'url': 'http://x.com/2', 'fair_value': 2800.0, 'score': 0.14, 'pct_under': 14.3,
         'days_ago': 3},
        {'listing_id': 'T3', 'title': 'Liberty Village Studio', 'price': 1500.0, 'beds': 0,
         'baths': 1, 'sqft': 400, 'neighborhood': 'Liberty Village', 'region': 'Downtown',
         'url': 'http://x.com/3', 'fair_value': 1900.0, 'score': 0.21, 'pct_under': 21.1,
         'days_ago': 0},
    ]
    conn = sqlite3.connect(path)
    for d in deals:
        conn.execute("""
            INSERT INTO listings (listing_id, source, title, price, beds, baths, sqft,
                neighborhood, region, url, fair_value, score, pct_under, days_ago, is_active)
            VALUES (?, 'kijiji', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (d['listing_id'], d['title'], d['price'], d['beds'], d['baths'],
              d['sqft'], d['neighborhood'], d['region'], d['url'],
              d['fair_value'], d['score'], d['pct_under'], d['days_ago']))
    conn.commit()
    conn.close()
    return deals


def _cleanup_test_dbs():
    for path in _test_db_files:
        try:
            os.remove(path)
        except OSError:
            pass
    _test_db_files.clear()


# ── Persist Tests ─────────────────────────────────────────────────────────────

class TestTelegramPersist:

    def setup_method(self):
        _cleanup_test_dbs()
        _fresh_test_db()

    def teardown_method(self):
        _persist._cached_conn[0] = None
        _cleanup_test_dbs()

    def test_upsert_and_get(self):
        _persist.upsert_telegram_subscription('123456', 'alice@example.com',
                                              max_price=2500, min_beds=1,
                                              neighbourhood='King West')
        sub = _persist.get_telegram_subscription('123456')
        assert sub is not None
        assert sub['email'] == 'alice@example.com'
        assert sub['max_price'] == 2500
        assert sub['min_beds'] == 1
        assert sub['neighbourhood'] == 'King West'
        assert sub['active'] == 1

    def test_upsert_updates_existing(self):
        _persist.upsert_telegram_subscription('123456', 'alice@example.com', max_price=2000)
        _persist.upsert_telegram_subscription('123456', 'alice-new@example.com', max_price=3000)
        sub = _persist.get_telegram_subscription('123456')
        assert sub['email'] == 'alice-new@example.com'
        assert sub['max_price'] == 3000

    def test_deactivate(self):
        _persist.upsert_telegram_subscription('999', 'bob@example.com')
        _persist.deactivate_telegram_subscription('999')
        sub = _persist.get_telegram_subscription('999')
        assert sub['active'] == 0

    def test_get_active_subscriptions(self):
        _persist.upsert_telegram_subscription('C1', 'a@test.com', max_price=2000)
        _persist.upsert_telegram_subscription('C2', 'b@test.com', max_price=2500)
        _persist.upsert_telegram_subscription('C3', 'c@test.com', max_price=3000)
        _persist.deactivate_telegram_subscription('C2')
        subs = _persist.get_active_telegram_subscriptions()
        assert len(subs) == 2
        chat_ids = {s['telegram_chat_id'] for s in subs}
        assert chat_ids == {'C1', 'C3'}

    def test_update_last_alerted(self):
        _persist.upsert_telegram_subscription('555', 'x@test.com')
        _persist.update_telegram_last_alerted('555')
        sub = _persist.get_telegram_subscription('555')
        assert sub['last_alerted'] is not None


# ── Deal Formatting Tests ─────────────────────────────────────────────────────

class TestDealFormatting:

    def setup_method(self):
        _cleanup_test_dbs()
        path = _fresh_test_db()
        _seed_deals(path)

    def teardown_method(self):
        _persist._cached_conn[0] = None
        _cleanup_test_dbs()

    def test_build_deals_message_no_deals(self):
        from telegram_bot import build_deals_message
        msg = build_deals_message([])
        assert 'No deals' in msg or 'no deals' in msg.lower()

    def test_build_deals_message_with_deals(self):
        conn = sqlite3.connect(_persist.DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM listings WHERE is_active=1 AND score>0 ORDER BY score DESC LIMIT 5"
        ).fetchall()
        conn.close()
        deals_list = [dict(r) for r in rows]

        from telegram_bot import build_deals_message
        msg = build_deals_message(deals_list)
        assert 'Top Toronto Deals' in msg
        assert 'King West' in msg
        assert '$1,800' in msg or '1,800' in msg

    def test_build_alert_message(self):
        conn = sqlite3.connect(_persist.DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM listings WHERE is_active=1 LIMIT 2"
        ).fetchall()
        conn.close()
        deals_list = [dict(r) for r in rows]

        from telegram_bot import build_alert_message
        msg = build_alert_message(deals_list)
        assert 'New Deals Found' in msg or 'deals' in msg.lower()
        assert 'King West' in msg

    def test_format_deal_all_fields(self):
        from telegram_bot import _format_deal
        deal = {
            'listing_id': 'X1', 'title': 'Downtown 2BR 2Ba',
            'price': 2700, 'beds': 2, 'baths': 2, 'sqft': 850,
            'neighborhood': 'Downtown Core', 'region': 'Downtown',
            'url': 'http://x.com/x', 'fair_value': 3000,
            'score': 0.10, 'pct_under': 10.0, 'days_ago': 2,
        }
        formatted = _format_deal(deal, 1)
        assert 'Downtown Core' in formatted
        assert '2BR' in formatted
        assert '2700' in formatted or '2,700' in formatted


# ── Deal Fetching Tests ───────────────────────────────────────────────────────

class TestDealFetching:

    def setup_method(self):
        _cleanup_test_dbs()
        path = _fresh_test_db()
        _seed_deals(path)

    def teardown_method(self):
        _persist._cached_conn[0] = None
        _cleanup_test_dbs()

    def test_fetch_top_deals_order(self):
        from telegram_bot import _fetch_top_deals
        deals = _fetch_top_deals(limit=5)
        assert len(deals) == 3
        assert deals[0]['listing_id'] == 'T3'   # score 0.21
        assert deals[1]['listing_id'] == 'T1'   # score 0.18
        assert deals[2]['listing_id'] == 'T2'   # score 0.14

    def test_fetch_max_price_filter(self):
        from telegram_bot import _fetch_top_deals
        deals = _fetch_top_deals(max_price=2000)
        assert all(d['price'] <= 2000 for d in deals)
        assert len(deals) == 2  # T1 (1800) and T3 (1500)

    def test_fetch_min_beds_filter(self):
        from telegram_bot import _fetch_top_deals
        deals = _fetch_top_deals(min_beds=2)
        assert all((d.get('beds') or 0) >= 2 for d in deals)
        assert len(deals) == 1  # T2 only

    def test_fetch_excludes_inactive(self):
        conn = sqlite3.connect(_persist.DB_PATH)
        conn.execute("UPDATE listings SET is_active=0 WHERE listing_id='T1'")
        conn.commit()
        conn.close()
        from telegram_bot import _fetch_top_deals
        deals = _fetch_top_deals()
        ids = [d['listing_id'] for d in deals]
        assert 'T1' not in ids

    def test_fetch_excludes_null_score(self):
        conn = sqlite3.connect(_persist.DB_PATH)
        conn.execute("""
            INSERT INTO listings (listing_id, source, title, price, beds,
                neighborhood, region, url, fair_value, score, pct_under, days_ago, is_active)
            VALUES ('T4', 'kijiji', 'Bad Deal', 5000, 1,
                'X', 'Y', 'http://x.com', 2500, NULL, NULL, 1, 1)
        """)
        conn.commit()
        conn.close()
        from telegram_bot import _fetch_top_deals
        deals = _fetch_top_deals()
        ids = [d['listing_id'] for d in deals]
        assert 'T4' not in ids


# ── Alert Matching Tests ───────────────────────────────────────────────────────

class TestAlertMatching:

    def setup_method(self):
        _cleanup_test_dbs()
        path = _fresh_test_db()
        _seed_deals(path)

    def teardown_method(self):
        _persist._cached_conn[0] = None
        _cleanup_test_dbs()

    def test_match_with_max_price(self):
        from telegram_bot import get_matching_deals_for_telegram
        sub = {'telegram_chat_id': 'C1', 'email': 'a@test.com',
               'max_price': 2000.0, 'min_beds': None, 'neighbourhood': None}
        matches = get_matching_deals_for_telegram(sub, limit=5)
        assert all(m['price'] <= 2000 for m in matches)
        assert len(matches) == 2

    def test_match_with_min_beds(self):
        from telegram_bot import get_matching_deals_for_telegram
        sub = {'telegram_chat_id': 'C1', 'email': 'a@test.com',
               'max_price': None, 'min_beds': 1.5, 'neighbourhood': None}
        matches = get_matching_deals_for_telegram(sub, limit=5)
        assert all((m.get('beds') or 0) >= 1.5 for m in matches)
        assert len(matches) == 1  # T2 (2BR) only — T1 (1BR) < 1.5

    def test_match_no_results(self):
        from telegram_bot import get_matching_deals_for_telegram
        sub = {'telegram_chat_id': 'C1', 'email': 'a@test.com',
               'max_price': 500.0, 'min_beds': None, 'neighbourhood': None}
        matches = get_matching_deals_for_telegram(sub, limit=5)
        assert len(matches) == 0
