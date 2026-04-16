import json
from collections import Counter

with open('rent_finder/output/raw_2026-04-16.json') as f:
    data = json.load(f)

urls = [d['url'] for d in data]
url_counts = Counter(urls)
dupes = [(u, c) for u, c in url_counts.items() if c > 1]
print(f"Total URLs: {len(urls)}, Unique: {len(set(urls))}, Dupes: {len(dupes)}")
print(f"Dupe count: {len(urls) - len(set(urls))}")
print(f"Example dupes: {dupes[:5] if dupes else 'None'}")

import pandas as pd
df = pd.read_csv('rent_finder/deals_output.csv')
print(f"deals_output rows: {len(df)}")
print(f"duplicate links: {df['link'].duplicated().sum()}")
print(f"Unique links: {df['link'].nunique()}")

# Sample links
print("\nSample links from raw data:")
for d in data[:5]:
    print(f"  {d['link']}")