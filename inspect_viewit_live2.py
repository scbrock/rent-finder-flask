import httpx, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
}

client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)

url = 'https://www.viewit.ca/Listings?sort=price&dir=asc&page=1'
resp = client.get(url)
html = resp.text

# Find all unique class names that might be listing containers
classes = re.findall(r'class="([^"]+)"', html)
class_counts = {}
for c in classes:
    for part in c.split():
        class_counts[part] = class_counts.get(part, 0) + 1

# Sort by frequency
sorted_classes = sorted(class_counts.items(), key=lambda x: -x[1])
print('Top 30 CSS classes:')
for cls, cnt in sorted_classes[:30]:
    print(f'  {cls}: {cnt}')

# Find price pattern
prices = re.findall(r'\$(\d{3,5})', html)
price_counts = {}
for p in prices:
    price_counts[int(p)] = price_counts.get(int(p), 0) + 1
sorted_prices = sorted(price_counts.items(), key=lambda x: -x[1])[:20]
print('\nTop prices:', sorted_prices)

# Try to find address/listing blocks
addr_blocks = re.findall(r'class="[^"]*address[^"]*"[^>]*>([^<]+)', html, re.IGNORECASE)
print('\nAddress blocks found:', len(addr_blocks))
print('First 5:', addr_blocks[:5])

# Find any div blocks that contain prices
price_divs = re.findall(r'<div[^>]*>.*?\$(\d{3,5}).*?</div>', html, re.DOTALL)[:20]
print('\nDivs with prices:', len(price_divs))