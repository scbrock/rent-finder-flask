"""MC-246: Kijiji Toronto rental scraper — parses SSR HTML cards.

Working URL (apartment-for-rent subcategory, city of Toronto):
  https://www.kijiji.ca/b-apartments-condos/city-of-toronto/apartment-for-rent/k0c37l1700273
Returns 46 SSR cards per page; ~45 are actual rental listings.
Selector: <section data-testid="listing-card">
"""

import httpx
import re
from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import datetime, timezone

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# URL sub-paths that are NOT rentals
EXCLUDE_CATS = {
    "cars-trucks", "v-cars-trucks", "v-buy-sell-other",
    "v-furniture", "v-electronics", "v-sports", "v-books",
    "v-toys-games", "v-musical-instruments", "v-health-beauty",
    "v-clothing", "v-jewelry", "v-art-collectibles", "v-photography",
    "v-appliances", "v-renovation", "v-tools", "v-lawn-garden",
    "v-real-estate", "v-office", "v-storage", "v-moving",
    "v-bedding", "v-mattress", "v-free-stuff", "v-hobbies-craft",
    "v-painters-painting", "v-snowblower", "v-other-business",
    "v-deck-fence", "v-heavy-equipment", "v-financial-legal",
    "v-classes-lessons",
}

RENTAL_KW = [
    "apartment", "condo", "bedroom", "bedrooms",
    "suite", "unit", "den", "bachelor", "studio",
    "toronto", "north york", "scarborough", "etobicoke",
    "mississauga", "brampton", "gta", "midtown", "downtown",
    "lease", "for rent",
]

NON_RENTAL_TITLE = [
    "truck", "excavator", "boat", "trailer", "car", "vehicle",
    "financing", "lesson", "driving", "equipment", "machine",
    "call us", "rental car", "lease-to-own", "lease option",
]


@dataclass
class Listing:
    listing_id: str
    title: str
    price: float
    price_str: str
    location: str
    beds: str
    baths: str
    url: str
    image_url: str
    source: str = "kijiji"


def _is_rental_url(url: str) -> bool:
    if not url:
        return False
    url_l = url.lower()
    return not any(cat in url_l for cat in EXCLUDE_CATS)


def _is_rental_title(title: str) -> bool:
    if not title:
        return False
    t = title.lower()
    has_rental = any(kw in t for kw in RENTAL_KW)
    has_non_rental = any(
        re.search(r"\b" + re.escape(nr) + r"\b", t) is not None
        for nr in NON_RENTAL_TITLE
    )
    return has_rental and not has_non_rental


def parse_html_cards(html: str) -> list[Listing]:
    """Parse SSR listing cards from Kijiji HTML.

    Card structure (confirmed):
      <section data-testid="listing-card" data-listingid="...">
        <h3 data-testid="listing-title"> <a href="...">Title Text</a> </h3>
        <p data-testid="listing-price">  $2,500 /month  </p>
        <p data-testid="listing-location">  Address, Neighbourhood  </p>
        <img data-testid="listing-card-image" src="https://..." />
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("section", {"data-testid": "listing-card"})
    listings = []

    for card in cards:
        lst_id = card.get("data-listingid", "")

        # Title + URL
        title_el = card.find("h3", {"data-testid": "listing-title"})
        link_el = title_el.find("a") if title_el else None
        title = title_el.get_text(strip=True) if title_el else ""
        url = link_el.get("href", "") if link_el else ""
        if url and not url.startswith("http"):
            url = "https://www.kijiji.ca" + url

        # Filter by title (rental keywords, no non-rental)
        if not _is_rental_title(title):
            continue
        if not _is_rental_url(url):
            continue

        # Price
        price_el = card.find("p", {"data-testid": "listing-price"})
        price_text = price_el.get_text(strip=True) if price_el else ""
        price_val_str = re.sub(r"[^0-9.]", "", price_text)
        try:
            price_val = float(price_val_str) if price_val_str else 0.0
        except ValueError:
            price_val = 0.0

        # Price range: $200–$15,000/month
        if price_val < 200 or price_val > 15000:
            continue

        # Location
        loc_el = card.find("p", {"data-testid": "listing-location"})
        location = loc_el.get_text(strip=True) if loc_el else ""

        # Beds / baths from card text
        beds_m = re.search(r"(\d+)\s*(?:bed|bedroom|br)", card.get_text(), re.IGNORECASE)
        baths_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:bath|ba)", card.get_text(), re.IGNORECASE)
        beds = beds_m.group(0) if beds_m else ""
        baths = baths_m.group(0) if baths_m else ""

        # Image
        img_el = card.find("img", {"data-testid": "listing-card-image"})
        image_url = img_el.get("src", "") if img_el else ""

        listings.append(Listing(
            listing_id=str(lst_id),
            title=title,
            price=price_val,
            price_str=price_text,
            location=location,
            beds=beds,
            baths=baths,
            url=url,
            image_url=image_url,
        ))

    return listings


def scrape(
    base_url: str = (
        "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/"
        "apartment-for-rent/k0c37l1700273"
    ),
    pages: int = 5,
) -> list[Listing]:
    """Scrape Kijiji rental listings across multiple pages.

    Args:
        base_url: URL of the Kijiji apartment-for-rent listing page for city of Toronto.
                  Default is the apartment-for-rent subcategory which returns ~45 rental
                  cards per page (vs the general b-rentals page which is heavily
                  polluted with non-rental listings).
        pages: Number of pages to scrape.

    Returns:
        List of Listing dataclass objects.
    """
    all_listings = []
    seen = set()

    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
        # Initialize cookies (Kijiji may redirect first)
        c.get("https://www.kijiji.ca/")

        for page in range(1, pages + 1):
            url = f"{base_url}?page={page}"
            r = c.get(url)
            if r.status_code != 200:
                break

            page_listings = parse_html_cards(r.text)
            new = [l for l in page_listings if l.listing_id not in seen]
            seen.update(l.listing_id for l in new)
            all_listings.extend(new)

            if not page_listings:
                break

    return all_listings


if __name__ == "__main__":
    print("MC-246: Scraping Kijiji Toronto rentals...\n")
    results = scrape(pages=3)
    print(f"\nTotal: {len(results)} rental listings")
    print(f"Unique: {len(set(r.listing_id for r in results))}")
    for lst in results[:10]:
        print(f"\n  [{lst.listing_id}] {lst.price_str or 'N/A'} | {lst.beds or '?'}bd | {lst.location[:50]}")
        print(f"    {lst.title[:90]}")
        print(f"    {lst.url}")
