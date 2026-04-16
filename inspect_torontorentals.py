"""Inspect torontorentals.com HTML structure to find listing data."""
import requests, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}

url = "https://www.torontorentals.com/rentals"
print(f"Fetching: {url}")
r = requests.get(url, headers=HEADERS, timeout=20)
print(f"Status: {r.status_code}, Len: {len(r.text)}")
print(f"Content-Type: {r.headers.get('content-type','')}")

# Look for JSON data in HTML
json_patterns = [
    r'window\.__NEXT_DATA__\s*=\s*({.*?});',
    r'window\.dataLayer\s*=\s*(\[.*?\]);',
    r'class="listing-card"[^>]*data-price="([^"]*)"',
    r'"price"\s*:\s*"?([0-9]+)',
]

for pat in json_patterns:
    matches = re.findall(pat, r.text[:50000], re.DOTALL)
    if matches:
        print(f"\nPattern {pat[:40]} found {len(matches)} matches:")
        for m in matches[:3]:
            print(f"  {str(m)[:100]}")

# Look for script tags with JSON
script_data = re.findall(r'<script[^>]*>\s*({.*?})\s*</script>', r.text[:100000], re.DOTALL)
print(f"\nScript blocks with JSON: {len(script_data)}")
for s in script_data[:3]:
    if len(s) < 500 and '{' in s:
        print(f"  {s[:200]}")

# Check if any data is embedded in HTML attributes
listing_prices = re.findall(r'data-price="([0-9]+)"', r.text)
listing_titles = re.findall(r'data-title="([^"]+)"', r.text)
print(f"\ndata-price attributes found: {len(listing_prices)}")
print(f"data-title attributes found: {len(listing_titles)}")

# Check for price ranges in the page
price_patterns = re.findall(r'\$([0-9,]+)\s*(?:/month|/mo|/monthly)?', r.text[:20000])
unique_prices = sorted(set(int(p.replace(',','')) for p in price_patterns if int(p.replace(',','')) > 500))[:20]
print(f"\nPrice values found in page (sample): {unique_prices}")