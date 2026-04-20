import os, sqlite3

TEST_DIR = 'C:/Users/steph/.openclaw/workspace-coding/rent_finder/tests'
TEST_DATA_DIR = os.path.join(TEST_DIR, 'data')
test_db = os.path.join(TEST_DATA_DIR, 'test_sms.db')
os.makedirs(TEST_DATA_DIR, exist_ok=True)
if os.path.exists(test_db):
    os.remove(test_db)

conn = sqlite3.connect(test_db)
conn.execute('''CREATE TABLE IF NOT EXISTS sms_subscriptions (
    sub_id INTEGER PRIMARY KEY, phone TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
    max_price REAL, min_beds REAL, neighbourhood TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    last_alerted TEXT
)''')
conn.execute("INSERT INTO sms_subscriptions (phone, email) VALUES ('+14165551000', 'a@example.com')")
conn.execute("INSERT INTO sms_subscriptions (phone, email) VALUES ('+14165551001', 'b@example.com')")
conn.commit()
conn.close()

os.environ['RENT_DATA_DIR'] = TEST_DATA_DIR

import importlib, persist
importlib.reload(persist)

subs = persist.get_active_sms_subscriptions()
print(f'get_active_sms_subscriptions returned {len(subs)} rows')
for s in subs:
    print(f'  {s["phone"]} / {s["email"]}')