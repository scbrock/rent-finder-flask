"""Test specific Kijiji page to understand why rental listings are missing."""

import httpx, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
    c.get("https://www.kijiji.ca/")

    # Try the specific URL format that works in find_deals.py
    # /b-rentals/city-of-toronto/1__32?sort=priceAsc
    url = "https://www.kijiji.ca/b-rentals/city-of-toronto/1__32?sort=priceAsc"
    r = c.get(url)
    print(f"URL: {url}")
    print(f"  HTTP {r.status_code}, final URL: {r.url}")
    print(f"  Content-type: {r.headers.get('content-type','')}")

    title = re.search(r'<title>([^<]+)</title>', r.text)
    print(f"  Title: {title.group(1)[:80] if title else 'N/A'}")

    # Check for search results
    has_search_results = "search-result" in r.text or "listing-card" in r.text
    print(f"  Has listing markup: {has_search_results}")

    cards = re.findall(r'data-testid="listing-card"', r.text)
    print(f"  Listing cards: {len(cards)}")

    # Parse JSON
    next_match = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
    if next_match:
        data = json.loads(next_match.group(1))
        apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]
        print(f"  Apollo entries: {len(apollo)}")
        print(f"  Categories: {[k for k in apollo if 'Category' in k]}")
        print(f"  Locations: {[k for k in apollo if 'Location' in k][:5]}")

        # Look for srp data
        srp = data["props"]["pageProps"].get("srp", {})
        print(f"  srp keys: {list(srp.keys()) if srp else 'empty'}")

        # Check for ads list
        for k in ["ads", "listings", "results", "items"]:
            if k in srp:
                v = srp[k]
                print(f"  srp.{k}: type={type(v).__name__}, len={len(v) if isinstance(v, (list, dict)) else 'N/A'}")

    # Also check the actual HTTP response size
    print(f"  Total HTML size: {len(r.text)}")