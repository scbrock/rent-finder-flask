import sys
import os

# scraper.py is in rent_finder/
parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
scraper_path = os.path.join(parent, "rent_finder", "scraper.py")
page_path = os.path.join(parent, "rent_finder", "kijiji_page.html")
print(f"Loading: {scraper_path}")
print(f"Page: {page_path}")

import importlib.util
spec = importlib.util.spec_from_file_location("scraper", scraper_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

with open(page_path, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

listings = mod.extract_listings_from_page(content)
print(f'Extracted: {len(listings)}')
for l in listings[:10]:
    print(f'  price={l["price"]} beds={l["beds"]} neighborhood={l["neighborhood"]}')
    print(f'  title={l["title"][:60]}')
    print(f'  url={l["url"]}')