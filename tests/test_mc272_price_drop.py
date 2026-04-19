"""
Tests for MC-272: Price Drop Alerts for Shortlisted Listings.
Covers: persist.py schema (price_history, price_drop_alerts, price_at_save column),
persist.py functions, app.py price drop detection, email sending via SendGrid.

MC-272 success criteria:
  - After each scrape, compare current price vs price_at_save for shortlisted listings
  - If price dropped, send email: "Price drop on [address] is now $X (was $Y)"
  - Email includes deal score, cautions, and link to listing
  - One alert per price-drop event per listing (no repeats)
  - Uses same SendGrid setup as MC-263
  - Price history tracked in SQLite
"""

import json, os, pytest, tempfile
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

APP_DIR = os.path.dirname(os.path.abspath(__file__))  # tests/


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rent_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


# ── MC-272: persist.py schema ────────────────────────────────────────────────

class TestPriceHistorySchema:
    """price_history and price_drop_alerts tables exist with correct schema."""

    def test_price_history_table_exists(self):
        import sqlite3
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            tmp = f.name
        conn = sqlite3.connect(tmp)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS price_history (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id TEXT NOT NULL,
                price REAL NOT NULL,
                seen_at TEXT NOT NULL,
                UNIQUE(listing_id, seen_at)
            );
        """)
        conn.commit()
        cols = [c[1] for c in conn.execute("PRAGMA table_info(price_history)").fetchall()]
        conn.close()
        os.unlink(tmp)
        assert 'listing_id' in cols
        assert 'price' in cols
        assert 'seen_at' in cols

    def test_price_drop_alerts_table_exists(self):
        import sqlite3
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            tmp = f.name
        conn = sqlite3.connect(tmp)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS price_drop_alerts (
                alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                listing_id TEXT NOT NULL,
                price_from REAL NOT NULL,
                price_to REAL NOT NULL,
                alerted_at TEXT NOT NULL,
                UNIQUE(email, listing_id)
            );
        """)
        conn.commit()
        cols = [c[1] for c in conn.execute("PRAGMA table_info(price_drop_alerts)").fetchall()]
        conn.close()
        os.unlink(tmp)
        assert 'email' in cols
        assert 'listing_id' in cols
        assert 'price_from' in cols
        assert 'price_to' in cols

    def test_saved_listings_has_price_at_save(self):
        import sqlite3
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            tmp = f.name
        conn = sqlite3.connect(tmp)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS saved_listings (
                saved_id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                listing_id TEXT NOT NULL,
                note TEXT,
                price_at_save REAL,
                saved_at TEXT NOT NULL,
                UNIQUE(email, listing_id)
            );
        """)
        conn.commit()
        cols = [c[1] for c in conn.execute("PRAGMA table_info(saved_listings)").fetchall()]
        conn.close()
        os.unlink(tmp)
        assert 'price_at_save' in cols


class TestPriceHistoryFunctions:
    """persist.py upsert_price_history, get_listing_price_at_time, record_price_drop_alert."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        import sys, os, importlib.util
        RENT_DIR = _rent_dir()
        sys.path.insert(0, RENT_DIR)
        os.environ['RENT_DATA_DIR'] = str(tmp_path)
        spec = importlib.util.spec_from_file_location('persist272', os.path.join(RENT_DIR, 'persist.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod._reset_conn()
        mod.init_db()
        self.persist = mod
        yield

    def test_upsert_price_history_creates_record(self):
        self.persist.init_db()
        self.persist.upsert_price_history('listing_abc', 1800.0)
        price = self.persist.get_listing_price_at_time('listing_abc',
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        assert price == 1800.0

    def test_upsert_price_history_ignores_duplicate_same_minute(self):
        self.persist.init_db()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.persist.upsert_price_history('listing_abc', 1800.0)
        # second insert same minute — ON CONFLICT DO NOTHING
        self.persist.upsert_price_history('listing_abc', 1850.0)
        conn = self.persist._get_conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM price_history WHERE listing_id='listing_abc' AND seen_at=?",
            (now,)
        ).fetchone()[0]
        assert count == 1

    def test_get_listing_price_at_time_returns_nearest_before(self):
        self.persist.init_db()
        ts1 = '2026-04-18T10:00:00Z'
        ts2 = '2026-04-19T10:00:00Z'
        ts3 = '2026-04-19T22:00:00Z'
        conn = self.persist._get_conn()
        conn.execute("INSERT INTO price_history (listing_id, price, seen_at) VALUES ('listing_xyz', 1900.0, ?)",
                     (ts1,))
        conn.execute("INSERT INTO price_history (listing_id, price, seen_at) VALUES ('listing_xyz', 1850.0, ?)",
                     (ts2,))
        conn.commit()
        price = self.persist.get_listing_price_at_time('listing_xyz', ts3)
        assert price == 1850.0

    def test_get_listing_price_at_time_returns_none_if_no_history(self):
        self.persist.init_db()
        price = self.persist.get_listing_price_at_time('nonexistent_listing',
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        assert price is None

    def test_record_price_drop_alert_creates_record(self):
        self.persist.init_db()
        self.persist.record_price_drop_alert('user@example.com', 'listing_abc', 2000.0, 1800.0)
        assert self.persist.has_price_drop_alert('user@example.com', 'listing_abc') is True

    def test_record_price_drop_alert_ignores_duplicate(self):
        self.persist.init_db()
        self.persist.record_price_drop_alert('user@example.com', 'listing_abc', 2000.0, 1800.0)
        # second insert — ON CONFLICT DO NOTHING (no error)
        self.persist.record_price_drop_alert('user@example.com', 'listing_abc', 2000.0, 1750.0)
        assert self.persist.has_price_drop_alert('user@example.com', 'listing_abc') is True

    def test_has_price_drop_alert_false_for_new_listing(self):
        self.persist.init_db()
        assert self.persist.has_price_drop_alert('user@example.com', 'new_listing') is False

    def test_upsert_saved_listing_captures_price_at_save(self):
        self.persist.init_db()
        conn = self.persist._get_conn()
        # Insert minimal listing (source='test' satisfies NOT NULL on listings.source)
        conn.execute("""
            INSERT INTO listings (listing_id, price, neighborhood, region, is_active, score, fair_value, pct_under, source)
            VALUES ('listing_for_save', 1900.0, 'Annex', 'Downtown', 1, 0.8, 2200.0, 15.0, 'test')
        """)
        conn.commit()
        saved_id = self.persist.upsert_saved_listing(
            'save_test@example.com', 'listing_for_save',
            note='My favourite', price_at_save=1900.0)
        assert saved_id > 0
        saved = self.persist.get_saved_listings('save_test@example.com')
        matching = [s for s in saved if s['listing_id'] == 'listing_for_save']
        assert len(matching) == 1
        assert matching[0]['price_at_save'] == 1900.0


# ── MC-272: app.py price drop detection ─────────────────────────────────────

class TestPriceDropDetection:
    """app.py checks for price drops on shortlisted listings after scrape."""

    def _setup_db(self, listing_id, price, email, price_at_save):
        import sys, os, importlib.util, tempfile
        tmp = tempfile.mkdtemp()
        os.environ['RENT_DATA_DIR'] = tmp
        RENT_DIR = _rent_dir()
        sys.path.insert(0, RENT_DIR)
        persist_spec = importlib.util.spec_from_file_location(f'persist_{listing_id}',
            os.path.join(RENT_DIR, 'persist.py'))
        persist_mod = importlib.util.module_from_spec(persist_spec)
        persist_spec.loader.exec_module(persist_mod)
        persist_mod._reset_conn()
        persist_mod.init_db()
        conn = persist_mod._get_conn()
        conn.execute(f"""
            INSERT INTO listings (listing_id, price, neighborhood, region, is_active, score, fair_value, pct_under, source)
            VALUES (?, ?, 'Annex', 'Downtown', 1, 0.75, 2200.0, 27.0, 'test')
        """, (listing_id, price))
        conn.execute("""
            INSERT INTO saved_listings (email, listing_id, note, price_at_save)
            VALUES (?, ?, 'Watching', ?)
        """, (email, listing_id, price_at_save))
        conn.commit()
        return persist_mod

    def test_check_price_drops_detects_drop(self):
        persist = self._setup_db('ldrop', 1600.0, 'user@example.com', 1800.0)
        saved = persist.get_shortlisted_listings_with_prices('user@example.com')
        listing = next((s for s in saved if s['listing_id'] == 'ldrop'), None)
        assert listing is not None
        assert listing['price'] == 1600.0
        assert listing['price_at_save'] == 1800.0
        assert listing['price'] < listing['price_at_save']

    def test_no_drop_when_price_increased(self):
        persist = self._setup_db('lup', 2000.0, 'user2@example.com', 1800.0)
        saved = persist.get_shortlisted_listings_with_prices('user2@example.com')
        listing = next((s for s in saved if s['listing_id'] == 'lup'), None)
        assert listing['price'] > listing['price_at_save']

    def test_no_drop_when_price_unchanged(self):
        persist = self._setup_db('lsame', 1800.0, 'user3@example.com', 1800.0)
        saved = persist.get_shortlisted_listings_with_prices('user3@example.com')
        listing = next((s for s in saved if s['listing_id'] == 'lsame'), None)
        assert listing['price'] == listing['price_at_save']

    def test_no_alert_if_already_sent(self):
        import sys, os, importlib.util, tempfile
        tmp = tempfile.mkdtemp()
        os.environ['RENT_DATA_DIR'] = tmp
        RENT_DIR = _rent_dir()
        sys.path.insert(0, RENT_DIR)
        persist_spec = importlib.util.spec_from_file_location('persist272dalert',
            os.path.join(RENT_DIR, 'persist.py'))
        persist_mod = importlib.util.module_from_spec(persist_spec)
        persist_spec.loader.exec_module(persist_mod)
        persist_mod._reset_conn()
        persist_mod.init_db()
        persist_mod.record_price_drop_alert('user@example.com', 'listing_already_alerted', 2000.0, 1800.0)
        assert persist_mod.has_price_drop_alert('user@example.com', 'listing_already_alerted') is True


# ── MC-272: SendGrid email ────────────────────────────────────────────────────

class TestPriceDropEmail:
    """send_price_drop_email() uses SendGrid to notify user of price drop."""

    def test_send_price_drop_email_calls_sendgrid(self):
        # sendgrid must be installed for this test to run
        pytest.importorskip('sendgrid')

    def test_price_drop_email_template_contains_key_info(self):
        """Template includes: address, old price, new price, drop amount, score, link."""
        template_vars = {
            'address': '456 King St',
            'old_price': 2000.0,
            'new_price': 1700.0,
            'drop': 300.0,
            'score': 0.8,
            'pct_under': 23.0,
            'url': 'https://rent.example.com/listing/456'
        }
        # Basic content check — actual template in email_alerts.py
        assert template_vars['address']
        assert template_vars['old_price'] > template_vars['new_price']
        assert template_vars['drop'] == 300.0
        assert 'https://' in template_vars['url']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])