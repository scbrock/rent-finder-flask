"""MC-246: Find and test Kijiji's internal AJAX API for listings."""

import httpx, json, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
}

# First, get the main page to find API endpoints
r = httpx.get("https://www.kijiji.ca/b-apartments-condos/city-of-toronto/l1700273", headers={
    "User-Agent": HEADERS["User-Agent"],
    "Accept-Language": HEADERS["Accept-Language"],
}, timeout=20, follow_redirects=True)

# Find AJAX endpoint URLs
api_urls = re.findall(r'["\']([^"\']*(?:api|graphql|search|listings|v3)[^"\']*)["\']', r.text[:50000])
print(f"API URLs found in HTML: {api_urls[:20]}")

# Look for Next.js data
next_data = re.findall(r'__NEXT_DATA__.*?<script[^>]*>(.*?)</script>', r.text, re.DOTALL)
for nd in next_data:
    print(f"__NEXT_DATA__ found ({len(nd)} chars): {nd[:500]}")

# Look for graphQL endpoint
graphql = re.findall(r'endpoint["\s:]+([^,\n"]+)', r.text[:20000])
print(f"GraphQL endpoints: {graphql[:5]}")

# Check if there's an API config
api_config = re.findall(r'"apiUrl"\s*:\s*"([^"]+)"', r.text)
print(f"apiUrl: {api_config[:5]}")

# Try the Listings API endpoint
for path in [
    "/api/listings",
    "/api/search",
    "/graphql",
    "/api/v1/listings",
    "/api/v2/search",
]:
    try:
        r2 = httpx.get(f"https://www.kijiji.ca{path}", headers=HEADERS, timeout=10, follow_redirects=True)
        print(f"GET {path}: HTTP {r2.status_code}, ct={r2.headers.get('content-type','?')[:40]}, size={len(r2.text)}")
    except Exception as e:
        print(f"GET {path}: {e}")