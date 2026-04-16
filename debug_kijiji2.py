"""Debug why the Kijiji page shows category homepage instead of listings."""

import httpx, re

# First, compare what headers/cookies are needed
# Try the exact URL that successfully got listings in the first probe

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Use httpx with compression and keep-alive
with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True, http2=True) as client:
    # Try with HTTP/2
    r = client.get("https://www.kijiji.ca/b-apartments-condos/city-of-toronto/l1700273")
    print(f"HTTP/2: {r.status_code}, final: {r.url}")
    title = re.search(r'<title>([^<]+)</title>', r.text)
    print(f"Title: {title.group(1)[:80] if title else 'N/A'}")

    # Check for any Set-Cookie headers
    print(f"Cookies received: {dict(r.headers).get('set-cookie', 'none')[:200]}")

    # Check if this is actually the category page or the listing page
    has_search_results = "search-results" in r.text or "search-results" in r.text.lower()
    has_category = "All Categories" in r.text
    print(f"Has search results: {has_search_results}, Has 'All Categories': {has_category}")

    # Check for any listing data in the initial HTML
    has_listing_cards = 'data-testid="listing-card"' in r.text
    print(f"Has listing-card in HTML: {has_listing_cards}")

    # Try to find the actual listing count
    listing_count = len(re.findall(r'data-testid="listing-card"', r.text))
    print(f"Listing card count: {listing_count}")

    # Check if page has React hydration data
    next_data = re.findall(r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', r.text, re.DOTALL)
    print(f"JSON scripts: {len(next_data)}")
    for nd in next_data[:3]:
        if len(nd) > 200:
            print(f"  JSON chunk ({len(nd)} chars): {nd[:300]}")

# Also check the cookies that are being sent
print("\n--- Checking cookie jar ---")
import http.cookiejar
cj = http.cookiejar.CookieJar()
with httpx.Client(cookies=cj, headers=HEADERS, timeout=20, follow_redirects=True) as client2:
    r2 = client2.get("https://www.kijiji.ca/b-apartments-condos/city-of-toronto/l1700273")
    print(f"After first request: cookies = {[c.name for c in cj]}")