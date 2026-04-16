import httpx, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}
c = httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True)
c.get("https://www.kijiji.ca/")
r = c.get("https://www.kijiji.ca/b-apartments-condos/city-of-toronto/page-1/l1700273")

soup = BeautifulSoup(r.text, "html.parser")
cards = soup.find_all("section", {"data-testid": "listing-card"})
print(f"Cards: {len(cards)}")

for card in cards:
    title_el = card.find("h3", {"data-testid": "listing-title"})
    title = title_el.get_text(strip=True) if title_el else ""
    url = ""
    if title_el:
        a = title_el.find("a")
        if a:
            url = a.get("href", "")
    price_el = card.find("p", {"data-testid": "listing-price"})
    price = price_el.get_text(strip=True) if price_el else ""
    print(repr(price))
    print(f"  title: {title[:80]}")
    print(f"  url: {url[:80]}")