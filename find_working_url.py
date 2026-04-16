import httpx, re, json

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}
c = httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True)
c.get("https://www.kijiji.ca/")

for url in [
    "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/page-1/c1700273l1700273",
    "https://www.kijiji.ca/b-rentals/city-of-toronto/page-1/l1700273",
    "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/l1700273",
    "https://www.kijiji.ca/apartments-condos/city-of-toronto/k0c1700273l1700273",
]:
    r = c.get(url)
    cards = len(re.findall(r'data-testid="listing-card"', r.text))
    print(f"\nURL: {url}")
    print(f"  HTTP {r.status_code}, cards={cards}")
    nm = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
    if nm:
        data = json.loads(nm.group(1))
        apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]
        real = len([k for k in apollo if k.startswith("RealEstateListing:")])
        print(f"  RealEstateListing: {real}")
        std = len([k for k in apollo if k.startswith("StandardListing:")])
        print(f"  StandardListing: {std}")
        # Sample first RealEstateListing
        for k, v in apollo.items():
            if k.startswith("RealEstateListing:"):
                print(f"  Sample: {str(v)[:300]}")
                break