"""Find correct Kijiji Toronto rental URLs."""

from bs4 import BeautifulSoup
import httpx, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

# Try direct rental category paths
rental_urls = [
    "https://www.kijiji.ca/apartments-condos/city-of-toronto/k0c1700273l1700273",
    "https://www.kijiji.ca/apartments-condos/city-of-toronto/page-1/k0c1700273l1700273",
    "https://www.kijiji.ca/furnished-apartments/city-of-toronto/page-1/s-1c1700273",
    "https://www.kijiji.ca/sublets-toronto/city-of-toronto/k0c1700273l1700273",
    "https://www.kijiji.ca/apartments-condos/city-of-toronto/2 bedroom,toronto/k0c1700273",
]

for url in rental_urls:
    resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
    print(f"URL: {url}")
    print(f"  Final URL: {resp.url}")
    print(f"  HTTP {resp.status_code}, size={len(resp.text)}")

    # Check what category this is
    title_match = re.search(r'<title>([^<]+)</title>', resp.text)
    if title_match:
        print(f"  Title: {title_match.group(1)}")

    # Count rental listings
    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select("[data-testid='listing-card']")
    has_beds = sum(1 for c in cards if c.select_one("[data-testid*='bedroom'], [data-testid*='bathroom']"))
    print(f"  Cards: {len(cards)}, with beds/baths: {has_beds}")

    # Look for category-specific attributes
    price_range = [c.select_one("[data-testid*='listing-price']") for c in cards[:5]]
    prices = [p.get_text(strip=True) if p else "" for p in price_range]
    print(f"  First 5 prices: {prices}")
    print()