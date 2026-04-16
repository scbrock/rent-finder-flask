"""Parse Kijiji listing cards using BeautifulSoup."""

import httpx, re
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}


def parse_cards(html: str):
    soup = BeautifulSoup(html, "html.parser")

    # Find all listing card sections
    cards = soup.find_all("section", {"data-testid": "listing-card"})
    print(f"Found {len(cards)} listing cards")

    for i, card in enumerate(cards[:3]):
        print(f"\n=== Card {i} ===")
        # Listing ID
        listing_id = card.get("data-listingid", "")
        print(f"ID: {listing_id}")

        # Title
        title_el = card.find("h3", {"data-testid": "listing-title"})
        if title_el:
            title = title_el.get_text(strip=True)
            link = title_el.find("a")
            url = link.get("href", "") if link else ""
            print(f"Title: {title[:80]}")
            print(f"URL: {url}")

        # Price
        price_el = card.find("p", {"data-testid": "listing-price"})
        if price_el:
            price = price_el.get_text(strip=True)
            print(f"Price: {price}")

        # Location
        loc_el = card.find("p", {"data-testid": "listing-location"})
        if loc_el:
            loc = loc_el.get_text(strip=True)
            print(f"Location: {loc[:80]}")

        # Beds - look for any text with bedroom
        card_text = card.get_text()
        beds_m = re.search(r'(\d+)\s*(?:bed|bedroom|br)', card_text, re.IGNORECASE)
        if beds_m:
            print(f"Beds: {beds_m.group(0)}")

        # Image
        img = card.find("img", {"data-testid": "listing-card-image"})
        if img:
            print(f"Image: {img.get('src', '')[:80]}")


with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
    c.get("https://www.kijiji.ca/")
    r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")

parse_cards(r.text)