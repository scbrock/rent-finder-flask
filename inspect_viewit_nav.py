import httpx, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)

# Try pagination variations
pages = ['?page=2', '?pagenum=2', '?pg=2', '?page=2&sort=price&dir=asc']
for p in pages:
    url = 'https://www.viewit.ca/Listings' + p
    resp = client.get(url)
    html = resp.text
    featured = re.findall(r'featuredListing-name[^>]*>([^<]+)', html)
    print(f'{p}: status={resp.status_code}, len={len(html)}, featured={len(featured)}')

# Also try the explore-by-city navigation items
# Find links to Toronto neighbourhoods from main page
url = 'https://www.viewit.ca/Listings'
resp = client.get(url)
html = resp.text

# Find all links that look like city/area pages
links = re.findall(r'href="([^"]+)"', html)
city_links = [l for l in links if any(w in l.lower() for w in ['toronto', 'downtown', 'city', 'area', 'region', 'neighbourhood'])]
print(f'City links: {city_links[:10]}')

# Also look for the "Explore by city" section
explore = re.findall(r'Explore by city', html)
print(f'"Explore by city" found: {len(explore)}')

# Find the smart search result containers
smart_search = re.findall(r'smartSearch-Result-Container[^"]*"', html)
print(f'Smart search containers: {len(smart_search)}')

# Try to find any link patterns for city-specific listings
# Look for hrefs that contain viewit.ca + something
viewit_links = [l for l in links if 'viewit.ca' in l and l != 'https://www.viewit.ca/' and l != 'https://www.viewit.ca']
print(f'Viewit internal links: {viewit_links[:20]}')