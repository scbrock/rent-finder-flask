import httpx, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}
c = httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True)
c.get("https://www.kijiji.ca/")

r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")
soup = BeautifulSoup(r.text, "html.parser")
cards = soup.find_all("section", {"data-testid": "listing-card"})
print(f"b-rentals page: {len(cards)} cards")

for card in cards:
    title_el = card.find("h3", {"data-testid": "listing-title"})
    a = title_el.find("a") if title_el else None
    url = a.get("href", "") if a else ""
    title = title_el.get_text(strip=True) if title_el else ""
    price_el = card.find("p", {"data-testid": "listing-price"})
    price = price_el.get_text(strip=True) if price_el else ""
    # Extract v-category from URL
    vcat_m = re.search(r'/v-([^/]+)/', url)
    vcat = vcat_m.group(1) if vcat_m else "?"
    print(f"{price:12} | v={vcat:30} | {title[:80]}")
    print(f"             | {url[:80]}")