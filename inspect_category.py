"""Inspect the All Categories page to find the correct rental category URL."""

import httpx, re

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}
c = httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)
c.get("https://www.kijiji.ca/")

r = c.get("https://www.kijiji.ca/b-apartments-condos/city-of-toronto/l1700273")

# Look for the category tree navigation
# Kijiji category pages typically have category cards with URLs
category_links = re.findall(r'href="(/b-apartments-condos/[^"?]+)"', r.text)
print(f"Category links: {sorted(set(category_links))[:20]}")

# Also check if there's a "For Rent" section in the page
for_rent_links = re.findall(r'For Rent[^<]{0,50}href="([^"]+)"', r.text)
print(f"For Rent section links: {for_rent_links[:10]}")

# Try to find the specific category number for Toronto rentals
# Check for region/city codes
city_links = re.findall(r'href="(/b-apartments-condos/[^"]*toronto[^"]*)"', r.text)
print(f"Toronto apartment links: {city_links[:10]}")

# Find links with location codes (l1700273 pattern)
location_links = re.findall(r'href="(/b-apartments-condos[^"]*l1700\d+)"', r.text)
print(f"Location-coded links: {location_links[:10]}")

# Look for the main category number for "rentals"
main_cat = re.findall(r'href="(/b-rentals[^"]+)"', r.text)
print(f"Main rentals links: {main_cat[:5]}")

# Find any link that has a numeric category code
cat_patterns = re.findall(r'href="(/b-[^/]+/\S+?/l\d+)"', r.text)
print(f"All category links: {sorted(set(cat_patterns))[:20]}")

# Save the HTML for manual inspection
with open("kijiji_category.html", "w", encoding="utf-8") as f:
    f.write(r.text)
print(f"\nSaved {len(r.text)} chars to kijiji_category.html")