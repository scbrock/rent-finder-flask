"""Test various Kijiji rental URLs."""

import httpx, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

# Use the URL from find_deals.py
test_urls = [
    "https://www.kijiji.ca/b-rentals/city-of-toronto/1__32?sort=priceAsc",
    "https://www.kijiji.ca/b-rentals/city-of-toronto/2__32?sort=priceAsc",
    "https://www.kijiji.ca/b-rentals/city-of-toronto/?sort=priceAsc",
    "https://www.kijiji.ca/b-rentals/ontario/city-of-toronto/page-1/l1700273",
    "https://www.kijiji.ca/b-apartments-condos/ontario/city-of-toronto/page-1/l1700273",
]

for url in test_urls:
    r = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
    title = re.search(r'<title>([^<]+)</title>', r.text)
    cards = len(re.findall(r'data-testid="listing-card"', r.text))
    # Check for rental-specific attrs
    beds = len(re.findall(r'data-testid="[^"]*bedroom[^"]*"', r.text))
    baths = len(re.findall(r'data-testid="[^"]*bathroom[^"]*"', r.text))
    # Check price range of listings
    price_matches = re.findall(r'\$(\d{3,5})\s*(?:/month|mo)', r.text)
    print(f"URL: {url}")
    print(f"  HTTP {r.status_code}, title: {title.group(1)[:60] if title else 'N/A'}")
    print(f"  Cards={cards}, bedroom_attrs={beds}, bathroom_attrs={baths}")
    print(f"  Price patterns: {sorted(set(price_matches))[:10]}")
    print()