import sqlite3, statistics, os

db = r'C:\Users\steph\.openclaw\workspace-coding\rent_finder\data\listings.db'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

dist = conn.execute('SELECT is_active, COUNT(*) FROM listings GROUP BY is_active').fetchall()
print('is_active dist:', [(r[0], r[1]) for r in dist])

scores = [r[0] for r in conn.execute('SELECT score FROM listings WHERE score IS NOT NULL').fetchall()]
if scores:
    print(f'Score stats: min={min(scores):.3f}, max={max(scores):.3f}, mean={statistics.mean(scores):.3f}')

top = conn.execute('SELECT listing_id, neighborhood, price, beds, score, pct_under FROM listings WHERE is_active=1 ORDER BY score DESC LIMIT 10').fetchall()
for r in top:
    lid = str(r[0])[:20]
    neigh = r[1] or '?'
    price = r[2]
    beds = r[3]
    score = r[4]
    pct = r[5]
    print(f'  {lid} | {neigh} | ${price:.0f} | {beds}br | score={score:.3f} pct={pct}')

# Check why avg score is -0.11
neg = conn.execute('SELECT COUNT(*) FROM listings WHERE score < 0').fetchone()[0]
pos = conn.execute('SELECT COUNT(*) FROM listings WHERE score > 0').fetchone()[0]
zero = conn.execute('SELECT COUNT(*) FROM listings WHERE score = 0 OR score IS NULL').fetchone()[0]
print(f'Score distribution: negative={neg}, positive={pos}, zero/null={zero}')

# Check source
src_dist = conn.execute('SELECT source, COUNT(*) FROM listings GROUP BY source ORDER BY COUNT(*) DESC').fetchall()
print('Sources:', [(r[0], r[1]) for r in src_dist])

conn.close()