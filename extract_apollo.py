"""Extract listing data from Kijiji __APOLLO_STATE__."""

import httpx, re, json

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}
c = httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)
c.get("https://www.kijiji.ca/")

r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")

json_blocks = re.findall(r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', r.text, re.DOTALL)
for jb in json_blocks:
    if len(jb) > 10000:
        data = json.loads(jb)
        apollo = data["props"]["pageProps"].get("__APOLLO_STATE__", {})
        print(f"Apollo state keys: {list(apollo.keys())}")

        # Get normalized data entries
        for key, value in apollo.items():
            if isinstance(value, dict):
                # Look for Ad or listing entries
                if any(k in str(key) for k in ["Ad:", "Listing:", "Search:", "Query:"]):
                    print(f"\nKey: {key}")
                    print(f"  Value: {str(value)[:500]}")

        # Serialize and look for price patterns
        apollo_str = json.dumps(apollo)
        price_matches = re.findall(r'"\$[\d,]+"', apollo_str)
        print(f"\nPrice strings in Apollo: {price_matches[:20]}")

        # Find ad IDs
        ad_ids = re.findall(r'"adId"\s*:\s*"?(\d+)"', apollo_str)
        print(f"Ad IDs found: {ad_ids[:10]}")

        # Look for specific patterns
        for k, v in apollo.items():
            if isinstance(v, dict):
                if "description" in v and "price" in str(v).lower():
                    print(f"\nCandidate listing: {k}")
                    print(f"  {str(v)[:400]}")

        # Check for map of ads
        for k in apollo:
            if k.startswith("ROOT_QUERY.") or k.startswith("Ad:"):
                val_str = json.dumps(apollo[k])
                if len(val_str) > 100 and ("price" in val_str.lower() or "street" in val_str.lower()):
                    print(f"\n{k}: {val_str[:600]}")