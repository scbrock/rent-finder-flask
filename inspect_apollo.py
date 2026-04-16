"""Inspect what's in the Kijiji Apollo state."""

import httpx, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
    c.get("https://www.kijiji.ca/")  # Get cookies
    r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")

# Extract __NEXT_DATA__
next_match = re.search(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL
)
if next_match:
    data = json.loads(next_match.group(1))
    apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]
    print(f"Apollo has {len(apollo)} entries:\n")
    for k, v in apollo.items():
        print(f"  {k}: {str(v)[:150]}")

    # Look for any key with "search" in it
    print("\n\n--- Keys with 'search' ---")
    for k in apollo:
        if "search" in k.lower():
            print(f"  {k}: {str(apollo[k])[:300]}")

    # Look for any key with price data
    print("\n\n--- Keys with price ---")
    for k in apollo:
        v_str = str(apollo[k])
        if "price" in v_str.lower() and len(v_str) > 100:
            print(f"  {k}: {v_str[:400]}")

    # Look for any key with "Ad" in name
    print("\n\n--- Keys starting with Ad: ---")
    for k in apollo:
        if k.startswith("Ad:"):
            print(f"  {k}: {str(apollo[k])[:400]}")