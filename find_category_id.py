"""Find correct category ID for rental listings."""

import httpx, re, json

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}
c = httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True)
c.get("https://www.kijiji.ca/")

# Test with different category IDs
# Category codes: 1700273=rentals, 14970008=apartments/condos, 14970009=townhouses, 14970010=houses
# Location codes: l1700273=City of Toronto
test_urls = [
    # Try apartments category + city of toronto
    "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/c14970008l1700273",
    # Try with page and sort
    "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/page-1/c14970008l1700273",
    # Try with __32 (rental type filter)
    "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/1__32c14970008l1700273",
    # Try rentals page with subcategory
    "https://www.kijiji.ca/b-rentals/city-of-toronto/1__32l1700273",
    # Try with apartment category
    "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/1__32l1700273",
    # Try search URL
    "https://www.kijiji.ca/search?categoryId=14970008&locationId=1700273",
]

for url in test_urls:
    r = c.get(url)
    nm = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
    if not nm:
        print(f"\n{url}: No __NEXT_DATA__")
        continue

    data = json.loads(nm.group(1))
    apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]
    real = len([k for k in apollo if k.startswith("RealEstateListing:")])
    std = len([k for k in apollo if k.startswith("StandardListing:")])
    cards = len(re.findall(r'data-testid="listing-card"', r.text))

    # Sample titles from RealEstateListing
    sample_titles = []
    for k in apollo:
        if k.startswith("RealEstateListing:"):
            t = apollo[k].get("title", "")
            if t:
                sample_titles.append(t[:60])
        if len(sample_titles) >= 3:
            break

    print(f"\nURL: {url}")
    print(f"  HTTP {r.status_code}, cards={cards}, RealEstate={real}, Standard={std}")
    print(f"  RealEstate samples: {sample_titles}")