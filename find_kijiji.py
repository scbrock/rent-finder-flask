"""Find actual working Kijiji URLs via search."""

import httpx, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

# Try Kijiji search
search_urls = [
    "https://www.kijiji.ca/search Kajiji apartment Toronto",
    "https://www.kijiji.ca/apartments-condos/toronto-on/k0c1700273l1700273",
    "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/l1700273",
    # Try with location parameter
    "https://www.kijiji.ca/b-apartments-condos/ontario/city-of-toronto/l1700273",
    "https://www.kijiji.ca/b-apartments-condos/ontario/city-of-toronto/page-1/l1700273",
]

for url in search_urls:
    print(f"Fetching: {url[:80]}")
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        print(f"  HTTP {resp.status_code}, final: {resp.url}")
        title = re.search(r'<title>([^<]+)</title>', resp.text)
        if title:
            print(f"  Title: {title.group(1)[:80]}")
        cards = len(re.findall(r'data-testid="listing-card"', resp.text))
        print(f"  Listing cards: {cards}")
    except Exception as e:
        print(f"  Error: {e}")
    print()