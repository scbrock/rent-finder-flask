"""MC-246: Try viewit.ca city zones listing pages."""

import requests, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# Try the city zones page for Toronto
url = "https://www.viewit.ca/torontozones?CID=14"
resp = requests.get(url, headers=HEADERS, timeout=20)
print(f"City zones: HTTP {resp.status_code}, size={len(resp.text)}")

prices = sorted(set(re.findall(r'\$[\d,]+', resp.text)))
print(f"Prices (unique): {prices[:20]}")
print(f"Prices count: {len(prices)}")

# Try listings page for each zone
zones = re.findall(r'href="([^"]*toronto[^"]*)"', resp.text)
print(f"\nToronto links found: {len(zones)}")
for z in list(set(zones))[:10]:
    print(f"  {z}")

# Check if this is a redirect page
if resp.history:
    print(f"Redirected: {[r.status_code for r in resp.history]}")
    print(f"Final URL: {resp.url}")