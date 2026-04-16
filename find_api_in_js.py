"""Inspect Kijiji JavaScript bundle for API endpoint patterns."""

import httpx, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

r = httpx.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273", headers=HEADERS, timeout=20, follow_redirects=True)

# Extract JS bundle URLs
js_bundles = re.findall(r'src="(https://webapp-static[^"]+\.js)"', r.text)
print(f"JS bundles: {len(js_bundles)}")
for b in js_bundles[:5]:
    print(f"  {b}")

# Also look for webpack chunk URLs
chunks = re.findall(r'"(\w{8})"\s*,\s*"[^"]*\.js"', r.text)
print(f"\nWebpack chunks: {chunks[:10]}")

# Look for data-fetching patterns in scripts
scripts = re.findall(r'<script[^>]*>(.*?)</script>', r.text, re.DOTALL)
for i, s in enumerate(scripts):
    if len(s) > 50000:
        # Look for API patterns
        api_calls = re.findall(r'fetch\("([^"]+)"', s) or []
        url_patterns = re.findall(r'(?:https://[^"\']+api[^"\']{0,50}|/api/v\d+[^"\']*)', s)
        if url_patterns:
            print(f"\nScript {i} ({len(s)} chars):")
            print(f"  API URLs: {url_patterns[:10]}")

        # Look for GraphQL patterns
        graphql = re.findall(r'(?:operationName|query\s*\{|query:)', s)
        if graphql:
            print(f"  GraphQL patterns: {graphql[:5]}")

        # Look for listing ID patterns
        listing_ids = re.findall(r'"(adId|listingId|itemId)"\s*:', s)
        if listing_ids:
            print(f"  Listing ID keys: {set(listing_ids)}")