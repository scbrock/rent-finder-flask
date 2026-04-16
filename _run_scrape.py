"""Verify scrape_kijiji.py works and print results."""

import sys
sys.path.insert(0, r"C:\Users\steph\.openclaw\workspace-coding\rent_finder")

from scrape_kijiji import scrape

print("Running scrape...")
results = scrape(pages=2)
print(f"\nTotal: {len(results)} listings")
print("\nSample:")
for r in results[:10]:
    print(f"  {r['price_str'] or r['price']} | {r.get('beds','?')}bd | {r.get('location','')[:40]}")
    print(f"    {r['title'][:80]}")