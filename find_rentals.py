import httpx, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    c.get("https://www.kijiji.ca/")
    r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")

next_match = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
if next_match:
    data = json.loads(next_match.group(1))
    apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]
    rentals = {k: v for k, v in apollo.items() if k.startswith("RealEstateListing:")}
    print(f"RealEstateListing count: {len(rentals)}")
    for k, v in rentals.items():
        print(f"\n  {k}:")
        print(f"    title: {str(v.get('title', ''))[:80]}")
        print(f"    price: {v.get('price')}")
        print(f"    url: {str(v.get('url', ''))[:80]}")
        print(f"    beds: {v.get('bedrooms')}")
        print(f"    baths: {v.get('bathrooms')}")
        print(f"    address: {str(v.get('address', ''))[:80]}")
        print(f"    desc: {str(v.get('description', ''))[:100]}")

    # Also look for StandardListing with rental keywords
    print("\n--- StandardListing with rental keywords ---")
    for k, v in apollo.items():
        if not k.startswith("StandardListing:"):
            continue
        title = v.get("title", "").lower()
        desc = v.get("description", "").lower()
        if any(kw in f"{title} {desc}" for kw in ["apartment", "condo", "rent", "bedroom", "suite", "toronto"]):
            price = v.get("price")
            print(f"\n  {k}:")
            print(f"    title: {str(v.get('title', ''))[:80]}")
            print(f"    price: {price}")
            print(f"    url: {str(v.get('url', ''))[:80]}")

# Also look at what srp.searchCategory says
srp = data["props"]["pageProps"].get("srp", {})
print(f"\n\nsrp.searchCategory: {srp.get('searchCategory')}")
print(f"srp.loadingResults: {srp.get('loadingResults')}")

# Check the actual URL that was returned
print(f"\nFinal URL: {r.url}")
print(f"HTML size: {len(r.text)}")