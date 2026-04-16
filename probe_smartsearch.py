"""MC-246: Probe viewit.ca SmartSearch AJAX endpoint."""

import requests, json, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json; charset=utf-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.viewit.ca/Listings",
}

# SmartSearch endpoint from the page source
# It uses ScriptService - URL is /vwdefault.aspx/GetListingsSmartSearch
# via POST with JSON body

base = "https://www.viewit.ca/vwdefault.aspx"

# Try different JSON payloads
searches = [
    '{"sSearch":"Toronto"}',
    '{"sSearch":"Toronto, ON"}',
    '{"sSearch":"M5V"}',
    '{"sSearch":"Downtown Toronto"}',
    '{"sSearch":"apartment toronto"}',
]

for body in searches:
    try:
        resp = requests.post(
            f"{base}/GetListingsSmartSearch",
            headers=HEADERS,
            data=body,
            timeout=20,
        )
        print(f"Search '{body[:40]}...': HTTP {resp.status_code}, ct={resp.headers.get('content-type','?')[:40]}")
        print(f"  Response ({len(resp.text)} chars): {resp.text[:300]}")
        print()
    except Exception as e:
        print(f"Search error: {e}")

# Also try without JSON - classic ASP.NET AJAX
searches2 = [
    ("POST", f"{base}/GetListingsSmartSearch", "sSearch=Toronto"),
    ("GET", "https://www.viewit.ca/Listings?sort=price&dir=asc&q=Toronto", ""),
    ("GET", "https://www.viewit.ca/Listings?q=toronto", ""),
]

for method, url, data in searches2:
    try:
        if method == "POST":
            resp = requests.post(url, headers={k: v for k, v in HEADERS.items() if k != "Content-Type"}, data=data, timeout=20)
        else:
            resp = requests.get(url, headers=HEADERS, timeout=20)
        print(f"{method} {url[:60]}: HTTP {resp.status_code}, ct={resp.headers.get('content-type','?')[:40]}")
        print(f"  Response: {resp.text[:200]}")
    except Exception as e:
        print(f"Error: {e}")