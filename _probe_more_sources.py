"""Quick probe of additional rental sources"""
import requests, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

sources = {
    "rentalrehabs": "https://www.rentalrehabs.com/listings?city=Toronto",
    "rentfaster": "https://www.rentfaster.ca/toronto/apartments/",
    "rentboard": "https://www.rentboard.ca/rentals/toronto/",
    "kijiji_beds": "https://www.kijiji.ca/b-apartments-condos/toronto/c44l1700273",
    "rentals_inner": "https://www.rentals.ca/toronto-on/",
}

for name, url in sources.items():
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        size = len(r.text)
        # Look for price patterns
        prices = re.findall(r'\$[\d,]+', r.text)
        unique_prices = sorted(set(prices))[:10]
        price_count = len(prices)
        # Look for listing links
        listing_urls = re.findall(r'href="(/[a-z0-9_-]+/toronto[^"]*)"', r.text, re.I)
        print(f"{name}: HTTP {r.status_code}, size={size}, prices={unique_prices[:5]}, listing_links={len(listing_urls)}")
    except Exception as e:
        print(f"{name}: ERROR {e}")