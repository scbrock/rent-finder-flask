import persist

conn = persist._get_conn()

# Migrate scrape_runs table to add new columns if they don't exist
for col, col_type in [("errors", "INTEGER NOT NULL DEFAULT 0"), ("duration_secs", "REAL NOT NULL DEFAULT 0")]:
    try:
        conn.execute(f"ALTER TABLE scrape_runs ADD COLUMN {col} {col_type}")
        print(f"Added column: {col}")
        conn.commit()
    except Exception as e:
        print(f"Column {col}: {e}")

print("Migration done.")
conn.close()