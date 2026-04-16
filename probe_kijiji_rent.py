"""Inspect Kijiji for-rent category HTML for rental listings."""
import requests, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Fetch the for-rent-by-owner category (not the apartments-condos category which has the wrong listings)
url = "https://www.kijiji.ca/b-for-rent/city-of-toronto/c30349001l1700273"
print(f"Fetching: {url}")
r = requests.get(url, headers=HEADERS, timeout=20)
print(f"HTTP {r.status_code}, size={len(r.text)}")

text = r.text

# Save HTML
with open("kijiji_for_rent.html", "w", encoding="utf-8") as f:
    f.write(text)

# Parse Apollo state
m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', text, re.DOTALL)
if m:
    data = json.loads(m.group(1))
    apollo = data.get('props',{}).get('pageProps',{}).get('__APOLLO_STATE__',{})

    real = [(k,v) for k,v in apollo.items() if isinstance(v,dict) and v.get('__typename')=='RealEstateListing']
    std = [(k,v) for k,v in apollo.items() if isinstance(v,dict) and v.get('__typename')=='StandardListing']

    print(f"\nApollo: RealEstateListing={len(real)}, StandardListing={len(std)}")

    # Show all RealEstateListings
    for k,v in real:
        price = v.get('price',{})
        if isinstance(price,dict): price = price.get('amount','')
        desc = str(v.get('description',''))[:100]
        print(f"  id={v.get('id')} price={price} desc={desc}")

    # Check for any search results
    search_meta = [(k,v) for k,v in apollo.items() if 'search' in k.lower() or 'result' in k.lower()]
    print(f"\nSearch-related keys: {[k for k,_ in search_meta[:10]]}")

    # Check for pagination or total count
    for k,v in apollo.items():
        if isinstance(v,dict) and v.get('totalResults'):
            print(f"Found totalResults: {v}")
else:
    print("No __NEXT_DATA__ found")