"""Inspect rentalrehabs.com page for rental listing structure."""

import httpx, re
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

r = httpx.get("https://www.rentalrehabs.com/listings?city=Toronto", headers=HEADERS, timeout=20)
print(f"HTTP {r.status_code}, size={len(r.text)}")
print(f"Content-type: {r.headers.get('content-type','?')}")

soup = BeautifulSoup(r.text, "html.parser")

# Check page title
title = soup.select_one("title")
print(f"Title: {title.get_text(strip=True) if title else 'N/A'}")

# Look for listing containers
for sel in ["[class*='listing']", "[class*='card']", "[class*='property']", "[data-listing]", "article"]:
    els = soup.select(sel)
    if els:
        print(f"Selector '{sel}': {len(els)} elements")
        if els:
            print(f"  First: {els[0].prettify()[:500]}")

# Check for price in structured data
prices = re.findall(r'\$[\d,]+', r.text)
print(f"\nUnique prices found: {sorted(set(prices))[:20]}")

# Look for addresses
addresses = re.findall(r'[A-Z][a-zA-Z ]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Terrace|Ter|Boulevard|Blvd)[,.]?\s*[A-Z][a-z]+,?\s*[A-Z]{2}', r.text)
print(f"Address-like patterns: {addresses[:10]}")

# Check for JSON data
for script in soup.find_all("script"):
    if script.string and len(script.string) > 500:
        # Check if it contains listing data
        if "listing" in script.string.lower() and ("price" in script.string.lower() or "$" in script.string):
            print(f"\nScript with listing data ({len(script.string)} chars):")
            print(script.string[:500])