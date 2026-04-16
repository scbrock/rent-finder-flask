"""Debug: inspect Kijiji page structure."""

import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

url = "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/l1700273"
resp = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
print(f"HTTP {resp.status_code}, size={len(resp.text)}")

soup = BeautifulSoup(resp.text, "html.parser")
cards = soup.select("li.search-item")
print(f"search-item cards: {len(cards)}")

if cards:
    # Print first card's HTML
    print("\nFirst card HTML (first 2000 chars):")
    print(cards[0].prettify()[:2000])
else:
    # Try other selectors
    print("\nTrying other selectors...")
    for sel in ["[data-testid='listing-card']", ".listing-item", "article"]:
        els = soup.select(sel)
        print(f"  '{sel}': {len(els)} found")
    # Save HTML for inspection
    with open("kijiji_page.html", "w", encoding="utf-8") as f:
        f.write(resp.text)
    print("Saved to kijiji_page.html")