import requests, re

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'en-CA,en;q=0.9',
    'Referer': 'https://www.google.com/',
}

# Try rentals.ca - has a dedicated Toronto page
r = requests.get('https://rentals.ca/toronto', headers=HEADERS, timeout=15)
print(f'Rentals.ca: HTTP {r.status_code}, len={len(r.text)}')

# Look for listings in HTML
prices = re.findall(r'\$(\d{3,5})\s*/\s*mo', r.text)
print(f'Prices: {prices[:10]}')

# Check for __NEXT_DATA__ or Apollo state
next_data = re.findall(r'__NEXT_DATA__[^>]*>([^<]+)', r.text)
if next_data:
    print(f'NEXT_DATA len: {len(next_data[0])}')
    import json
    try:
        data = json.loads(next_data[0])
        print(f'NEXT_DATA keys: {list(data.keys())}')
    except Exception as e:
        print(f'NEXT_DATA parse error: {e}')
        print(f'Raw: {next_data[0][:300]}')

# Check for listing card patterns
cards = re.findall(r'listing-card[^\>]*>', r.text, re.IGNORECASE)
print(f'Listing cards: {len(cards)}')

# Look for rental-specific patterns
bed_patterns = re.findall(r'(\d+)\s*bed', r.text, re.IGNORECASE)
print(f'Bed patterns: {bed_patterns[:10]}')

# Try API endpoint
r2 = requests.get('https://rentals.ca/api/listings?city=toronto&province=ON&limit=20', headers=HEADERS, timeout=15)
print(f'\nAPI try: HTTP {r2.status_code}, len={len(r2.text)}')
print(r2.text[:400])