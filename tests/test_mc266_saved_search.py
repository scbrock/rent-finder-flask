"""
Tests for MC-266: Saved Searches / Watchlist
Tests the saved_searches table and CRUD functions in persist.py.
"""

import pytest, os, sys, sqlite3, tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import persist as P

# Use a temp DB for all tests
TEST_DB_DIR = tempfile.mkdtemp()
TEST_DB = os.path.join(TEST_DB_DIR, "test_mc266.db")


# Cached connection so _get_conn() and conn() both return the same object
_temp_conn_ref = [None]  # list used for mutability in closure

def _temp_conn():
    # Return existing open connection if available; only create new one when needed.
    if _temp_conn_ref[0] is not None:
        try:
            # Test the connection is still usable
            _temp_conn_ref[0].execute("SELECT 1")
            return _temp_conn_ref[0]
        except Exception:
            pass  # closed or broken, recreate
    os.makedirs(TEST_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(TEST_DB, isolation_level='DEFERRED')
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _temp_conn_ref[0] = conn
    return conn


@pytest.fixture(autouse=True)
def fresh_db():
    """Patch persist to use temp DB, init schema, yield, restore."""
    # Reset the cached connection and close any existing one
    P._reset_conn()
    _temp_conn_ref[0] = None

    orig_get_conn = P._get_conn
    orig_db_path = P.DB_PATH
    orig_data_dir = P.DATA_DIR
    P._get_conn = _temp_conn
    P.DATA_DIR = TEST_DB_DIR
    P.DB_PATH = TEST_DB
    # Remove stale temp DB files
    for f in [TEST_DB, TEST_DB + "-wal", TEST_DB + "-shm", TEST_DB + "-journal"]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except PermissionError:
                pass  # Windows: file still open
    P.init_db()
    yield
    # Close the connection the test left open
    try:
        c = P._get_conn()
        c.close()
    except Exception:
        pass
    _temp_conn_ref[0] = None
    P._reset_conn()  # clear cached conn before restoring
    P._get_conn = orig_get_conn
    P.DB_PATH = orig_db_path
    P.DATA_DIR = orig_data_dir


def conn():
    return P._get_conn()


def insert_listing(price=2000, beds=1, score=0.15, region="Downtown", is_active=1):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    c = conn()
    c.execute("""
        INSERT INTO listings (listing_id, source, price, beds, neighborhood,
                             region, url, score, fair_value, pct_under,
                             first_seen, last_seen, is_active, is_stale)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        f"lid-{price}-{beds}-{score}", "test", price, beds, "King West",
        region, f"http://example.com/{price}", score, 2500, score * 100,
        now, now, is_active, 0,
    ))
    conn().commit()


class TestSavedSearchTable:
    def test_table_exists(self):
        tables = [r[0] for r in conn().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert 'saved_searches' in tables

    def test_insert_saved_search(self):
        P.upsert_saved_search(
            email="test@example.com", name="My 1BR Search",
            beds_min=1.0, beds_max=1.0, region="Downtown", min_score=0.15,
        )
        rows = conn().execute(
            "SELECT email, name, beds_min, beds_max, region, min_score FROM saved_searches"
        ).fetchall()
        assert len(rows) == 1
        email, name, beds_min, beds_max, region, min_score = rows[0]
        assert email == "test@example.com"
        assert name == "My 1BR Search"
        assert beds_min == 1.0
        assert beds_max == 1.0
        assert region == "Downtown"
        assert min_score == 0.15

    def test_upsert_updates_existing(self):
        P.upsert_saved_search(email="test@example.com", name="My Search", min_score=0.10)
        P.upsert_saved_search(email="test@example.com", name="My Search", min_score=0.20)
        rows = conn().execute(
            "SELECT min_score FROM saved_searches WHERE email=? AND name=?",
            ("test@example.com", "My Search")
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 0.20

    def test_get_saved_searches_empty(self):
        results = P.get_saved_searches("nobody@example.com")
        assert results == []

    def test_get_saved_searches_returns_match_count(self):
        P.upsert_saved_search(email="test@example.com", name="Any", min_score=0.0)
        insert_listing(price=2000, beds=1, score=0.20)

        results = P.get_saved_searches("test@example.com")
        assert len(results) == 1
        assert results[0]['match_count'] == 1
        assert results[0]['name'] == "Any"

    def test_get_saved_searches_top_match_highest_score(self):
        P.upsert_saved_search(email="test@example.com", name="Top", min_score=0.0)
        # Lower price = higher score (better deal)
        insert_listing(price=2200, beds=1, score=0.12)
        insert_listing(price=2000, beds=1, score=0.25)  # better deal

        results = P.get_saved_searches("test@example.com")
        top = results[0]['top_match']
        assert top is not None
        assert top['price'] == 2000  # better deal (higher score)

    def test_delete_saved_search(self):
        sid = P.upsert_saved_search(email="test@example.com", name="To Delete")
        deleted = P.delete_saved_search(sid, "test@example.com")
        assert deleted is True
        deleted2 = P.delete_saved_search(sid, "test@example.com")
        assert deleted2 is False

    def test_delete_requires_correct_email(self):
        sid = P.upsert_saved_search(email="test@example.com", name="Private")
        deleted = P.delete_saved_search(sid, "other@example.com")
        assert deleted is False
        results = P.get_saved_searches("test@example.com")
        assert len(results) == 1

    def test_touch_saved_search(self):
        sid = P.upsert_saved_search(email="test@example.com", name="Touch Test")
        P.touch_saved_search(sid)
        row = conn().execute(
            "SELECT last_checked FROM saved_searches WHERE search_id = ?", (sid,)
        ).fetchone()
        assert row is not None
        assert row[0] is not None

    def test_update_saved_search_match_count(self):
        sid = P.upsert_saved_search(email="test@example.com", name="Count Test")
        P.update_saved_search_match_count(sid, 42)
        row = conn().execute(
            "SELECT last_match_count FROM saved_searches WHERE search_id = ?", (sid,)
        ).fetchone()
        assert row[0] == 42

    def test_match_count_respects_beds_filter(self):
        P.upsert_saved_search(email="test@example.com", name="1BR only", beds_min=1, beds_max=1)
        insert_listing(price=1500, beds=0, score=0.10)   # Studio — excluded
        insert_listing(price=2000, beds=1, score=0.10)   # 1BR — included
        insert_listing(price=3000, beds=2, score=0.10)   # 2BR — excluded

        results = P.get_saved_searches("test@example.com")
        assert results[0]['match_count'] == 1

    def test_match_count_excludes_inactive(self):
        P.upsert_saved_search(email="test@example.com", name="Active only")
        insert_listing(price=2000, beds=1, score=0.10, is_active=1)
        insert_listing(price=2100, beds=1, score=0.10, is_active=0)

        results = P.get_saved_searches("test@example.com")
        assert results[0]['match_count'] == 1  # only active counted

    def test_match_count_respects_region_filter(self):
        P.upsert_saved_search(email="test@example.com", name="Downtown Only", region="Downtown")
        insert_listing(price=2000, beds=1, score=0.10, region="Downtown")
        insert_listing(price=1900, beds=1, score=0.10, region="Midtown")

        results = P.get_saved_searches("test@example.com")
        assert results[0]['match_count'] == 1

    def test_match_count_respects_price_filter(self):
        P.upsert_saved_search(email="test@example.com", name="Under 2500", price_max=2500)
        insert_listing(price=2000, beds=1, score=0.10)   # under
        insert_listing(price=3000, beds=1, score=0.10)   # over — excluded

        results = P.get_saved_searches("test@example.com")
        assert results[0]['match_count'] == 1

    def test_match_count_respects_min_score_filter(self):
        P.upsert_saved_search(email="test@example.com", name="Score > 0.20", min_score=0.20)
        insert_listing(price=2000, beds=1, score=0.15)   # below threshold
        insert_listing(price=1900, beds=1, score=0.25)   # above threshold

        results = P.get_saved_searches("test@example.com")
        assert results[0]['match_count'] == 1
