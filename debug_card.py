import httpx
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}
c = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)
c.get("https://www.kijiji.ca/")
r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")

soup = BeautifulSoup(r.text, "html.parser")
cards = soup.find_all("section", {"data-testid": "listing-card"})
print(f"Cards: {len(cards)}")

card = cards[0]
print(f"Card class: {card.get('class')}")
print(f"Card data-listingid: {card.get('data-listingid')}")

# Price element
price_el = card.find("p", {"data-testid": "listing-price"})
print(f"\nprice_el: {price_el}")
if price_el:
    txt = price_el.get_text(strip=True)
    print(f"  text: {repr(txt)}")
    print(f"  HTML: {str(price_el)[:200]}")
else:
    all_p = card.find_all("p")
    print(f"All p tags: {len(all_p)}")
    for p in all_p[:5]:
        dt = p.get("data-testid", "")
        text = p.get_text(strip=True)[:60]
        print(f"  p data-testid={repr(dt)} text={repr(text)}")

# Title
title_el = card.find("h3", {"data-testid": "listing-title"})
print(f"\ntitle_el: {title_el}")
if title_el:
    a = title_el.find("a")
    print(f"  a: {a}")
    if a:
        print(f"  href: {a.get('href')}")
        print(f"  text: {title_el.get_text(strip=True)[:60]}")