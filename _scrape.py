"""MC-246: Kijiji Toronto rental scraper — inline execution."""

import httpx, re
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

RENTAL_KW = [
    "apartment", "condo", "bedroom", "bedrooms", "bed", "bath",
    "suite", "unit", "den", "bachelor", "studio",
    "toronto", "north york", "scarborough", "etobicoke", "mississauga",
    "brampton", "oakville", "burlington", "hamilton", "gta", "midtown",
    "downtown", "for rent",
]
NON_RENTAL = [
    "truck", "excavator", "boat", "trailer", "car ", "vehicle", "financing",
    "lesson", "driving", "equipment", "machine", "call us", "rental car",
    "lease-to-own", "lease option", "financing available",
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
    "v-powerboat", "v-heavy-trucks",
}

def is_rental(title, url):
    t = title.lower()
    u = url.lower()
    if any(cat in u for cat in EXCLUDE_CATS):
        return False
    if any(nr in t for nr in NON_RENTAL):
        return False
    return any(kw in t for kw in RENTAL_KW)

def parse_price(text):
    digits = re.sub(r'[^0-9.]', '', text)
    try:
        return float(digits), text.strip()
    except ValueError:
        return 0.0, text.strip()

# Use the apartment-for-rent subcategory URL (subagent found this works)
BASE_URL = "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/apartment-for-rent/k0c37l1700273"

results = []
with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
    c.get("https://www.kijiji.ca/")
    for page in range(1, 6):
        url = f"{BASE_URL}&page={page}"
        r = c.get(url)
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.find_all("section", {"data-testid": "listing-card"})
        if not cards:
            break
        for card in cards:
            lst_id = card.get("data-listingid", "")
            title_el = card.find("h3", {"data-testid": "listing-title"})
            link_el = title_el.find("a") if title_el else None
            title = title_el.get_text(strip=True) if title_el else ""
            url_path = link_el.get("href", "") if link_el else ""
            if url_path and not url_path.startswith("http"):
                url_path = "https://www.kijiji.ca" + url_path
            if not is_rental(title, url_path):
                continue
            price_el = card.find("p", {"data-testid": "listing-price"})
            price_text = price_el.get_text(strip=True) if price_el else ""
            price_val, _ = parse_price(price_text)
            if price_val < 200 or price_val > 15000:
                continue
            loc_el = card.find("p", {"data-testid": "listing-location"})
            location = loc_el.get_text(strip=True) if loc_el else ""
            card_text = card.get_text()
            beds_m = re.search(r'(\d+)\s*(?:bed|bedroom|br)', card_text, re.IGNORECASE)
            baths_m = re.search(r'(\d+(?:\.\d+)?)\s*(?:bath|ba)', card_text, re.IGNORECASE)
            beds = beds_m.group(0) if beds_m else ""
            baths = baths_m.group(0) if baths_m else ""
            img_el = card.find("img", {"data-testid": "listing-card-image"})
            image_url = img_el.get("src", "") if img_el else ""
            results.append({
                "listing_id": lst_id,
                "title": title,
                "price": price_val,
                "price_str": price_text,
                "location": location,
                "beds": beds,
                "baths": baths,
                "url": url_path,
                "image_url": image_url,
            })
            print(f"  {price_text} | {beds or '?'}bd | {location[:40]}")
        print(f"Page {page}: {len([c for c in cards if is_rental(c.find('h3',{'data-testid':'listing-title'}).get_text(strip=True) if c.find('h3',{'data-testid':'listing-title'}) else '','']))} rental listings")
        print(f"  Total so far: {len(results)}")

print(f"\nTotal rental listings scraped: {len(results)}")
