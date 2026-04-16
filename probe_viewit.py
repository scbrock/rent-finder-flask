"""MC-246: Deep inspect viewit.ca for listing structure."""

import requests, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

url = "https://www.viewit.ca/toronto/"
resp = requests.get(url, headers=HEADERS, timeout=20)
print(f"HTTP {resp.status_code}, size={len(resp.text)}")

text = resp.text

# Find price patterns
prices = re.findall(r'\$[\d,]+', text)
print(f"\nPrices found (first 30): {prices[:30]}")

# Find listing containers
listing_patterns = [
    r'class="[^"]*listing[^"]*"',
    r'class="[^"]*card[^"]*"',
    r'data-price="[^"]*"',
    r'<li[^>]*>.*?\$[\d,]+.*?</li>',
]

for pat in listing_patterns:
    matches = re.findall(pat, text[:50000])
    if matches:
        print(f"\nPattern '{pat[:40]}...': {len(matches)} matches")
        for m in matches[:3]:
            print(f"  {m[:100]}")

# Try to find actual listing URLs
listing_urls = re.findall(r'href="([^"]*toronto[^"]*)"', text)
print(f"\nToronto listing URLs (first 10): {listing_urls[:10]}")

# Check if there's a JSON API endpoint
api_patterns = [
    r'api["\']?\s*:\s*["\']([^"\']+)["\']',
    r'endpoint["\']?\s*:\s*["\']([^"\']+)["\']',
    r'/api/v\d+/[^"\']+',
    r'/listings/[^"\']+',
]
for pat in api_patterns:
    matches = re.findall(pat, text)
    if matches:
        print(f"\nAPI pattern '{pat}': {matches[:5]}")

# Save full HTML for inspection
with open("viewit_homepage.html", "w", encoding="utf-8") as f:
    f.write(text)
print("\nSaved full HTML to viewit_homepage.html")
print(f"File size: {len(text)} chars")