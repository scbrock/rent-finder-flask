"""Extract listing data from Kijiji page props JSON."""

import httpx, re, json

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}
c = httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)
c.get("https://www.kijiji.ca/")

r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")

# Find the JSON block
json_blocks = re.findall(r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', r.text, re.DOTALL)
print(f"JSON blocks: {len(json_blocks)}")

for jb in json_blocks:
    if len(jb) > 10000:  # Only large blocks with listing data
        try:
            data = json.loads(jb)
            print(f"\nJSON keys: {list(data.keys())}")
            page_props = data.get("props", {}).get("pageProps", {})
            print(f"pageProps keys: {list(page_props.keys())}")

            # Look for listing data
            for key in ["listings", "ads", "searchResults", "items", "results"]:
                if key in page_props:
                    val = page_props[key]
                    if isinstance(val, list):
                        print(f"\n{key}: {len(val)} items")
                        if val:
                            print(f"  First item keys: {list(val[0].keys()) if isinstance(val[0], dict) else type(val[0])}")
                            print(f"  First item: {str(val[0])[:300]}")
                    elif isinstance(val, dict):
                        print(f"\n{key}: dict with keys {list(val.keys())}")
                    else:
                        print(f"\n{key}: {type(val)}, len={len(str(val))}")

            # Check for any search-related fields
            search = page_props.get("search", {})
            if search:
                print(f"\nsearch object: {list(search.keys())}")

            # Try to find category-specific data
            for k in ["category", "searchRequest", "userRequest"]:
                if k in page_props:
                    print(f"\n{k}: {str(page_props[k])[:300]}")

            # Serialize the full pageProps to find listing count
            serialized = json.dumps(page_props)
            has_listing = "listingId" in serialized or "adId" in serialized or "itemId" in serialized
            print(f"\nHas listing IDs: {has_listing}")

            # Count occurrences of price-like strings
            price_count = len(re.findall(r'\$[\d]{3,5}', serialized))
            print(f"Price occurrences in pageProps: {price_count}")

        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            print(f"First 200 chars: {jb[:200]}")