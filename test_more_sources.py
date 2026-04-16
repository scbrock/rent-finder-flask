import requests
from bs4 import BeautifulSoup
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

sources = [
    ("Viewit downtown", "https://www.viewit.ca/toronto.aspx"),
    ("Viewit downtown direct", "https://www.viewit.ca/torontodowntown.aspx"),
    ("Viewit API", "https://www.viewit.ca/available.php"),
    ("Canadian Apartments", "https://www.canadianapartments.com/toronto/"),
    ("RentSeeker", "https://www.rentseeker.ca/toronto"),
    ("liv.rent", "https://liv.rent/toronto/apartments-for-rent"),
    ("Rentster", "https://www.rentster.ca/toronto-apartments"),
    ("BrewCap", "https://www.brewcap.com/toronto-rentals"),
    ("Real Estate pins", "https://www.realestatepins.ca/toronto"),
    ("Apartment.ca", "https://www.apartment.ca/toronto"),
    ("Rental.ca direct", "https://www.rental.ca/toronto-on/apartments"),
    ("SmartSearch Toronto", "https://www.smartsearchnetwork.com/toronto"),
]

for name, url in sources:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        ct = r.headers.get("Content-Type", "")
        print(f"\n{name}: HTTP {r.status_code}, len={len(r.text)}, ct={ct[:50]}")
        if r.status_code == 200 and len(r.text) > 2000:
            soup = BeautifulSoup(r.text, "html.parser")
            prices = re.findall(r'\$[\d,]+', r.text)
            unique_prices = sorted(set(prices))[:20]
            links = soup.find_all("a", href=True)
            external_links = [l["href"] for l in links if l["href"].startswith("http") and "viewit" not in l["href"] and len(l["href"]) < 100]
            print(f"  Unique prices: {unique_prices[:10]}")
            print(f"  External links sample: {external_links[:5]}")
            # Check if this looks like real listing content
            if len(unique_prices) >= 3:
                print(f"  -> HAS LISTINGS ({len(unique_prices)} prices found)")
    except Exception as e:
        print(f"  ERROR: {e}")
