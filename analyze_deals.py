import csv

with open('deals_output.csv', 'r', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))

def parse_days(d):
    try:
        return int(d)
    except:
        return 999

fresh = [r for r in rows if parse_days(r.get('days_ago','999')) <= 3]
stale = [r for r in rows if parse_days(r.get('days_ago','999')) > 14]

print(f'Fresh (<=3d): {len(fresh)}, Stale (>14d): {len(stale)}, Total: {len(rows)}')
print(f'Best score: {max(float(r.get("score",0) or 0) for r in rows):.3f}')
print(f'Top deals (score>0): {sum(1 for r in rows if float(r.get("score",0) or 0) > 0)}')

# Top 5 by score
sorted_all = sorted(rows, key=lambda x: float(x.get('score',0) or 0), reverse=True)[:5]
print('\nTop 5 by score:')
for r in sorted_all:
    print(f'  {r["neighborhood"]} {r["beds"]}BR ${r["price"]} score={r["score"]} pct={r["pct_under"]}% days={r["days_ago"]}')

# Region breakdown
from collections import Counter
print('\nBy region:')
for region, count in Counter(r.get('region','None') for r in rows).most_common():
    print(f'  {region}: {count}')