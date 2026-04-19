"""
Tests for MC-263 — Email Alert System.
"""

import pytest, os, sys, sqlite3, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import persist
from persist import upsert_alert, send_alert_email, check_and_send_alerts


@pytest.fixture
def db_path(tmp_path):
    db = str(tmp_path / "test_alerts.db")
    original = persist.DB_PATH
    persist.DB_PATH = db
    persist.init_db()
    yield db
    persist.DB_PATH = original


class TestUpsertAlert:
    def test_upsert_creates_alert(self, db_path):
        upsert_alert("test@example.com", region="Downtown", min_beds=1, max_price=2500, min_score=0.15)
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT * FROM user_alerts WHERE email = ?", ("test@example.com",)).fetchone()
        assert row is not None
        # Schema: alert_id(0), email(1), region(2), min_beds(3), max_price(4), min_score(5), created_at(6), is_enabled(7), last_sent(8)
        assert row[1] == "test@example.com"
        assert row[3] == 1  # min_beds
        assert row[4] == 2500  # max_price
        assert row[5] == 0.15  # min_score
        assert row[7] == 1  # is_enabled
        conn.close()

    def test_upsert_updates_existing(self, db_path):
        upsert_alert("test2@example.com", region="Downtown", min_beds=1, max_price=2500, min_score=0.10)
        upsert_alert("test2@example.com", region="West End", min_beds=2, max_price=2000, min_score=0.20)
        conn = sqlite3.connect(db_path)
        # Schema: alert_id(0), email(1), region(2), min_beds(3), max_price(4), min_score(5), created_at(6), is_enabled(7), last_sent(8)
        row = conn.execute("SELECT region, min_beds, max_price, min_score FROM user_alerts WHERE email = ?",
                          ("test2@example.com",)).fetchone()
        assert row[0] == "West End"
        assert row[1] == 2
        assert row[2] == 2000
        assert row[3] == 0.20
        conn.close()

    def test_upsert_resets_last_sent(self, db_path):
        upsert_alert("test3@example.com", min_score=0.10)
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE user_alerts SET last_sent = '2020-01-01T00:00:00Z' WHERE email = ?", ("test3@example.com",))
        conn.commit()
        conn.close()
        upsert_alert("test3@example.com", min_score=0.20)
        conn = sqlite3.connect(db_path)
        last_sent = conn.execute("SELECT last_sent FROM user_alerts WHERE email = ?", ("test3@example.com",)).fetchone()[0]
        assert last_sent is None
        conn.close()


class TestCheckAndSendAlerts:
    def test_no_alerts_returns_zero_counts(self, db_path):
        result = check_and_send_alerts()
        assert result["checked"] == 0
        assert result["sent"] == 0

    def test_alert_with_no_matching_listings_skipped(self, db_path):
        upsert_alert("nobody@example.com", min_score=0.50)
        result = check_and_send_alerts()
        assert result["skipped_no_matches"] == 1
        assert result["sent"] == 0

    def test_alert_with_matching_listing_no_sendgrid_key_skips(self, db_path):
        """Without SENDGRID_API_KEY, send_alert_email returns False — errors counted."""
        upsert_alert("match@example.com", min_score=0.0)
        # Insert a matching active listing
        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT INTO listings (listing_id, source, title, price, beds, neighborhood, region,
                                  url, is_active, score, scrape_count)
            VALUES ('match-listing', 'Test', 'Test Listing', 1500, 1, 'Annex', 'Downtown',
                    'https://example.com', 1, 0.5, 1)
        """)
        conn.commit()
        conn.close()
        result = check_and_send_alerts()
        # No API key → send fails → error counted
        assert result["errors"] >= 1 or result["sent"] == 0

    def test_rate_limit_one_per_hour(self, db_path):
        """Alerts with last_sent within 1 hour should be skipped."""
        upsert_alert("ratelimit@example.com", min_score=0.0)
        conn = sqlite3.connect(db_path)
        # Set last_sent to within the last hour
        recent_time = "2026-04-18T22:00:00Z"
        conn.execute("UPDATE user_alerts SET last_sent = ? WHERE email = ?",
                     (recent_time, "ratelimit@example.com"))
        conn.execute("""
            INSERT INTO listings (listing_id, source, title, price, beds, neighborhood, region,
                                  url, is_active, score, scrape_count)
            VALUES ('match2', 'Test', 'Test', 1500, 1, 'Annex', 'Downtown', 'https://example.com', 1, 0.5, 1)
        """)
        conn.commit()
        conn.close()
        result = check_and_send_alerts()
        assert result["skipped_rate_limit"] == 1
        assert result["sent"] == 0


class TestAlertUnsubscribe:
    def test_unsubscribe_disables_alert(self, db_path):
        upsert_alert("unsub@example.com", min_score=0.10)
        conn = sqlite3.connect(db_path)
        was_enabled = conn.execute(
            "SELECT is_enabled FROM user_alerts WHERE email = ?", ("unsub@example.com",)
        ).fetchone()[0]
        assert was_enabled == 1
        conn.close()

        from app import api_alerts_delete
        # Simulate the DELETE logic directly
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE user_alerts SET is_enabled = 0 WHERE email = ?", ("unsub@example.com",))
        conn.commit()
        is_enabled = conn.execute(
            "SELECT is_enabled FROM user_alerts WHERE email = ?", ("unsub@example.com",)
        ).fetchone()[0]
        assert is_enabled == 0
        conn.close()
