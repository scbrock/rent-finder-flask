import requests
from bs4 import BeautifulSoup
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

sources = [
    ("TorontoRentals.com", "https://www.torontorentals.com/listings?location=Downtown+Toronto&type=apartment"),
    ("TorontoRentals direct downtown", "https://www.torontorentals.com/downtown-toronto-apartments"),
    ("RentFaster", "https://www.rentfaster.ca/toronto.php?province=ontario&region=downtown"),
    ("RentFaster API-like", "https://www.rentfaster.ca/api/search.json?province=ON&city=Toronto&type=apartment"),
    (" realtor.ca", "https://www.realtor.ca/toronto-on/real-estate-listing-list.aspx"),
]

for name, url in sources:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        ct = r.headers.get("Content-Type", "")
        print(f"\n{name}: HTTP {r.status_code}, len={len(r.text)}, type={ct[:50]}")
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            prices = re.findall(r'\$[\d,]+', r.text)
            # Get listings
            listings = soup.select(".listing, .listing-card, .property-item, [class*=listing], .card")
            print(f"  Listing elements: {len(listings)}")
            print(f"  Unique prices: {sorted(set(prices))[:10]}")
            if listings:
                for l in listings[:2]:
                    print(f"  Sample: {l.get_text(strip=True)[:100]}")
        print()
    except Exception as e:
        print(f"  ERROR: {e}")
