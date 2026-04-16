"""MC-246: Parse viewit.ca listing grid from raw HTML."""

import re

with open("viewit_listings.html", "r", encoding="utf-8") as f:
    html = f.read()

print(f"HTML size: {len(html)}")

# Look for GridView table
trs = re.findall(r'<tr[^>]*class="[^"]*GridView[^"]*"[^>]*>.*?</tr>', html, re.DOTALL)
print(f"GridView TRs: {len(trs)}")

# Try table rows
trs2 = re.findall(r'<tr[^>]*>.*?</tr>', html[:50000])
print(f"All TRs (first 50k): {len(trs2)}")

# Look for specific listing IDs pattern from GridView
# GridView rows in ASP.NET have class like "GridViewRow" or "GridViewAlternatingRow"
gv_rows = re.findall(r'class="([^"]*Row[^"]*)"', html)
unique_classes = set(re.findall(r'class="([^"]*[Gg]rid[Vv]iew[^"]*)"', html))
print(f"GridView classes: {unique_classes}")

# Find all elements with numeric IDs in the 5-digit range (listing IDs)
# Look for IDs like 26056 in img src or anchor href
listing_img_pattern = r'images\.viewit\.ca/(\d+)/\S+\.jpg'
img_ids = re.findall(listing_img_pattern, html)
print(f"Listing IDs from image URLs: {len(img_ids)} unique: {len(set(img_ids))} -> {sorted(set(img_ids))[:20]}")

# Anchor hrefs with listing IDs
href_ids = re.findall(r'href="[^"]*/(\d{4,6})"', html)
print(f"Listing IDs from hrefs: {len(href_ids)} unique: {len(set(href_ids))} -> {sorted(set(href_ids))[:20]}")

# Check for a specific known listing in the HTML
known_id = "26056"
pos = html.find(known_id)
if pos > 0:
    snippet = html[pos-200:pos+500]
    print(f"\nContext around {known_id}:")
    print(snippet)