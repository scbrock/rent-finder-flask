"""Inspect Viewit.ca for rental listings."""
import requests, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
    "Referer": "https://www.viewit.ca/",
}

# Try Toronto rental search
urls = [
    "https://www.viewit.ca/searchresults.aspx?search=apartment&location=Toronto&pricefrom=0&priceto=3500",
    "https://www.viewit.ca/PreferredDirectories/PTRental/Results.aspx",
]

for url in urls:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        print(f"\nURL: {url[:80]}")
        print(f"  HTTP {r.status_code}, Len: {len(r.text)}")

        # Look for JSON data in page
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', r.text, re.DOTALL)
        for s in scripts:
            if 'listing' in s.lower() or 'price' in s.lower() and len(s) > 200:
                print(f"  Script snippet (200ch): {s[:200]}")

        # Look for structured data
        json_blocks = re.findall(r'window\.__[A-Z][a-zA-Z]+\s*=\s*(\{.{100,}\})', r.text)
        for b in json_blocks[:2]:
            print(f"  JSON block: {b[:200]}")

        # Look for address/price patterns in HTML
        addresses = re.findall(r'class="[^"]*address[^"]*"[^>]*>([^<]+)', r.text, re.IGNORECASE)
        prices = re.findall(r'\$[\d,]+', r.text)[:5]
        print(f"  Prices found: {prices[:5]}")
        print(f"  Addresses found: {addresses[:3]}")

    except Exception as e:
        print(f"  ERROR: {e}")