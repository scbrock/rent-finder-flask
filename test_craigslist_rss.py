import requests
import xml.etree.ElementTree as ET
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}

# Try Craigslist RSS for Toronto downtown rentals
# Filter: 1-2BR, max $3500, downtown neighborhoods
urls = [
    "https://toronto.craigslist.org/search/apa?bedrooms=1&max_price=3500&neighborhoods=Downtown+Toronto&availabilityMode=0&sale_date=all+dates&format=rss",
    "https://toronto.craigslist.org/search/apa?bedrooms=2&max_price=4000&neighborhoods=Downtown+Toronto&availabilityMode=0&sale_date=all+dates&format=rss",
]

all_listings = []

for url in urls:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        print(f"URL: {url[:80]}")
        print(f"  HTTP {r.status_code}, Type: {r.headers.get('Content-Type','')[:60]}, Len: {len(r.text)}")
        if r.status_code == 200 and len(r.text) > 200:
            # Parse RSS XML
            try:
                root = ET.fromstring(r.text)
                channel = root.find("channel")
                if channel is not None:
                    items = channel.findall("item")
                    print(f"  Items in feed: {len(items)}")
                    for item in items[:3]:
                        title = item.findtext("title", "")
                        link = item.findtext("link", "")
                        desc = item.findtext("description", "")
                        print(f"  Title: {title[:60]}")
                        print(f"  Link: {link[:80]}")
                        print(f"  Desc: {desc[:120]}")
                        print()
                else:
                    print(f"  No channel found. Raw: {r.text[:300]}")
            except ET.ParseError as e:
                print(f"  XML parse error: {e}")
                print(f"  Raw: {r.text[:300]}")
        print()
    except Exception as e:
        print(f"  ERROR: {e}\n")
