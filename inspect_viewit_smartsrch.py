import httpx, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)

url = 'https://www.viewit.ca/rentals/toronto'
resp = client.get(url)
html = resp.text

# Find SmartSearch result containers
smart_containers = re.findall(r'smartSearch-Result-Container[^>]*>(.*?)</div>', html, re.DOTALL)
print(f'Smart search containers: {len(smart_containers)}')
for i, c in enumerate(smart_containers[:3]):
    print(f'  Container {i} (len={len(c)}): {c[:300]}')

# Look for any JSON data in the page
# Check for ScriptManager JSON
sm_patterns = re.findall(r'\{"url"\s*:\s*"[^"]+"\s*,\s*"expireTime".*?\}', html)
print(f'ScriptManager patterns: {len(sm_patterns)}')
for p in sm_patterns[:3]:
    print(f'  {p[:200]}')

# Check for any JSON that contains listing data
listing_json = re.findall(r'\{"@type"\s*:\s*"ListItem".*?\}', html)
print(f'ListItem JSON: {len(listing_json)}')

# Look for the UpdatePanel data
update_panels = re.findall(r'UpdatePanel.*?<div[^>]*id="([^"]+)"', html)
print(f'UpdatePanels: {update_panels}')

# Try to find any API/AJAX URL patterns
ajax_urls = re.findall(r'(?:ajax|api|json|service)[^\w]*url[^\w]*[:=][^\w]*["\']([^"\']+)["\']', html[:50000])
print(f'AJAX URLs: {ajax_urls[:10]}')

# Try to find data in the ViewState (it's a large base64 value)
viewstate_match = re.search(r'__VIEWSTATE[^>]*value="([^"]+)"', html)
if viewstate_match:
    vs = viewstate_match.group(1)
    print(f'ViewState length: {len(vs)}')
    # ViewState might be compressed - try to decode
    import base64
    try:
        vs_bytes = base64.b64decode(vs)
        print(f'ViewState decoded bytes: {len(vs_bytes)}')
        # Check if it's gzip compressed
        if vs_bytes[:2] == b'\x1f\x8b':
            import gzip
            decompressed = gzip.decompress(vs_bytes)
            text = decompressed.decode('utf-8', errors='replace')
            print(f'ViewState decompressed: {len(text)} chars')
            # Look for price patterns in decompressed ViewState
            prices_in_vs = re.findall(r'\$[\d,]+', text)
            print(f'Prices in ViewState: {prices_in_vs[:20]}')
            addresses_in_vs = re.findall(r'\d+\s+[A-Z][a-zA-Z\s]+(?:Ave|St|Rd|Blvd|Dr|Lane|Way|Court|Crescent|Place)', text)
            print(f'Addresses in ViewState: {addresses_in_vs[:10]}')
    except Exception as e:
        print(f'ViewState decode error: {e}')
