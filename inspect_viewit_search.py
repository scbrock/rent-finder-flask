import httpx, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://www.viewit.ca/',
}

client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)

urls_to_try = [
    'https://www.viewit.ca/searchresults.aspx?search=apartment&location=Toronto&pricefrom=0&priceto=3500',
    'https://www.viewit.ca/PreferredDirectories/PTRental/Results.aspx',
    'https://www.viewit.ca/preferreddirectories.aspx',
    'https://www.viewit.ca/Listings?page=1',
]

for url in urls_to_try:
    try:
        resp = client.get(url)
        html = resp.text
        print(f'\n=== {url[:80]} ===')
        print(f'Status: {resp.status_code}, Length: {len(html)}')
        
        # Check featured listings count
        featured = re.findall(r'featuredListing-name[^>]*>([^<]+)', html)
        featured_prices = re.findall(r'featuredListing-price[^>]*>([^<]+)', html)
        print(f'Featured listings: {len(featured)}')
        if featured:
            for i, (name, price) in enumerate(zip(featured[:5], featured_prices[:5])):
                print(f'  {name}: {price}')
        
        # Check for any other price listings
        all_prices = re.findall(r'\$[\d,]+', html)
        price_vals = sorted(set(int(re.sub(r'[^\d]', '', p)) for p in all_prices if re.sub(r'[^\d]', '', p).isdigit() and int(re.sub(r'[^\d]', '', p)) > 100))
        print(f'All prices (sorted unique >100): {price_vals[:20]}')
        
        # Look for listing count
        listing_count = re.findall(r'(\d+)\s*listings?', html, re.IGNORECASE)
        print(f'Listing count mentions: {listing_count[:5]}')
        
        # Check if there's a repeater for regular listings
        repeater_items = re.findall(r'Repeater[^>]*>\s*</?(?:tbody|tr|td|div)', html)
        print(f'Repeater patterns: {len(repeater_items)}')
        
        # Look for any JSON data
        json_blocks = re.findall(r'window\.__([A-Z][a-zA-Z]+)\s*=\s*(\{.{100,\})', html)
        print(f'JSON blocks: {len(json_blocks)}')
        
    except Exception as e:
        print(f'ERROR: {e}')