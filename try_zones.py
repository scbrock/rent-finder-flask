"""MC-246: Final viewit.ca scraping approach — use the zone/city AJAX endpoints."""

import httpx, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json; charset=utf-8",
    "X-Requested-With": "XMLHttpRequest",
}

client = httpx.Client(timeout=30, follow_redirects=True)

# Step 1: Get CityID=14 (Toronto) zones
print("Step 1: Get Toronto zones...")
r = client.post(
    "https://www.viewit.ca/vwdefault.aspx/GetZoneGeocodes",
    content=json.dumps({"sPage": "toronto"}),
    headers=HEADERS,
)
print(f"GetZoneGeocodes: HTTP {r.status_code}")
print(f"Response: {r.text[:1000]}")

# Step 2: Try GetListingsSmartSearch with full Toronto area
print("\nStep 2: Get listings by search criteria...")
searches = [
    "Toronto, Ontario",
    "Scarborough, Toronto",
    "Downtown Toronto",
    "North York, Toronto",
    "Etobicoke, Toronto",
    "M5V",
    "M6E",
    "M4C",
    "L5V",
]
for search in searches:
    r = client.post(
        "https://www.viewit.ca/vwdefault.aspx/GetListingsSmartSearch",
        content=json.dumps({"sSearch": search}),
        headers=HEADERS,
    )
    if r.status_code == 200:
        d = r.json()
        xml_str = d.get("d", "")
        # Extract CityID if found
        city_match = re.search(r'<CityID>(\d+)</CityID>\s*<ProvinceCode>(\w+)</ProvinceCode>\s*<CityName>([^<]+)</CityName>', xml_str)
        listing_count = xml_str.count("<Listing")
        print(f"  Search '{search}': city_match={city_match.group(0)[:50] if city_match else 'None'}, listing_blocks={listing_count}")
        if listing_count > 0:
            print(f"  XML sample: {xml_str[:500]}")
            break