import httpx, re

client = httpx.Client(timeout=30)
resp = client.get('https://www.viewit.ca/js/viewit.dist.min.js')
js = resp.text
print('JS size:', len(js))

# Look for API endpoints or AJAX URLs
endpoints = re.findall(r'["\'](/[^\"\']+|https?://[^\"\']+)["\']\s*[,:]', js[:10000])
print('Endpoints found:', len(endpoints))
for e in endpoints[:30]:
    print('  ', e[:80])

# Look for city/area/region codes
city_patterns = re.findall(r'(?:area|region|city|loc)[^\w]{0,20}["\']([A-Za-z0-9_-]{2,20})', js[:50000])
print('City patterns:', set(city_patterns[:50]))

# Look for Toronto-related patterns
toronto = re.findall(r'toronto[^a-z]{0,5}([a-z]{2,20})', js[:20000])
print('Toronto patterns:', toronto[:20])

# Look for pricing/listing grid related
price_js = re.findall(r'(?:price|listing|grid|search)[^\w]{0,30}["\']([A-Za-z0-9_/-]{3,50})', js[:20000])
print('Price/listing patterns:', price_js[:20])

# Check for any URL patterns that look like API calls
api_urls = re.findall(r'(?:api|ajax|json|service)[^\w]{0,20}["\']([A-Za-z0-9_/-]{3,100})', js[:20000])
print('API patterns:', api_urls[:20])