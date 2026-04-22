"""Quick probe of rent.at Toronto"""
import requests, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

print("=== Testing rent.at ===")
r = requests.get("https://www.rent.at/toronto-on/", headers=HEADERS, timeout=20)
print(f"Status: {r.status_code}, Size: {len(r.text)}")

# Find links with prices
hrefs = re.findall(r'href="(https?://[^"]+)"', r.text)
toronto_links = [h for h in hrefs if 'toronto' in h.lower() or 'rent' in h.lower()]
print(f"Total hrefs: {len(hrefs)}, Toronto-related: {len(toronto_links)}")
print(f"Sample links: {toronto_links[:5]}")

# Look for JSON data
for pattern in [r'window\.dataLayer\s*=\s*(\[.*?\]);', r'"price":\s*[\d]+', r'"listing":\s*\{']:
    matches = re.findall(pattern, r.text[:50000], re.DOTALL)
    if matches:
        print(f"Pattern {pattern!r}: {len(matches)} matches")
        print(f"  Sample: {matches[0][:200]}")

# Try to parse any JSON
try:
    data = json.loads(r.text[:1000])
    print(f"JSON root type: {type(data)}")
except:
    pass

# Check for specific listing patterns
listing_cards = re.findall(r'data-price=["\']([^"\']+)["\']', r.text)
print(f"data-price attrs: {listing_cards[:5]}")

price_spans = re.findall(r'<span[^>]*>[\$][\d,]+</span>', r.text)
print(f"Price spans: {price_spans[:5]}")