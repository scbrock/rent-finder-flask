"""Inspect Kijiji category page for actual listing URLs."""

import httpx, re

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}
c = httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)
c.get("https://www.kijiji.ca/")

r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")
print(f"HTTP {r.status_code}, size={len(r.text)}, URL: {r.url}")

# Look for all links to individual listings (ad ID pattern)
listing_links = re.findall(r'href="(/ad-view-[^"]+)"', r.text)
print(f"Ad view links: {listing_links[:5]}")

# Check what category this actually is
# Look for breadcrumb or category indicator
breadcrumb = re.search(r'"breadcrumb"\s*:\s*\[(.*?)\]', r.text[:5000])
if breadcrumb:
    print(f"Breadcrumb: {breadcrumb.group(0)[:200]}")

# Look for the category description
desc = re.search(r'"description"\s*:\s*"([^"]{50,500})"', r.text[:10000])
if desc:
    print(f"Description: {desc.group(1)}")

# Try to find the JavaScript bundle URLs
js_bundles = re.findall(r'src="([^"]*\.js[^"]*)"', r.text[:20000])
print(f"JS bundles: {js_bundles[:10]}")

# Check if this is actually returning a listing results page
# vs a category navigation page
if "search-results" in r.text.lower():
    print("Page contains 'search-results'")
if "listing-card" in r.text:
    print("Page contains 'listing-card'")
if "featured-ads" in r.text.lower():
    print("Page contains 'featured-ads'")

# Find any JSON data in script tags
json_blocks = re.findall(r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', r.text, re.DOTALL)
print(f"JSON blocks: {len(json_blocks)}")
for jb in json_blocks[:3]:
    if len(jb) > 200:
        print(f"  JSON chunk ({len(jb)} chars): {jb[:300]}")

# Check for any API endpoint in the page
api = re.findall(r'["\']?(https?://[^"\']*api[^"\']{0,100})["\']?', r.text[:50000])
print(f"API URLs: {api[:10]}")