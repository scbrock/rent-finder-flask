"""Debug: check what DATA_DIR/persist.DB_PATH is after fresh_db runs."""
import pytest, os, sqlite3

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DATA_DIR = os.path.join(TEST_DIR, 'data')
TEST_DB = os.path.join(TEST_DATA_DIR, 'test_sms.db')

@pytest.fixture(autouse=True)
def fresh_db():
    os.makedirs(TEST_DATA_DIR, exist_ok=True)
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    conn = sqlite3.connect(TEST_DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS sms_subscriptions (
        sub_id INTEGER PRIMARY KEY, phone TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        max_price REAL, min_beds REAL, neighbourhood TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        last_alerted TEXT
    )''')
    conn.close()

    os.environ['RENT_DATA_DIR'] = TEST_DATA_DIR

    import importlib, persist
    persist._reset_conn()
    importlib.reload(persist)

    print(f"\n[DEBUG] RENT_DATA_DIR env: {os.environ.get('RENT_DATA_DIR')}")
    print(f"[DEBUG] persist.DATA_DIR: {persist.DATA_DIR}")
    print(f"[DEBUG] persist.DB_PATH: {persist.DB_PATH}")
    print(f"[DEBUG] TEST_DATA_DIR: {TEST_DATA_DIR}")

    yield

def test_debug(fresh_db):
    import persist
    print(f"\n[TEST] persist.DB_PATH: {persist.DB_PATH}")
    persist.upsert_sms_subscription(phone='+14165551000', email='a@example.com')

    conn = sqlite3.connect(TEST_DB)
    rows = conn.execute("SELECT phone FROM sms_subscriptions").fetchall()
    print(f"[TEST] Rows in TEST_DB: {len(rows)}")
    conn.close()

    conn2 = sqlite3.connect(persist.DB_PATH)
    rows2 = conn2.execute("SELECT phone FROM sms_subscriptions").fetchall()
    print(f"[TEST] Rows in persist.DB_PATH: {len(rows2)}")
    conn2.close()