"""
Tests for MC-271: Saved Listings / Shortlist
Tests the saved_listings table and CRUD functions in persist.py.
"""

import pytest, os, sys, sqlite3, tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import persist as P

TEST_DB_DIR = tempfile.mkdtemp()
TEST_DB = os.path.join(TEST_DB_DIR, "test_mc271.db")

_temp_conn_ref = [None]

def _temp_conn():
    if _temp_conn_ref[0] is not None:
        try:
            _temp_conn_ref[0].execute("SELECT 1")
            return _temp_conn_ref[0]
        except Exception:
            pass
    os.makedirs(TEST_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(TEST_DB, isolation_level='DEFERRED')
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _temp_conn_ref[0] = conn
    return conn


@pytest.fixture(autouse=True)
def fresh_db():
    P._reset_conn()
    _temp_conn_ref[0] = None

    orig_get_conn = P._get_conn
    orig_db_path = P.DB_PATH
    orig_data_dir = P.DATA_DIR
    P._get_conn = _temp_conn
    P.DATA_DIR = TEST_DB_DIR
    P.DB_PATH = TEST_DB

    for f in [TEST_DB, TEST_DB + "-wal", TEST_DB + "-shm", TEST_DB + "-journal"]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except PermissionError:
                pass
    P.init_db()
    yield
    try:
        c = P._get_conn()
        c.close()
    except Exception:
        pass
    _temp_conn_ref[0] = None
    P._reset_conn()
    P._get_conn = orig_get_conn
    P.DB_PATH = orig_db_path
    P.DATA_DIR = orig_data_dir


def conn():
    return P._get_conn()


def insert_listing(listing_id="lid-001", price=2000, beds=1, score=0.15, region="Downtown", is_active=1):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    c = conn()
    c.execute("""
        INSERT INTO listings (listing_id, source, price, beds, neighborhood,
                             region, url, score, fair_value, pct_under,
                             first_seen, last_seen, is_active, is_stale)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        listing_id, "test", price, beds, "King West",
        region, f"http://example.com/{listing_id}", score, 2500, score * 100,
        now, now, is_active, 0,
    ))
    conn().commit()


class TestSavedListingsTable:
    def test_table_exists(self):
        tables = [r[0] for r in conn().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert 'saved_listings' in tables

    def test_insert_saved_listing(self):
        insert_listing(listing_id="lid-save-001")
        sid = P.upsert_saved_listing(email="user@example.com", listing_id="lid-save-001")
        assert sid > 0
        rows = conn().execute(
            "SELECT email, listing_id FROM saved_listings"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0] == ("user@example.com", "lid-save-001")

    def test_upsert_updates_note(self):
        insert_listing(listing_id="lid-upsert-001")
        sid1 = P.upsert_saved_listing(email="user@example.com", listing_id="lid-upsert-001", note="Love it")
        sid2 = P.upsert_saved_listing(email="user@example.com", listing_id="lid-upsert-001", note="Changed my mind")
        # Same saved_id on conflict
        assert sid1 == sid2
        rows = conn().execute(
            "SELECT note FROM saved_listings WHERE listing_id=?", ("lid-upsert-001",)
        ).fetchall()
        assert rows[0][0] == "Changed my mind"

    def test_upsert_same_listing_twice_no_duplicate(self):
        insert_listing(listing_id="lid-dup-001")
        P.upsert_saved_listing(email="user@example.com", listing_id="lid-dup-001")
        P.upsert_saved_listing(email="user@example.com", listing_id="lid-dup-001")
        count = conn().execute("SELECT COUNT(*) FROM saved_listings").fetchone()[0]
        assert count == 1

    def test_get_saved_listings_empty(self):
        results = P.get_saved_listings("nobody@example.com")
        assert results == []

    def test_get_saved_listings_returns_listing_data(self):
        insert_listing(listing_id="lid-get-001", price=2100, beds=2)
        P.upsert_saved_listing(email="user@example.com", listing_id="lid-get-001")
        results = P.get_saved_listings("user@example.com")
        assert len(results) == 1
        assert results[0]['listing_id'] == "lid-get-001"
        assert results[0]['price'] == 2100
        assert results[0]['beds'] == 2

    def test_get_saved_listings_excludes_inactive(self):
        insert_listing(listing_id="lid-inactive-001", is_active=0)
        P.upsert_saved_listing(email="user@example.com", listing_id="lid-inactive-001")
        results = P.get_saved_listings("user@example.com")
        assert results == []

    def test_get_saved_listings_respects_email(self):
        insert_listing(listing_id="lid-multi-001")
        P.upsert_saved_listing(email="user1@example.com", listing_id="lid-multi-001")
        P.upsert_saved_listing(email="user2@example.com", listing_id="lid-multi-001")
        results1 = P.get_saved_listings("user1@example.com")
        results2 = P.get_saved_listings("user2@example.com")
        assert len(results1) == 1
        assert len(results2) == 1

    def test_delete_saved_listing(self):
        insert_listing(listing_id="lid-del-001")
        sid = P.upsert_saved_listing(email="user@example.com", listing_id="lid-del-001")
        deleted = P.delete_saved_listing(sid, "user@example.com")
        assert deleted is True
        results = P.get_saved_listings("user@example.com")
        assert results == []

    def test_delete_requires_correct_email(self):
        insert_listing(listing_id="lid-del-wrong-001")
        sid = P.upsert_saved_listing(email="user@example.com", listing_id="lid-del-wrong-001")
        deleted = P.delete_saved_listing(sid, "other@example.com")
        assert deleted is False
        results = P.get_saved_listings("user@example.com")
        assert len(results) == 1

    def test_is_listing_saved(self):
        insert_listing(listing_id="lid-check-001")
        assert P.is_listing_saved("user@example.com", "lid-check-001") is False
        P.upsert_saved_listing(email="user@example.com", listing_id="lid-check-001")
        assert P.is_listing_saved("user@example.com", "lid-check-001") is True
        assert P.is_listing_saved("other@example.com", "lid-check-001") is False

    def test_multiple_listings_per_user(self):
        insert_listing(listing_id="lid-multi-a")
        insert_listing(listing_id="lid-multi-b")
        insert_listing(listing_id="lid-multi-c")
        P.upsert_saved_listing(email="user@example.com", listing_id="lid-multi-a")
        P.upsert_saved_listing(email="user@example.com", listing_id="lid-multi-b")
        results = P.get_saved_listings("user@example.com")
        assert len(results) == 2
        ids = {r['listing_id'] for r in results}
        assert ids == {"lid-multi-a", "lid-multi-b"}
