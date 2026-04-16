"""Debug: show all card titles and filter decisions."""

import httpx, re
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

RENTAL_KW = [
    "apartment", "condo", "bedroom", "bedrooms", "bed ", "bath",
    "suite", "unit", "den", "bachelor", "studio",
    "toronto", "north york", "scarborough", "etobicoke", "mississauga",
    "brampton", "oakville", "burlington", "hamilton", "gta", "midtown",
    "downtown", "lease", "for rent",
]
NON_RENTAL_TITLE = [
    "truck", "excavator", "boat", "trailer", "car", "vehicle", "financing",
    "lesson", "driving", "equipment", "machine", "financing available",
    "call us", "rental car", "lease-to-own", "lease option",
]
EXCLUDE_CATS = {
    "cars-trucks", "v-cars-trucks", "v-buy-sell-other", "v-speakers",
    "v-furniture", "v-electronics", "v-baby-kids", "v-sports", "v-books",
    "v-toys-games", "v-musical-instruments", "v-health-beauty", "v-clothing",
    "v-jewelry", "v-art-collectibles", "v-photography", "v-appliances",
    "v-renovation", "v-tools", "v-lawn-garden", "buy-sell", "boats",
    "motorcycles", "RVs", "commercial", "jobs", "services", "v-real-estate",
    "v-office", "v-storage", "v-moving", "pet-supplies", "v-bedding",
    "v-mattress", "v-free-stuff", "v-hobbies-craft", "v-painters-painting",
    "v-snowblower", "v-non-fiction", "v-other-business", "v-deck-fence",
    "v-heavy-equipment", "v-financial-legal", "v-classes-lessons",
    "v-powerboat",
}

with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
    c.get("https://www.kijiji.ca/")
    r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")

soup = BeautifulSoup(r.text, "html.parser")
cards = soup.find_all("section", {"data-testid": "listing-card"})
print(f"Total cards on page: {len(cards)}\n")

for i, card in enumerate(cards[:20]):
    lst_id = card.get("data-listingid", "")
    title_el = card.find("h3", {"data-testid": "listing-title"})
    link_el = title_el.find("a") if title_el else None
    title = title_el.get_text(strip=True) if title_el else ""
    url = link_el.get("href", "") if link_el else ""
    if url and not url.startswith("http"):
        url = "https://www.kijiji.ca" + url

    price_el = card.find("p", {"data-testid": "listing-price"})
    price_text = price_el.get_text(strip=True) if price_el else ""

    has_rental = any(kw in title.lower() for kw in RENTAL_KW)
    has_non_rental = any(nr in title.lower() for nr in NON_RENTAL_TITLE)
    has_exclude = any(cat in url.lower() for cat in EXCLUDE_CATS)

    passes = has_rental and not has_non_rental and not has_exclude

    print(f"[{i}] {'PASS' if passes else 'FAIL'} | {price_text or 'N/A':>12} | {lst_id}")
    print(f"     title: {title[:80]}")
    print(f"     url: {url[:80]}")
    print(f"     has_rental={has_rental}, has_non_rental={has_non_rental}, has_exclude={has_exclude}")
    print()