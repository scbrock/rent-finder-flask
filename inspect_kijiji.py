"""Inspect Kijiji card classes to find rental vs other categories."""

from bs4 import BeautifulSoup

with open("kijiji_page.html", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")
cards = soup.select("[data-testid='listing-card']")
print(f"Total cards: {len(cards)}\n")

# Group by price range to distinguish rentals vs cars
for card in cards:
    price_el = card.select_one("[data-testid*='listing-price']")
    price_text = price_el.get_text(strip=True) if price_el else "NO_PRICE"
    title_el = card.select_one("[data-testid='listing-title']")
    title = title_el.get_text(strip=True)[:50] if title_el else "NO_TITLE"
    listing_id = card.get("data-listingid", "NO_ID")
    href = card.select_one("a[data-testid='listing-link']")
    url = href.get("href", "") if href else ""

    # Check if rental-specific attributes exist
    has_beds = bool(card.select_one("[data-testid*='bedroom']"))
    has_baths = bool(card.select_one("[data-testid*='bathroom']"))
    has_address = bool(card.select_one("[data-testid='listing-location']"))

    print(f"[{listing_id}] ${price_text} | beds={has_beds} baths={has_baths} addr={has_address} | {title} | {url[:60]}")