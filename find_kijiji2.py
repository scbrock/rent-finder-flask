"""Find Kijiji rental category URL by examining the category pages."""

import httpx, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

# Try the category browse pages
urls = [
    # Apartments category
    "https://www.kijiji.ca/b-apartments-condos/ontario/page-1/c1700273l1700273",
    # Try with category number
    "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/page-1/c1700273l1700273",
    # Try with 'for-rent' suffix
    "https://www.kijiji.ca/apartments-condos-for-rent/city-of-toronto/k0c1700273l1700273",
    # Try the listings page directly
    "https://www.kijiji.ca/listings/c1700273?sort=priceAsc",
    # Try with 'rent' prefix
    "https://www.kijiji.ca/rent-apartments-condos/city-of-toronto/k0c1700273",
]

for url in urls:
    print(f"URL: {url[:80]}")
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        print(f"  -> HTTP {resp.status_code}, final: {resp.url}")
        title = re.search(r'<title>([^<]+)</title>', resp.text)
        if title:
            print(f"  Title: {title.group(1)[:80]}")
        cards = len(re.findall(r'data-testid="listing-card"', resp.text))
        # Check for rental-specific data attributes
        beds = len(re.findall(r'data-testid="[^"]*bedroom[^"]*"', resp.text))
        baths = len(re.findall(r'data-testid="[^"]*bathroom[^"]*"', resp.text))
        print(f"  Cards={cards}, bedroom attrs={beds}, bathroom attrs={baths}")
    except Exception as e:
        print(f"  Error: {e}")
    print()