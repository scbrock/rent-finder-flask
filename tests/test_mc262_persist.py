"""
Tests for persist.py — MC-262 SQLite persistence layer.
"""

import pytest, os, sys, sqlite3, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import persist


@pytest.fixture
def db_path(tmp_path):
    """Use a temp DB for each test."""
    db = str(tmp_path / "test.db")
    # Patch DB_PATH for the module
    original = persist.DB_PATH
    persist.DB_PATH = db
    persist.init_db()
    yield db, persist._get_conn
    persist.DB_PATH = original


class TestSchema:
    def test_tables_exist(self, db_path):
        db, _ = db_path
        conn = sqlite3.connect(db)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        assert "listings" in tables
        assert "scrape_runs" in tables
        assert "user_alerts" in tables
        conn.close()

    def test_listings_columns(self, db_path):
        db, _ = db_path
        conn = sqlite3.connect(db)
        cur = conn.execute("PRAGMA table_info(listings)")
        cols = {r[1] for r in cur.fetchall()}
        required = {"listing_id", "source", "price", "beds", "baths",
                    "first_seen", "last_seen", "is_active", "scrape_count",
                    "fair_value", "score", "pct_under"}
        assert required.issubset(cols), f"Missing: {required - cols}"
        conn.close()

    def test_indexes_exist(self, db_path):
        db, _ = db_path
        conn = sqlite3.connect(db)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {r[0] for r in cur.fetchall() if r[0]}
        assert "idx_listings_active" in indexes
        conn.close()


class TestUpsert:
    def test_upsert_inserts_new_listing(self, db_path):
        db, _ = db_path
        rows = [{
            "listing_id": "test-001",
            "source": "Kijiji",
            "title": "Test Listing",
            "price": 2000,
            "price_str": "$2,000",
            "beds": 1,
            "baths": 1,
            "neighborhood": "Annex",
            "region": "Downtown",
            "location": "Annex, Toronto",
            "link": "https://example.com/listing/001",
            "days_ago": 5,
            "is_stale": False,
        }]
        import pandas as pd
        df = pd.DataFrame(rows)
        stats = persist.upsert_listings(rows, df)
        conn = sqlite3.connect(db)
        count = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE listing_id = ?", ("test-001",)
        ).fetchone()[0]
        assert count == 1
        is_active = conn.execute(
            "SELECT is_active FROM listings WHERE listing_id = ?", ("test-001",)
        ).fetchone()[0]
        assert is_active == 1
        conn.close()

    def test_upsert_updates_existing(self, db_path):
        db, _ = db_path
        rows1 = [{"listing_id": "test-002", "source": "Craigslist", "price": 1800,
                  "beds": 2, "baths": 1, "neighborhood": "West End",
                  "region": "West End", "link": "https://example.com/listing/002",
                  "days_ago": 5, "is_stale": False, "title": "First Title"}]
        import pandas as pd
        persist.upsert_listings(rows1, pd.DataFrame(rows1))

        conn = sqlite3.connect(db)
        first_price = conn.execute(
            "SELECT price FROM listings WHERE listing_id = ?", ("test-002",)
        ).fetchone()[0]
        assert first_price == 1800

        rows2 = [{"listing_id": "test-002", "source": "Craigslist", "price": 1700,
                  "beds": 2, "baths": 1, "neighborhood": "West End",
                  "region": "West End", "link": "https://example.com/listing/002",
                  "days_ago": 1, "is_stale": False, "title": "Updated Title"}]
        persist.upsert_listings(rows2, pd.DataFrame(rows2))

        updated_price = conn.execute(
            "SELECT price FROM listings WHERE listing_id = ?", ("test-002",)
        ).fetchone()[0]
        assert updated_price == 1700  # updated

        scrape_count = conn.execute(
            "SELECT scrape_count FROM listings WHERE listing_id = ?", ("test-002",)
        ).fetchone()[0]
        assert scrape_count == 2  # incremented
        conn.close()

    def test_inactive_if_not_seen(self, db_path):
        db, _ = db_path
        # Insert two listings
        import pandas as pd
        rows1 = [
            {"listing_id": "seen-001", "source": "Kijiji", "price": 1500,
             "beds": 1, "baths": 1, "neighborhood": "Annex", "region": "Downtown",
             "link": "https://example.com/1", "days_ago": 5, "is_stale": False, "title": "A"},
            {"listing_id": "not-seen-001", "source": "Kijiji", "price": 1600,
             "beds": 2, "baths": 1, "neighborhood": "West End", "region": "West End",
             "link": "https://example.com/2", "days_ago": 5, "is_stale": False, "title": "B"},
        ]
        persist.upsert_listings(rows1, pd.DataFrame(rows1))
        conn = sqlite3.connect(db)
        assert conn.execute("SELECT COUNT(*) FROM listings WHERE is_active=1").fetchone()[0] == 2
        conn.close()

        # Second run: only "seen-001"
        rows2 = [
            {"listing_id": "seen-001", "source": "Kijiji", "price": 1550,
             "beds": 1, "baths": 1, "neighborhood": "Annex", "region": "Downtown",
             "link": "https://example.com/1", "days_ago": 1, "is_stale": False, "title": "A Updated"},
        ]
        persist.upsert_listings(rows2, pd.DataFrame(rows2))
        conn = sqlite3.connect(db)
        assert conn.execute("SELECT COUNT(*) FROM listings WHERE is_active=1").fetchone()[0] == 1
        assert conn.execute("SELECT is_active FROM listings WHERE listing_id='not-seen-001'").fetchone()[0] == 0
        conn.close()


class TestAlerts:
    def test_upsert_alert(self, db_path):
        db, _ = db_path
        persist.upsert_alert("test@example.com", region="Downtown",
                             min_beds=1, max_price=2500, min_score=0.5)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT * FROM user_alerts WHERE email = ?", ("test@example.com",)
        ).fetchone()
        assert row is not None
        assert row[1] == "test@example.com"
        conn.close()

    def test_upsert_updates_existing_alert(self, db_path):
        db, _ = db_path
        persist.upsert_alert("alert@example.com", region="Downtown", max_price=2000)
        persist.upsert_alert("alert@example.com", region="West End", max_price=2500)
        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT * FROM user_alerts WHERE email = ?",
                            ("alert@example.com",)).fetchall()
        assert len(rows) == 1  # only one row (updated)
        conn.close()
