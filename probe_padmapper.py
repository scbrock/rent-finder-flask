"""MC-246: Probe padmapper and other aggregator sites."""

import requests, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

# PadMapper - popular Toronto rental aggregator
urls = [
    ("padmapper", "https://www.padmapper.com/apartments-for-rent/toronto-on/"),
    ("padmapper_api", "https://api.padmapper.com/search?city=Toronto&province=ON"),
    ("listingstar", "https://www.listingstar.ca/search?region=Toronto&type=apartment"),
    ("rent_at", "https://www.rent.at/toronto-on/"),
    ("apartmentscanada", "https://www.apartmentscanada.com/toronto-apartments-for-rent"),
    ("mypad", "https://mypad.ca/apartments-for-rent/toronto/"),
    ("canadarentals", "https://www.canadarentals.ca/en/toronto-on/apartments"),
    ("rentalrehabs", "https://www.rentalrehabs.com/listings?city=Toronto"),
]

for name, url in urls:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        prices = sorted(set(re.findall(r'\$[\d,]+', resp.text)))[:15]
        print(f"{name}: HTTP {resp.status_code}, size={len(resp.text)}, prices={prices}")
        if resp.status_code == 200 and len(prices) > 3:
            print(f"  -> GOOD DATA, {len(prices)} unique prices found")
            # Extract some listing links
            links = re.findall(r'href="([^"]*toronto[^"]*)"', resp.text)[:5]
            print(f"  -> Links: {links}")
        print()
    except Exception as e:
        print(f"{name}: ERROR {e}\n")