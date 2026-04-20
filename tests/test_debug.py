"""Debug test to see what's in the DB when the test runs."""
import pytest, os, sqlite3

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DATA_DIR = os.path.join(TEST_DIR, 'data')
TEST_DB = os.path.join(TEST_DATA_DIR, 'test_sms.db')

@pytest.fixture(autouse=True)
def fresh_db():
    os.makedirs(TEST_DATA_DIR, exist_ok=True)
    print(f"\n[DEBUG] TEST_DB path: {TEST_DB}")
    print(f"[DEBUG] File exists before remove: {os.path.exists(TEST_DB)}")
    if os.path.exists(TEST_DB):
        try:
            os.remove(TEST_DB)
            print("[DEBUG] Removed old DB")
        except Exception as e:
            print(f"[DEBUG] Remove failed: {e}")

    conn = sqlite3.connect(TEST_DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS sms_subscriptions (
        sub_id INTEGER PRIMARY KEY, phone TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        max_price REAL, min_beds REAL, neighbourhood TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        last_alerted TEXT
    )''')
    conn.close()
    print(f"[DEBUG] File exists after create: {os.path.exists(TEST_DB)}")

    os.environ['RENT_DATA_DIR'] = TEST_DATA_DIR

    import importlib, persist
    persist._reset_conn()
    importlib.reload(persist)

    print(f"[DEBUG] After reload, DB_PATH = {persist.DB_PATH}")

    # Check what's in the DB
    conn2 = sqlite3.connect(TEST_DB)
    rows = conn2.execute("SELECT phone, email FROM sms_subscriptions").fetchall()
    print(f"[DEBUG] Rows in sms_subscriptions at fixture start: {len(rows)}")
    for r in rows:
        print(f"  {r}")
    conn2.close()

    yield

    try:
        persist._reset_conn()
    except Exception:
        pass


def test_debug(fresh_db):
    import persist
    persist.upsert_sms_subscription(phone='+14165551000', email='a@example.com')
    persist.upsert_sms_subscription(phone='+14165551001', email='b@example.com')

    # Check DB directly
    conn = sqlite3.connect(TEST_DB)
    rows = conn.execute("SELECT phone, email FROM sms_subscriptions").fetchall()
    print(f"[DEBUG] After insert, DB rows: {len(rows)}")
    conn.close()

    subs = persist.get_active_sms_subscriptions()
    print(f"[DEBUG] get_active_sms_subscriptions returned {len(subs)}")
    assert False, f"expected 2, got {len(subs)}"