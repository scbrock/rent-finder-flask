"""MC-246: Scrape ViewIt.ca Listings pages."""

import requests, re, time
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.viewit.ca/",
}

listings = []
seen = set()

for near_type, name in [(3, "apartments"), (2, "condos"), (1, "houses")]:
    for page in range(1, 4):
        url = f"https://www.viewit.ca/Listings?near={near_type}&page={page}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            print(f"[{name}] page {page}: HTTP {resp.status_code}, size={len(resp.text)}")
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # ASP.NET listings often in datalist or repeater containers
            # Try multiple selectors
            cards = soup.select(".listing-card, .listingItem, [class*=listing], .propertyItem, .listing-item")
            if not cards:
                # Try finding all links with /Listing/ in href
                links = soup.find_all("a", href=lambda h: h and "/Listing/" in h)
                print(f"  -> Found {len(links)} listing links")
                for a in links[:5]:
                    print(f"    -> {a.get('href','')} | text: {a.get_text(strip=True)[:80]}")

            # Look for price patterns in text
            price_spans = soup.find_all(string=re.compile(r'\$[\d,]+'))
            if price_spans:
                print(f"  -> Price spans: {len(price_spans)}, e.g.: {price_spans[0].strip()[:60]}")

            # Look for any dollar amounts
            dollar_texts = re.findall(r'\$[\d,]+', resp.text)
            unique_prices = sorted(set(dollar_texts))[:20]
            if unique_prices:
                print(f"  -> Unique $ amounts: {unique_prices[:15]}")

            # Check for data in script tags
            scripts = soup.find_all("script", type="application/ld+json")
            for s in scripts:
                if s.string and "rent" in s.string.lower():
                    print(f"  -> JSON-LD found: {s.string[:200]}")

        except Exception as e:
            print(f"[{name}] page {page} error: {e}")
        time.sleep(1)

# Also try the search page with city filter
print("\n--- Trying city search ---")
search_url = "https://www.viewit.ca/Search.aspx?city=Toronto"
try:
    resp = requests.get(search_url, headers=HEADERS, timeout=20)
    print(f"Search.aspx HTTP {resp.status_code}, size={len(resp.text)}")
    dollar_texts = re.findall(r'\$[\d,]+', resp.text)
    print(f"  Unique $ amounts: {sorted(set(dollar_texts))[:15]}")
except Exception as e:
    print(f"Search error: {e}")