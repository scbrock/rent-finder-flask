import sys
sys.path.insert(0, 'C:\\Users\\steph\\.openclaw\\workspace-coding\\rent_finder')

import persist
import csv

# Check DB
try:
    conn = persist._get_conn()
    cur = conn.execute("""
        SELECT l.id, l.price, l.neighbourhood, l.beds, l.score, l.fair_value, l.pct_under, l.days_ago, l.is_new
        FROM listings l WHERE l.is_active = 1 ORDER BY l.score DESC LIMIT 20
    """)
    rows = cur.fetchall()
    conn.close()
    if rows:
        print('DB Top 20 deals:')
        for r in rows:
            print(f'  ID={r[0]} | price={r[1]} | neighbourhood={r[2]} | beds={r[3]} | score={r[4]:.3f} | FV={r[5]} | pct={r[6]:.1f}% | {r[7]}d ago | new={r[8]}')
    else:
        print('No active listings in DB')
except Exception as e:
    print(f'DB error: {e}')

# Check CSV
try:
    with open('deals_output.csv', 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    print(f'deals_output.csv: {len(rows)} rows')
    if rows:
        sorted_rows = sorted(rows, key=lambda x: float(x.get('score', 0) or 0), reverse=True)[:10]
        print('Top 10 by score from CSV:')
        for r in sorted_rows:
            print(f'  {r.get("neighbourhood")} {r.get("beds")}BR ${r.get("price")} score={r.get("score")} pct={r.get("pct_under")}%')
except Exception as e:
    print(f'CSV error: {e}')