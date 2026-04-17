import requests, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

r = requests.get('https://www.viewit.ca/FeaturedListings.aspx', headers=HEADERS, timeout=15)

# Print entire page length and look for actual listing content
# Search for key patterns in the raw HTML
patterns = [
    r'Price[^<]{0,30}\$[\d,]+',
    r'bedroom[^<]{0,50}',
    r'<img[^>]+src="[^"]*"[^>]+alt="([^"]+)"',
    r'data-price="([^"]+)"',
    r'listingid[^>]{0,30}"[^"]+"',
]

for p in patterns:
    matches = re.findall(p, r.text, re.IGNORECASE)
    if matches:
        print(f"Pattern '{p[:40]}...': {matches[:5]}")

# Print raw snippet around where listings would be
idx = r.text.lower().find('listing')
if idx > 0:
    print(f"\nListing context (idx {idx}):")
    print(r.text[idx-100:idx+300])
else:
    print("No 'listing' found in page")
    print("Page sample 3000-3500:", r.text[3000:3500])