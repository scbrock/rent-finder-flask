"""Try Kijiji GraphQL API with proper category/location."""
import requests, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-CA,en;q=0.9",
    "Referer": "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/c37l1700287",
}

# Try a direct GraphQL query
query = """
query SearchAds($location: String, $category: String) {
  searchAds(location: $location, category: $category) {
    results {
      id
      title
      price {
        type
        amount
      }
      location {
       Neighbourhood
      }
      adId
    }
    pagination {
      totalResults
    }
  }
}
"""

for url in [
    "https://www.kijiji.ca/api/graphql",
    "https://www.kijiji.ca/graphql",
]:
    try:
        r = requests.post(url, headers=HEADERS, json={
            "query": query,
            "variables": {"location": "city-of-toronto", "category": "c37l1700287"}
        }, timeout=15)
        print(f"URL: {url}")
        print(f"  Status: {r.status_code}, CT: {r.headers.get('content-type','')[:60]}")
        if r.status_code == 200:
            print(f"  Body: {r.text[:400]}")
        else:
            print(f"  Body: {r.text[:200]}")
        print()
    except Exception as e:
        print(f"  Error: {e}")