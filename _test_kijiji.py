"""Test Kijiji scraper"""
import scrape_kijiji_real, time

t0 = time.time()
listings = scrape_kijiji_real.scrape_kijiji(pages=3)
print(f"Got {len(listings)} listings in {time.time()-t0:.1f}s")
for l in listings[:5]:
    print(f"  {l.get('beds',0)}BR ${l.get('price',0)} - {l.get('neighborhood','')}")