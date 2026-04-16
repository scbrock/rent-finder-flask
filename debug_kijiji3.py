"""Debug why Kijiji shows category page instead of listings."""

import httpx, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as client:
    # Step 1: visit homepage to get cookies
    r0 = client.get("https://www.kijiji.ca")
    print(f"Homepage: HTTP {r0.status_code}, cookies: {list(client.cookies.keys())}")

    # Step 2: visit the listings page with cookies
    r = client.get("https://www.kijiji.ca/b-apartments-condos/city-of-toronto/l1700273")
    print(f"Listings: HTTP {r.status_code}, final: {r.url}")
    title = re.search(r'<title>([^<]+)</title>', r.text)
    print(f"Title: {title.group(1)[:80] if title else 'N/A'}")

    # Is this the category listing or a redirect?
    print(f"URL path: {r.url.path}")

    # Look for search results container
    has_search = "search-results" in r.text.lower() or "search result" in r.text.lower()
    has_category = "All Categories" in r.text
    print(f"Has search results: {has_search}, Has 'All Categories': {has_category}")

    listing_count = len(re.findall(r'data-testid="listing-card"', r.text))
    print(f"Listing card count: {listing_count}")

    # Check if the response is actually the listings (not a redirect to homepage)
    if listing_count > 0:
        # Get first few prices from actual listing cards
        cards_data = re.findall(r'data-testid="listing-card"[^>]*>(.*?)</section>', r.text, re.DOTALL)
        print(f"Card sections found: {len(cards_data)}")
        for cd in cards_data[:3]:
            price = re.search(r'\$[\d,]+', cd)
            print(f"  Card price: {price.group(0) if price else 'N/A'}")
            title_m = re.search(r'data-testid="listing-title"[^>]*>(.*?)</', cd)
            if title_m:
                print(f"  Card title: {title_m.group(1)[:60]}")