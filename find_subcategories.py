"""Find correct category IDs for rental subcategories."""

import httpx, re, json

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}
c = httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True)
c.get("https://www.kijiji.ca/")

# Get the apartment category page to find subcategory links
r = c.get("https://www.kijiji.ca/b-apartments-condos/city-of-toronto/l1700273")

# Look for subcategory links in the page
# Kijiji uses URL pattern like /b-apartments-condos/city-of-toronto/c{categoryId}l{locationId}
subcat_links = re.findall(r'href="(/b-apartments-condos/city-of-toronto/c\d+[^"]*)"', r.text)
print(f"Subcategory links: {sorted(set(subcat_links))[:20]}")

# Also find rental-specific subcategories
rental_subs = re.findall(r'href="(/b-rentals/city-of-toronto/c\d+[^"]*)"', r.text)
print(f"\nRental subcategory links: {sorted(set(rental_subs))[:20]}")

# Try to find the specific category number for "Apartments & Condos for Rent"
# by looking at the category tree
category_pages = re.findall(r'href="(/b-apartments-condos/[^"]+)"', r.text)
print(f"\nAll apartment links: {sorted(set(category_pages))[:20]}")