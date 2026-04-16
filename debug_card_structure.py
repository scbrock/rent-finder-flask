"""Debug: find actual listing card HTML structure."""

import httpx, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
    c.get("https://www.kijiji.ca/")
    r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")

# Find the first occurrence of "listing-card" in HTML
pos = r.text.find('data-testid="listing-card"')
if pos > 0:
    print(f"First listing-card at position {pos}")
    print(f"Context (200 chars before): {r.text[pos-200:pos]}")
    print(f"\nCard (500 chars after): {r.text[pos:pos+500]}")
    print(f"\nCard (500-1000 chars after): {r.text[pos+500:pos+1000]}")
else:
    print("No 'data-testid=\"listing-card\"' found in HTML")
    # Check for variations
    for attr in ['listing-card', 'listingCard', 'listingcard', 'data-listing']:
        count = r.text.count(attr)
        print(f"'{attr}': {count} occurrences")
    # Check if cards are rendered by client-side JS
    print(f"\n__NEXT_DATA__ length: {len(re.search(r'<script[^>]+id=\"__NEXT_DATA__\"[^>]*>(.*?)</script>', r.text, re.DOTALL).group(1)) if re.search(r'<script[^>]+id=\"__NEXT_DATA__\"[^>]*>(.*?)</script>', r.text, re.DOTALL) else 0}")
    # Check for any SSR listing markup
    srps = re.findall(r'srp-card[^>]+', r.text)
    print(f"srp-card occurrences: {len(srps)}")
    article_count = r.text.count("<article")
    print(f"<article> tags: {article_count}")