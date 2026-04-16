import requests
from bs4 import BeautifulSoup
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Try Craigslist Toronto rental search
url = "https://toronto.craigslist.org/search/apa?availabilityMode=0&housing=1000%2C3000&max_bedrooms=2&max_price=3500&min_bedrooms=1&min_price=1000&neighborhoods=Downtown+Toronto%2C+Liberty+Village%2C+Queen+West%2C+King+West%2C+Distillery+District%2C+CityPlace%2C+Harbourfront%2C+Financial+District&postedToday=1"

try:
    r = requests.get(url, headers=HEADERS, timeout=20)
    print(f"HTTP {r.status_code}, Length: {len(r.text)}")
    soup = BeautifulSoup(r.text, "html.parser")
    
    # Look for listing cards
    listings = soup.select(".cl-static-search-results li, .result-row, [class*=listing], article")
    print(f"Listing elements found: {len(listings)}")
    
    # Try to find any apartment-like results
    titles = soup.select(".result-title, .hdrlnk, [class*=title]")
    print(f"Title elements: {len(titles)}")
    for t in titles[:5]:
        print(f"  {t.get_text(strip=True)[:80]}")
    
    # Try to find prices
    prices = soup.find_all(string=re.compile(r"\$\d+"))
    print(f"Price mentions: {len(prices)}")
    for p in prices[:5]:
        print(f"  {p.strip()[:80]}")
    
    # Check if the page has any data at all
    text_sample = soup.get_text()[:1000]
    print(f"\nText sample:\n{text_sample[:500]}")
    
except Exception as e:
    print(f"ERROR: {e}")
