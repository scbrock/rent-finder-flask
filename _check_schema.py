import persist

conn = persist._get_conn()
cur = conn.execute("SELECT sql FROM sqlite_master WHERE name='scrape_runs'")
schema = cur.fetchone()
if schema:
    print("scrape_runs schema:", schema[0])
else:
    print("scrape_runs table not found")
    # Check what tables exist
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    print("Tables:", [r[0] for r in cur.fetchall()])

# Also check listings columns
cur = conn.execute("SELECT sql FROM sqlite_master WHERE name='listings'")
print("\nlistings schema:", cur.fetchone()[0])