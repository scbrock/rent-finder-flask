import httpx, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
}

client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)

# Try the Toronto specific viewit URL
urls_to_try = [
    'https://www.viewit.ca/Listings?sort=price&dir=asc&page=1',
    'https://www.viewit.ca/metrotoronto',
    'https://www.viewit.ca/toronto',
    'https://www.viewit.ca/dtownto',
]

for url in urls_to_try:
    resp = client.get(url)
    print(f'\n=== {url} ===')
    print(f'Status: {resp.status_code}')
    html = resp.text
    
    # Check featured listings
    featured = re.findall(r'featuredListing-name[^>]*>([^<]+)', html)
    prices = re.findall(r'featuredListing-price[^>]*>([^<]+)', html)
    print(f'Featured names: {featured[:5]}')
    print(f'Featured prices: {prices[:5]}')
    
    # Look for VTourID or other listing identifiers
    vtour = re.findall(r'VTourID=([A-Za-z0-9_-]+)', html)
    print(f'VTourIDs: {vtour[:3]}')
    
    # Check for any JSON data embedded
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    json_data = []
    for s in scripts:
        try:
            d = json.loads(s.strip())
            json_data.append(type(d).__name__)
        except:
            pass
    print(f'Script JSON blocks: {len(json_data)}')
    
    # Find smart search containers
    smart = re.findall(r'smartSearch-Result-Container[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
    print(f'Smart search containers: {len(smart)}')
    if smart:
        print('First smart search sample:', smart[0][:200])
    
    # Check for listing links
    listing_links = re.findall(r'href="(/vtor/[^"]+)"', html)
    print(f'Listing links: {len(listing_links)}, sample: {listing_links[:3]}')