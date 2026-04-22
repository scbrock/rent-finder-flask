"""MC-290: Enhanced Craigslist listing extraction"""
import requests, re, json
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import scrape_craigslist as _cl

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Try additional Craigslist Toronto search URLs
test_urls = [
    "https://toronto.craigslist.org/d/apartments-housing-for-rent/search/apa",
    "https://toronto.craigslist.org/search/apa?query=toronto+apartment",
]

for url in test_urls:
    r = requests.get(url, headers=HEADERS, timeout=20)
    print(f"URL: {url}")
    print(f"  Status: {r.status_code}, Size: {len(r.text)}")
    # Count listing cards
    cards = re.findall(r'class="cl-static-search-result"', r.text)
    print(f"  Listing cards: {len(cards)}")
    prices = re.findall(r'\$(\d{3,5})', r.text)
    print(f"  Prices found: {len(prices)}")
    if prices:
        print(f"  Sample prices: {sorted(set(prices))[:5]}")