import requests
from bs4 import BeautifulSoup
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Check if rentals.ca has actual listing content
url = "https://www.rental.ca/toronto-on/apartments"
r = requests.get(url, headers=HEADERS, timeout=20)
print(f"rental.ca: HTTP {r.status_code}, len={len(r.text)}")

soup = BeautifulSoup(r.text, "html.parser")

# Find all text content to check if JS-rendered
text = soup.get_text()
print(f"Text length: {len(text)}")
print(f"Text sample (chars 500-1500): '{text[500:1500]}'")

# Look for listing containers
for sel in [
    ".listing", ".listing-card", ".listing-item", "[class*=listing]",
    ".property", ".property-card", "[class*=property]",
    ".result", ".result-item",
]:
    els = soup.select(sel)
    if els:
        print(f"\nSelector '{sel}': {len(els)} found")
        for e in els[:2]:
            print(f"  {str(e)[:150]}")

# Try to find any Toronto/Downtown-specific listings
toronto_text = soup.find_all(string=re.compile(r'(?i)downtown|toronto|king west|liberty',))
print(f"\nToronto mentions: {len(toronto_text)}")
for t in toronto_text[:3]:
    print(f"  {t.strip()[:100]}")

# Check for JSON data in script tags
scripts = soup.find_all("script", type="application/ld+json")
print(f"\nJSON-LD scripts: {len(scripts)}")
for s in scripts[:2]:
    print(f"  {str(s)[:200]}")

# Check for __NEXT_DATA__
next_data = soup.find("script", id="__NEXT_DATA__")
if next_data:
    print(f"\n__NEXT_DATA__ found: {len(str(next_data))} chars")
else:
    print(f"\n__NEXT_DATA__: not found")

# Look for listings in the HTML directly
raw_listings = re.findall(r'data-url="([^"]+)"', r.text)
print(f"\ndata-url attributes: {len(raw_listings)}")
for l in raw_listings[:5]:
    print(f"  {l[:80]}")
