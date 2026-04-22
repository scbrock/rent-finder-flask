import httpx, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)

url = 'https://www.viewit.ca/Listings?sort=price&dir=asc&page=1'
resp = client.get(url)
print('Status:', resp.status_code)
print('Content-Type:', resp.headers.get('content-type'))
html = resp.text

# Check for listing data
cards = re.findall(r'class="listingCard', html)
print('Cards found:', len(cards))

# Check ItemList JSON-LD
json_ld_scripts = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
print('JSON-LD scripts:', len(json_ld_scripts))
for i, script in enumerate(json_ld_scripts[:3]):
    try:
        data = json.loads(script)
        print(f'JSON-LD {i}: type={data.get("@type")}, keys={list(data.keys())[:5]}')
    except:
        print(f'JSON-LD {i}: parse error')

# Try to find any price data
prices = re.findall(r'\$[\d,]+', html)[:10]
print('Sample prices:', prices[:5])

# Look for listing div patterns
listings_div = re.findall(r'data-price', html)
print('data-price attrs:', len(listings_div))

# Check a portion of raw HTML for structure clues
# Find some listing-related HTML
idx = html.find('listingCard')
if idx >= 0:
    print('Found listingCard at idx:', idx)
    print('Snippet:', html[idx:idx+300])