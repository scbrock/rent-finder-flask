"""Fix: show all card titles + decisions + count how many pass."""

import httpx, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}

RENTAL_KW = ["apartment", "condo", "bedroom", "bedrooms", "bed ", "bath", "suite", "unit",
             "den", "bachelor", "studio", "toronto", "north york", "scarborough",
             "etobicoke", "mississauga", "brampton", "oakville", "burlington", "hamilton",
             "gta", "midtown", "downtown", "lease", "for rent"]
NON_RENTAL = ["truck", "excavator", "boat", "trailer", "car", "vehicle", "financing",
              "lesson", "driving", "equipment", "machine", "call us", "rental car",
              "lease-to-own", "lease option"]
EXCLUDE_CATS = {"cars-trucks", "v-cars-trucks", "v-buy-sell-other", "v-speakers",
                "v-furniture", "v-electronics", "v-baby-kids", "v-sports", "v-books",
                "v-toys-games", "v-musical-instruments", "v-health-beauty", "v-clothing",
                "v-jewelry", "v-art-collectibles", "v-photography", "v-appliances",
                "v-renovation", "v-tools", "v-lawn-garden", "buy-sell", "boats",
                "motorcycles", "RVs", "commercial", "jobs", "services", "v-real-estate",
                "v-office", "v-storage", "v-moving", "pet-supplies", "v-bedding",
                "v-mattress", "v-free-stuff", "v-hobbies-craft", "v-painters-painting",
                "v-snowblower", "v-non-fiction", "v-other-business", "v-deck-fence",
                "v-heavy-equipment", "v-financial-legal", "v-classes-lessons",
                "v-powerboat", "v-heavy-trucks", "v-refrigerator-fridge",
                "v-microwave-cooker", "v-video-tv-accessories", "v-brick-masonry-concrete",
                "v-general-labour-jobs", "v-bar-food-hospitality-jobs"}

with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
    c.get("https://www.kijiji.ca/")
    r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")

soup = BeautifulSoup(r.text, "html.parser")
cards = soup.find_all("section", {"data-testid": "listing-card"})
print(f"Total cards: {len(cards)}\n")

passes = []
for card in cards:
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
    has_non_rental = any(nr in title.lower() for nr in NON_RENTAL)
    has_exclude = any(cat in url.lower() for cat in EXCLUDE_CATS)
    ok = has_rental and not has_non_rental and not has_exclude and price_text

    if ok:
        passes.append((lst_id, title, price_text, url))

print(f"PASS (rental listings): {len(passes)}\n")
for lst_id, title, price, url in passes:
    print(f"  {price} | {title[:80]}")
    print(f"    {url}")
    print()

# Also check: what's the category breakdown of all 46 cards?
print("\n--- Category breakdown ---")
from collections import Counter
cats = []
for card in cards:
    link_el = card.find("h3", {"data-testid": "listing-title"})
    if link_el:
        a = link_el.find("a")
        if a:
            href = a.get("href", "")
            parts = [p for p in href.split("/") if p]
            if len(parts) >= 2:
                cats.append(parts[1] if parts[0] == "v" else parts[0])

cat_count = Counter(cats)
for cat, cnt in cat_count.most_common(15):
    print(f"  {cat}: {cnt}")