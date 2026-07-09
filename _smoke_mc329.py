import requests
r = requests.get('http://localhost:8083/api/deals', timeout=30)
print('status:', r.status_code)
data = r.json()
print('total:', data['total'])
print('returned:', len(data['deals']))
trends_present = sum(1 for d in data['deals'] if d.get('neighborhood_trend') is not None)
trends_none = sum(1 for d in data['deals'] if d.get('neighborhood_trend') is None)
print(f'neighborhood_trend present: {trends_present}')
print(f'neighborhood_trend None (no data): {trends_none}')
for d in data['deals'][:5]:
    t = d.get('neighborhood_trend')
    if t:
        print(f"  {d['neighbourhood']}: dir={t['direction']} pct={t['pct_change']} days={t['days_of_data']}")

# Also check /api/meta
r2 = requests.get('http://localhost:8083/api/meta', timeout=30)
print()
print('/api/meta status:', r2.status_code)
meta = r2.json()
print('neighborhood_trends present:', 'neighborhood_trends' in meta)
print('neighborhood_trends count:', len(meta.get('neighborhood_trends', {})))
for k, v in list(meta.get('neighborhood_trends', {}).items())[:5]:
    print(f"  {k}: {v}")