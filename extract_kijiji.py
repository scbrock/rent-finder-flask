"""MC-246: Extract Kijiji listing data from Apollo state."""

import httpx, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

def extract_kijiji_listings(url: str) -> list[dict]:
    """Fetch Kijiji page and extract listing data from Apollo state."""
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
        c.get("https://www.kijiji.ca/")  # Get cookies
        r = c.get(url)

    listings = []

    # Parse __NEXT_DATA__ for initial props
    next_data_match = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL
    )
    if next_data_match:
        try:
            next_data = json.loads(next_data_match.group(1))
            apollo = next_data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__", {})
            print(f"Apollo entries: {len(apollo)}")

            # Get search results from ROOT_QUERY.searchAds
            for key, value in apollo.items():
                if key.startswith("ROOT_QUERY.searchAds"):
                    ads_list = value.get("ads", []) if isinstance(value, dict) else []
                    print(f"Search ads: {len(ads_list)} items")
                    for ad in ads_list[:5]:
                        print(f"  {str(ad)[:200]}")
                    listings.extend(ads_list)
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")

    # Try to extract individual ad data from GraphQL normalized store
    ad_ids = re.findall(r'"adId"\s*:\s*(\d+)', r.text)
    print(f"Ad IDs found in HTML: {len(ad_ids)}")

    return listings


if __name__ == "__main__":
    url = "https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273"
    print(f"Fetching: {url}\n")
    listings = extract_kijiji_listings(url)
    print(f"\nTotal listings extracted: {len(listings)}")