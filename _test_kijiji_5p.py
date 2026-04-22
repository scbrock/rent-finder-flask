"""Test 5-page Kijiji scrape"""
import scrape_kijiji_real, time

t0 = time.time()
listings = scrape_kijiji_real.scrape_kijiji(pages=5)
print(f"Got {len(listings)} listings in {time.time()-t0:.1f}s")
prices = sorted(set(l['price'] for l in listings if l.get('price',0) > 500))
print(f"Price range: ${min(prices)} - ${max(prices)}")
for l in listings[:3]:
    print(f"  {l.get('beds',0)}BR ${l.get('price',0)} - {l.get('neighborhood','')}")