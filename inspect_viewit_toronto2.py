import httpx, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://www.viewit.ca/',
}

client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)

url = 'https://www.viewit.ca/rentals/toronto'
resp = client.get(url)
html = resp.text
print(f'Status: {resp.status_code}, Length: {len(html)}')

# Find ALL links (including full URLs) that look like listing pages
# Format: /address-Toronto-Nbdrm-VIT=XXXX
all_links = re.findall(r'href="([^"]+)"', html)
listing_links = [l for l in all_links if 'VIT=' in l]
print(f'Listing links (VIT=): {len(listing_links)}')
print(f'Sample: {listing_links[:10]}')

# Check featured listings
featured = re.findall(r'featuredListing-name[^>]*>([^<]+)', html)
featured_prices = re.findall(r'featuredListing-price[^>]*>([^<]+)', html)
featured_links = re.findall(r'featuredListing[^>]*>.*?href="([^"]+)"', html, re.DOTALL)
print(f'\nFeatured listings: {len(featured)}')
for name, price, link in zip(featured[:10], featured_prices[:10], featured_links[:10]):
    print(f'  {name}: {price} -> {link}')

# Look for the neighbourhood/city dropdown to see if there's a Toronto-specific page
# Look for search/filter controls
search_ctrls = re.findall(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', html, re.DOTALL)
print(f'\nSelect controls: {len(search_ctrls)}')
for name, options in search_ctrls:
    opts = re.findall(r'<option[^>]*value="([^"]+)"[^>]*>([^<]+)</option>', options)
    print(f'  {name}: {len(opts)} options')
    for val, label in opts[:5]:
        print(f'    {val} = {label}')

# Look for any hidden fields with city codes
hidden = re.findall(r'<input[^>]+type="hidden"[^>]*>', html)
for h in hidden[:10]:
    name_m = re.search(r'name="([^"]+)"', h)
    val_m = re.search(r'value="([^"]+)"', h)
    if name_m:
        print(f'Hidden: {name_m.group(1)} = {val_m.group(1) if val_m else "N/A"}')

# Look for any city/district specific listings
print('\nLooking for city/area specific URLs:')
area_links = [l for l in all_links if any(w in l.lower() for w in ['downtown', 'king west', 'queen west', 'liberty', 'distillery', 'harbour', 'yorkville'])]
print(f'Area-specific links: {area_links[:10]}')