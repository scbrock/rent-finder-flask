"""MC-246: Try viewit.ca direct listing URLs + check for any accessible API."""

import requests, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

# Try viewit.ca listing pages directly
listing_urls = [
    "https://www.viewit.ca/Listing/ViewAll.aspx",
    "https://www.viewit.ca/Listings?sort=price&dir=asc",
    "https://www.viewit.ca/Listings?city=Toronto&type=apartment",
    "https://www.viewit.ca/FeaturedListings.aspx",
    "https://www.viewit.ca/listingsearch.aspx",
]

for url in listing_urls:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    print(f"URL: {url}")
    print(f"  HTTP {resp.status_code}, size={len(resp.text)}, ctype={resp.headers.get('content-type','?')[:50]}")
    dollar_texts = sorted(set(re.findall(r'\$[\d,]+', resp.text)))[:10]
    print(f"  Prices: {dollar_texts}")
    # Check for ASP.NET __VIEWSTATE or UpdatePanel
    if "__VIEWSTATE" in resp.text:
        print("  -> ASP.NET WebForms (requires ViewState/EventValidation)")
    if "UpdatePanel" in resp.text:
        print("  -> ASP.NET AJAX UpdatePanel")
    if "WebResource" in resp.text:
        print("  -> Uses WebResource.axd (classic ASP.NET)")
    print()

# Check rentseeker API
print("--- rentseeker.ca API probe ---")
urls_rs = [
    "https://www.rentseeker.ca/api/listings?city=toronto",
    "https://www.rentseeker.ca/api/search?location=toronto",
    "https://www.rentseeker.ca/listings?city=toronto&province=ON",
]
for url in urls_rs:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        print(f"{url}: HTTP {resp.status_code}, size={len(resp.text)}, prices={sorted(set(re.findall(r'\$[\d,]+', resp.text)))[:5]}")
    except Exception as e:
        print(f"{url}: {e}")