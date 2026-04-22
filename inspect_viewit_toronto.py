import httpx, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://www.viewit.ca/',
}

client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)

# Try rentals/toronto
url = 'https://www.viewit.ca/rentals/toronto'
resp = client.get(url)
html = resp.text
print(f'Status: {resp.status_code}, Length: {len(html)}')

# Check featured listings
featured = re.findall(r'featuredListing-name[^>]*>([^<]+)', html)
featured_prices = re.findall(r'featuredListing-price[^>]*>([^<]+)', html)
print(f'Featured listings: {len(featured)}')
for name, price in zip(featured[:5], featured_prices[:5]):
    print(f'  {name}: {price}')

# All prices
all_prices = re.findall(r'\$[\d,]+', html)
price_vals = sorted(set(int(re.sub(r'[^\d]', '', p)) for p in all_prices if re.sub(r'[^\d]', '', p).isdigit() and int(re.sub(r'[^\d]', '', p)) > 100))
print(f'All unique prices >100: {price_vals[:30]}')

# Check for other listing containers
# Look for any listing row/grid patterns
listing_rows = re.findall(r'class="[^"]*listing[^"]*"', html, re.IGNORECASE)
print(f'Listing class occurrences: {len(listing_rows)}')

# Check for any grid/result patterns
result_patterns = re.findall(r'class="[^"]*(?:result|grid|item|card)[^"]*"', html, re.IGNORECASE)
print(f'Result/grid patterns: {result_patterns[:10]}')

# Look for all hrefs to listing pages
listing_links = re.findall(r'href="(/[A-Za-z0-9_-]+/[^"]*)"', html)
listing_links = [l for l in listing_links if 'viewit.ca' not in l and len(l) < 80]
print(f'Listing links: {len(listing_links)}')
print(f'Sample: {listing_links[:10]}')

# Look for any address patterns
addresses = re.findall(r'class="[^"]*address[^"]*"[^>]*>([^<]+)', html, re.IGNORECASE)
print(f'Addresses: {addresses[:10]}')

# Check for JS-rendered content (look for any script data)
# Find all links from rentals/toronto nav
links = re.findall(r'href="([^"]+)"', html)
toronto_links = [l for l in links if 'toronto' in l.lower() or '/rentals/' in l]
print(f'Toronto-related links: {toronto_links[:10]}')