"""Test Kijiji URLs with different location+category combos."""

import httpx, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

def test_url(url: str):
    with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
        c.get("https://www.kijiji.ca/")
        r = c.get(url)

    title = re.search(r'<title>([^<]+)</title>', r.text)
    cards = len(re.findall(r'data-testid="listing-card"', r.text))
    # Get sample titles to check category
    sample_titles = re.findall(r'data-testid="listing-title"[^>]*>(.*?)</[^>]+>', r.text, re.DOTALL)[:5]
    sample_titles = [re.sub(r'<[^>]+>', '', t).strip() for t in sample_titles]

    # Try to parse Apollo for rental-specific listings
    next_match = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
    apollo_rentals = 0
    if next_match:
        try:
            data = json.loads(next_match.group(1))
            apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]
            apollo_rentals = len([k for k in apollo if k.startswith("RealEstateListing:")])
        except:
            pass

    print(f"\nURL: {url}")
    print(f"  Final: {r.url}")
    print(f"  Title: {title.group(1)[:60] if title else 'N/A'}")
    print(f"  Cards: {cards}, Apollo RealEstate: {apollo_rentals}")
    print(f"  Sample titles: {sample_titles[:3]}")


# Test different URL patterns
urls = [
    # Pattern 1: category + location with number codes
    "https://www.kijiji.ca/b-rentals/city-of-toronto/1__32l1700273",
    # Pattern 2: just city + location
    "https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273",
    # Pattern 3: apartments directly
    "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/l1700273",
    # Pattern 4: apartments with filter
    "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/1__32l1700273",
    # Pattern 5: search with location + category
    "https://www.kijiji.ca/search?locationId=1700273&categoryId=32",
    "https://www.kijiji.ca/search?locationId=l1700273&categoryId=14970008",
]

for url in urls:
    test_url(url)