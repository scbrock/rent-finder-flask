"""Test different Kijiji URL structures for Toronto rental listings."""

import httpx, re

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}

test_urls = [
    # Try /b-rentals/ instead of /b-apartments-condos/
    "https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273",
    "https://www.kijiji.ca/b-rentals/city-of-toronto/page-1/l1700273",
    # Try Kijiji international with location ID
    "https://www.kijiji.ca/b-rentals/ontario/page-1/l1700273",
    # Try with different city naming
    "https://www.kijiji.ca/b-rentals/toronto-on/l1700273",
    # Try search instead of browse
    "https://www.kijiji.ca/search?locationId=l1700273&categoryId=1700273",
    "https://www.kijiji.ca/search?locationId=l1700273",
]

for url in test_urls:
    r = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
    title = re.search(r'<title>([^<]+)</title>', r.text)
    cards = len(re.findall(r'data-testid="listing-card"', r.text))
    price_matches = re.findall(r'\$(\d{3,5})', r.text)
    print(f"URL: {url}")
    print(f"  Final: {r.url}")
    print(f"  HTTP {r.status_code}, title: {title.group(1)[:60] if title else 'N/A'}")
    print(f"  Cards={cards}, prices={sorted(set(price_matches))[:8]}")
    print()