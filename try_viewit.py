"""MC-246: Try direct scraping approach for viewit.ca."""

import httpx, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

# Try different listing endpoints
urls = [
    ("Listings plain", "https://www.viewit.ca/Listings", None),
    ("Listings sort", "https://www.viewit.ca/Listings?sort=price&dir=asc", None),
    ("ViewAll", "https://www.viewit.ca/Listing/ViewAll.aspx", None),
    # Try the city page for Toronto
    ("City page", "https://www.viewit.ca/torontozones?CID=14", None),
]

for name, url, _ in urls:
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        resp = client.get(url)
        print(f"{name}: HTTP {resp.status_code}, size={len(resp.text)}")
        # Check what's in the HTML
        print(f"  Has GridView: {'GridView' in resp.text}")
        print(f"  Has listings div: {'hero-featured' in resp.text}")
        print(f"  Has smartSearch: {'SmartSearch' in resp.text}")
        print(f"  Has $ amounts: {len(re.findall(r'\$[\d,]+', resp.text))} unique")
        print(f"  Has listing IDs: {len(re.findall(r'images\.viewit\.ca/(\d+)/', resp.text))} img IDs")
        # Check for any repeater/grid data
        print(f"  __doPostBack: {len(re.findall(r'__doPostBack', resp.text))} occurrences")
        print()