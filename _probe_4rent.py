"""Deep probe of 4rent.ca Toronto"""
import requests, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

url = "https://4rent.ca/toronto-on/"
r = requests.get(url, headers=HEADERS, timeout=20)
print(f"Status: {r.status_code}, Size: {len(r.text)}")

# Find all price mentions
prices = re.findall(r'\$(\d{3,5}(?:,\d{3})*)', r.text)
print(f"All prices: {sorted(set(prices))}")

# Find listing URLs
listing_links = re.findall(r'href="(/listing/[a-z0-9_-]+)"', r.text)
print(f"Listing links: {listing_links[:10]}")

# Find JSON data
json_matches = re.findall(r'window\.dataLayer\s*=\s*(\[.*?\]);', r.text, re.DOTALL)
for m in json_matches:
    print(f"dataLayer found: {m[:300]}")
    break

# Try to find JSON API
api_patterns = [
    r'"url"\s*:\s*"([^"]+/listing/[^"]+)"',
    r'"uri"\s*:\s*"([^"]+/listing/[^"]+)"',
    r'"href"\s*:\s*"([^"]+listing[^"]+)"',
]
for pat in api_patterns:
    matches = re.findall(pat, r.text)
    if matches:
        print(f"Pattern {pat!r}: {matches[:5]}")

# Look for listings in JSON
json_ents = re.findall(r'"entities"\s*:\s*\[([^\]]+)\]', r.text)
print(f"Entities: {json_ents[:3]}")