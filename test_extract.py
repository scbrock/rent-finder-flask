import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from scraper import extract_listings_from_page

page_path = os.path.join(os.path.dirname(__file__), "kijiji_page.html")
with open(page_path, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

listings = extract_listings_from_page(content)
print(f'Extracted: {len(listings)}')
for l in listings[:10]:
    print(f'  price={l["price"]} beds={l["beds"]} neighborhood={l["neighborhood"]} title={l["title"][:50]}')
    print(f'    url={l["url"]}')