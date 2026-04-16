import requests, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

# rent.at full content check
r = requests.get("https://www.rent.at/toronto-on/", headers=HEADERS, timeout=20)
print(f"rent.at: HTTP {r.status_code}, size={len(r.text)}")
print(f"Content-type: {r.headers.get('content-type','?')}")
# Check for JS framework
for kw in ["angular", "react", "vue", "ng.", "data-v-", "__nuxt", "nextjs"]:
    if kw in r.text.lower():
        print(f"  -> {kw} detected")

# Try to find prices in specific attributes
price_attrs = re.findall(r'(?:data-price|itemprop="price"|content="\$[\d,]+")[^"<]{0,100}', r.text, re.IGNORECASE)
print(f"Price attrs: {price_attrs[:10]}")

# Check for JSON data in script tags
json_scripts = re.findall(r'window\.__NUXT__\s*=\s*(\{.{0,500})', r.text)
if json_scripts:
    print(f"Nuxt (Vue SSR): found {len(json_scripts)}")

json_state = re.findall(r'window\.__INITIAL_STATE__\s*=\s*(\{.{0,500})', r.text)
if json_state:
    print(f"React state: found {len(json_state)}")

# Check for API endpoints
api_urls = re.findall(r'["\']([^"\']*api[^"\']*)["\']', r.text[:10000])
print(f"API URLs in HTML: {api_urls[:10]}")

# Check for listing data in JSON-LD
json_ld = re.findall(r'<script type="application/ld\+json">(.*?)</script>', r.text, re.DOTALL)
for j in json_ld:
    if "rent" in j.lower() or "accommodation" in j.lower():
        print(f"JSON-LD: {j[:300]}")

print(f"\nFirst 500 chars:\n{r.text[:500]}")