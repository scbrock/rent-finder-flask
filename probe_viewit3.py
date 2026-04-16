"""MC-246: Save viewit.ca listings HTML and extract listing structure."""

import requests, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

resp = requests.get("https://www.viewit.ca/Listings?sort=price&dir=asc", headers=HEADERS, timeout=20)
with open("viewit_listings.html", "w", encoding="utf-8") as f:
    f.write(resp.text)
print(f"Saved {len(resp.text)} chars")

# Extract all links that go to individual listing pages
listing_links = re.findall(r'href="([^"]*(?:Listing|listing)[^"]*)"', resp.text)
print(f"Listing links: {len(set(listing_links))}")
for l in list(set(listing_links))[:10]:
    print(f"  {l}")

# Look for address patterns
addresses = re.findall(r'(?:address|location|street|ave|road|dr|tower)[^<\n]{0,80}', resp.text, re.IGNORECASE)
print(f"\nAddress-like lines: {len(addresses)}")
for a in addresses[:5]:
    print(f"  {a.strip()[:100]}")

# Look for div/span with listing data
print("\n--- Looking for listing items ---")
# Try to find all <tr> or <div> with numeric IDs (listing IDs)
ids = re.findall(r'id=["\']?(\d{6,})', resp.text)
print(f"Large numeric IDs: {len(ids)} → {set(ids)}")

# Look for bed/bath patterns
bed_bath = re.findall(r'(\d+)\s*(bed|bedroom|br|ba|bath)', resp.text, re.IGNORECASE)
print(f"\nBed/bath mentions: {len(bed_bath)}")
for m in bed_bath[:10]:
    print(f"  '{m[0]} {m[1]}'")

# Check the script data for listings
scripts = re.findall(r'<script[^>]*>(.*?)</script>', resp.text, re.DOTALL)
for i, s in enumerate(scripts):
    if len(s.strip()) > 100:
        print(f"\nScript {i} ({len(s)} chars): {s[:300]}")