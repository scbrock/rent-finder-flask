"""Inspect StandardListing entries from Kijiji rentals page."""

import httpx, re, json

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}
c = httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True)
c.get("https://www.kijiji.ca/")

r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")

nm = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
data = json.loads(nm.group(1))
apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]

std_listings = {k: v for k, v in apollo.items() if k.startswith("StandardListing:")}
print(f"StandardListing count: {len(std_listings)}")

for k, v in list(std_listings.items())[:5]:
    print(f"\n{k}:")
    print(f"  title: {v.get('title','')[:80]}")
    print(f"  price: {v.get('price')}")
    print(f"  url: {v.get('url','')[:80]}")
    print(f"  description: {str(v.get('description',''))[:150]}")
    print(f"  __typename: {v.get('__typename')}")
    print(f"  keys: {list(v.keys())}")