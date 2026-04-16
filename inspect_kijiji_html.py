import httpx, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

# Try the Kijiji ads API that powers their search
# Based on what we know about Kijiji's Next.js app
test_urls = [
    "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/page-1/c37l1700287",
    "https://www.kijiji.ca/b-apartments-condos/toronto-on/c37l1700287",
    "https://www.kijiji.ca/b-rentals/city-of-toronto/k0l1700273",
    "https://www.kijiji.ca/srpdekijiji/ajax/DesktopSearchLayout/GetLocationSuggestions",
]

for url in test_urls:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        print(f"\nURL: {url}")
        print(f"  HTTP {r.status_code}, ct={r.headers.get('content-type','?')[:60]}, size={len(r.text)}")
        if r.status_code == 200:
            # Check for __NEXT_DATA__
            next_match = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
            if next_match:
                data = json.loads(next_match.group(1))
                apollo = data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__", {})
                print(f"  Apollo keys: {list(apollo.keys())[:20]}")
                # Look for ad-related keys
                ad_keys = [k for k in apollo.keys() if 'Ad' in k or 'Listing' in k or 'search' in k.lower()]
                print(f"  Ad-related keys: {ad_keys[:10]}")
                if ad_keys:
                    for ak in ad_keys[:3]:
                        print(f"    {ak}: {str(apollo[ak])[:200]}")
            else:
                # Check for any JSON data
                if '__APOLLO_STATE__' in r.text:
                    print(f"  Found APOLLO_STATE in page")
                    idx = r.text.find('__APOLLO_STATE__')
                    print(r.text[idx:idx+500])
                else:
                    # Just look for prices
                    prices = re.findall(r'"\$[\d,]+"', r.text)
                    print(f"  Prices in JSON: {prices[:10]}")
    except Exception as e:
        print(f"  ERROR: {e}")
