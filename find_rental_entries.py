"""Inspect StandardListing entries for rental apartments."""

import httpx, re, json

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}
c = httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True)
c.get("https://www.kijiji.ca/")

r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")

nm = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
data = json.loads(nm.group(1))
apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]

# Look at ALL StandardListing entries
std_listings = [(k, v) for k, v in apollo.items() if k.startswith("StandardListing:")]

# Filter rental apartments — must have:
# 1. price between $200-$15,000 (rental range)
# 2. title has rental keywords (apartment, condo, bedroom, etc.)
# 3. NOT equipment, vehicles, services, etc.

print(f"Total StandardListing: {len(std_listings)}")
print("\n--- Looking for rental entries ---")
rental_entries = []

for k, v in std_listings:
    title = v.get("title", "")

    # Check price
    price_obj = v.get("price")
    price_val = 0
    if isinstance(price_obj, dict):
        amount = price_obj.get("amount")
        if amount:
            price_val = amount / 100  # Kijiji stores cents
    price_str = f"${price_val:.0f}" if price_val else ""

    # Rental keyword check
    rental_kw = ["apartment", "condo", "bedroom", "bedrooms", "bed ", "bath", "suite", "unit",
                 "toronto", "north york", "scarborough", "etobicoke", "mississauga", "gta",
                 "lease", "rent", "bachelor", "studio", "den", "furnished", "toronto"]

    has_rental = any(kw in title.lower() for kw in rental_kw)

    # Non-rental categories to exclude
    non_rental = ["truck", "excavator", "boat", "trailer", "car", "vehicle", "financing",
                  "lesson", "driving", "equipment", "machine", "financing", "legal",
                  "service", "repair", "rental car", "lease-to-own", "lease option",
                  "financing available", "call us"]

    is_non_rental = any(nr in title.lower() for nr in non_rental)

    # Must have price (rentals always have price)
    # Must be in rental price range
    # Must have rental keyword and not be non-rental category
    if price_val >= 200 and price_val <= 15000 and has_rental and not is_non_rental:
        print(f"\nRENTAL [{k}]:")
        print(f"  title: {title[:80]}")
        print(f"  price: {price_str}")
        print(f"  url: {v.get('url','')}")
        print(f"  categoryId: {v.get('categoryId')}")
        print(f"  description: {str(v.get('description',''))[:150]}")
        rental_entries.append((k, v))
    else:
        # Show first 3 non-rentals for reference
        if len(rental_entries) < 3:
            print(f"\nNON-RENTAL [{k}]:")
            print(f"  title: {title[:80]}")
            print(f"  price: {price_str}")