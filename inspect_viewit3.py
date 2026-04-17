import requests, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# Try Viewit listings endpoint
urls = [
    "https://www.viewit.ca/Listings?near=3&city=Toronto",
    "https://www.viewit.ca/FeaturedListings.aspx",
    "https://www.viewit.ca/ListingsBrowser.aspx",
]

for url in urls:
    r = requests.get(url, headers=HEADERS, timeout=15)
    print(f"\n=== {url[:70]} ===")
    print(f"HTTP {r.status_code}, len={len(r.text)}")

    # Look for data attributes with listing info
    data_attrs = re.findall(r'data-[a-z]+=["\']([^"\']{30,})["\']', r.text)
    if data_attrs:
        print(f"Data attrs: {data_attrs[:3]}")

    # Look for listing URLs
    links = re.findall(r'href="(/[A-Za-z0-9/?=&]+)"', r.text)
    unique_links = sorted(set(links))
    print(f"Links (first 15): {unique_links[:15]}")

    # Look for price patterns
    prices = re.findall(r'\$[\d,]+', r.text)
    print(f"Prices (first 10): {prices[:10]}")

    # Try to find embedded JSON
    json_data = re.findall(r'\{[^{}]{100,}\}', r.text)
    print(f"JSON-like blocks: {json_data[:2]}")