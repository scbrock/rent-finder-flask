import httpx, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
}

client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)

url = 'https://www.viewit.ca/Listings?sort=price&dir=asc&page=1'
resp = client.get(url)
html = resp.text

# Find all text around prices (but avoid dollar sign regex patterns)
price_pattern = re.compile(r'.{0,50}\$[\d,]+.{0,50}')
matches = price_pattern.findall(html)

listing_contexts = []
for m in matches:
    clean = m.replace('\n', ' ').strip()
    if any(w in clean.lower() for w in ['bed', 'br', 'bath', 'toronto', 'downtown', 'sqft', 'sq ft', 'ave ', 'st ', 'dr ']):
        listing_contexts.append(clean[:120])

print('Listing contexts with location keywords:')
for ctx in listing_contexts[:20]:
    print(' ', repr(ctx))

# Look at what the actual listing container looks like
# Find divs with price-like content (no regex dollar sign)
div_pattern = re.compile(r'<div[^>]+class="[^"]*"[^>]*>([^<]{0,50}\$[\d,]{3,6}[^<]{0,50})</div>')
divs = div_pattern.findall(html)
print(f'\nDivs with prices: {len(divs)}')
for d in divs[:10]:
    print(' ', repr(d[:120]))

# Check for any pattern like address+price together
# Look for the text between featured listings to find regular listing pattern
between_features = re.split(r'featuredListing', html)
print(f'\nBetween features segments: {len(between_features)}')
for i, seg in enumerate(between_features[1:6], 1):
    clean = re.sub(r'<[^>]+>', ' ', seg)
    clean = re.sub(r'\s+', ' ', clean)
    print(f'Segment {i}: {clean[:200]}')