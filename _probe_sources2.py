"""MC-290: Probe additional Toronto rental listing sources"""
import requests, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.google.com",
}

sources = {
    "realpages": ("https://www.realpages.com/toronto-apartments-for-rent/", "apartments"),
    "surfrlty": ("https://www.surfrealty.ca/toronto-rentals", "listings"),
    "4rent": ("https://4rent.ca/toronto-on/", "rental"),
    "rentseeker": ("https://www.rentseeker.ca/toronto-apartments", "rent"),
    "toronto4rent": ("https://toronto.4rent.ca/", "listing"),
    "avendor": ("https://www.avendor.ca/toronto-rentals", "toronto"),
}

for name, (url, _) in sources.items():
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        prices = re.findall(r'\$(\d{3,5}(?:,\d{3})*)', r.text)
        unique = sorted(set(prices))[:8]
        links = re.findall(r'href="(/[a-z0-9_-]+/toronto[^"]*)"', r.text, re.I)
        print(f"{name}: {r.status_code}, size={len(r.text)}, prices={unique[:5]}, links={len(links)}")
    except Exception as e:
        print(f"{name}: ERROR {e}")