"""MC-246: Get real Toronto rental listings — probe accessible sources."""

import requests, sys

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SOURCES = [
    ("rentals.ca", "https://www.rentals.ca/toronto-on/"),
    ("liv.rent", "https://liv.rent/toronto+on/rentals"),
    ("rentseeker", "https://www.rentseeker.ca/listings?city=toronto&province=ON"),
    ("rentboard", "https://www.rentboard.ca/rentals/listings.aspx?City=Toronto"),
    ("viewit", "https://www.viewit.ca/toronto/"),
    ("rentcanada", "https://www.rentcanada.com/toronto-on/"),
]

for name, url in SOURCES:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        print(f"{name}: HTTP {resp.status_code}, content-type: {resp.headers.get('content-type','?')[:40]}, size: {len(resp.text)}")
        # Check for JS-rendered indicators
        text_lower = resp.text.lower()
        has_vue = "vue" in text_lower or "ng-app" in text_lower
        has_react = "react" in text_lower
        has_angular = "angular" in text_lower
        has_htmx = "htmx" in text_lower
        print(f"  -> vue={has_vue}, react={has_react}, angular={has_angular}, htmx={has_htmx}")
        # Check if listings appear in raw HTML
        has_price = "price" in text_lower or "$" in text_lower
        has_listings = "listing" in text_lower or "apartment" in text_lower
        print(f"  -> has_price={has_price}, has_listing={has_listings}")
        # Sample first 300 chars of body
        print(f"  -> PREVIEW: {resp.text[:300].replace(chr(10),' ')}")
        print()
    except Exception as e:
        print(f"{name}: ERROR {e}")
        print()