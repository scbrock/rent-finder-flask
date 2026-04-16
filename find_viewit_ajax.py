"""MC-246: Find the ASP.NET AJAX endpoint that loads viewit.ca listing grid."""

import httpx, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

resp = httpx.get("https://www.viewit.ca/Listings?sort=price&dir=asc", headers=HEADERS, timeout=20, follow_redirects=True)

# Extract all script blocks
scripts = re.findall(r'<script[^>]*>(.*?)</script>', resp.text, re.DOTALL)
for i, s in enumerate(scripts):
    if len(s.strip()) > 100:
        print(f"Script {i} ({len(s)} chars):")
        print(s[:1000])
        print("---")

# Also look for PageMethod calls (ASP.NET WebMethods called from JavaScript)
page_methods = re.findall(r'(?:PageMethods|Sys\.Net\.WebRequest|_doPostBack)[^;]{0,200}', resp.text)
print(f"\nPageMethod references: {len(page_methods)}")
for pm in page_methods[:10]:
    print(f"  {pm[:200]}")

# Look for the actual listing loading function
listing_load = re.findall(r'(?:loadListings|getListings|fetchListings|searchListings)[^;]{0,200}', resp.text, re.IGNORECASE)
print(f"\nListing load functions: {len(listing_load)}")
for ll in listing_load[:5]:
    print(f"  {ll[:200]}")

# Find any URL-like strings that look like AJAX endpoints
ajax_patterns = re.findall(r'["\'](/[^"\']*(?:Listings|Search|Query|Filter)[^"\']*)["\']', resp.text)
print(f"\nAJAX endpoint candidates: {ajax_patterns[:20]}")