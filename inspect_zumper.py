import requests, re

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'en-CA,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
}

# Try Zumper
r = requests.get('https://www.zumper.com/apartment-for-rent/toronto-on/', headers=HEADERS, timeout=15)
print(f'Zumper: HTTP {r.status_code}, len={len(r.text)}')

prices = re.findall(r'"price"\s*:\s*(\d+)', r.text)
print(f'Price JSON matches: {prices[:10]}')

listing_ids = re.findall(r'"id"\s*:\s*(\d{6,})', r.text)
print(f'Listing IDs: {listing_ids[:10]}')

hoods = re.findall(r'"neighborhood"\s*:\s*"([^"]+)"', r.text)
print(f'Neighborhoods: {hoods[:10]}')

# Look for API endpoint
api_patterns = re.findall(r'api[^\'"]{0,50}toronto[^\'"]{0,50}', r.text, re.IGNORECASE)
print(f'API patterns: {api_patterns[:5]}')

# Look for nextData
next_data = re.findall(r'__NEXT_DATA__[^>]*>([^<]+)', r.text)
if next_data:
    print(f'NEXT_DATA found, len: {len(next_data[0])}')
    try:
        import json
        data = json.loads(next_data[0])
        print(f'NEXT_DATA keys: {list(data.keys())}')
    except:
        print(f'NEXT_DATA raw: {next_data[0][:300]}')