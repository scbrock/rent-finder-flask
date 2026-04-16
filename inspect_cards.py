"""Inspect the listing card data from the working URL."""

import httpx, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
    c.get("https://www.kijiji.ca/")
    r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/1__32?sort=priceAsc")

# Extract listing cards from HTML
cards = re.findall(r'data-testid="listing-card"[^>]*>(.*?)</section>', r.text, re.DOTALL)
print(f"Listing cards found: {len(cards)}")

for i, card in enumerate(cards[:5]):
    print(f"\n=== Card {i} ===")
    # Get the listing URL
    url_match = re.search(r'href="(/v-[^"]+/\d+)"', card)
    if url_match:
        print(f"URL: https://www.kijiji.ca{url_match.group(1)}")
    # Title
    title_match = re.search(r'data-testid="listing-title"[^>]*>(.*?)</', card)
    if title_match:
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
        print(f"Title: {title[:80]}")
    # Price
    price_match = re.search(r'\$[\d,]+\.?\d*', card)
    if price_match:
        print(f"Price: {price_match.group(0)}")
    # Beds
    beds_match = re.search(r'(\d+)\s*(?:bed|bedroom|br)', card, re.IGNORECASE)
    if beds_match:
        print(f"Beds: {beds_match.group(0)}")
    # Address/neighborhood
    addr_match = re.search(r'data-testid="listing-location"[^>]*>(.*?)</', card)
    if addr_match:
        addr = re.sub(r'<[^>]+>', '', addr_match.group(1)).strip()
        print(f"Location: {addr}")
    # Image count
    img_match = re.search(r'(\d+)\s*images?', card, re.IGNORECASE)
    if img_match:
        print(f"Images: {img_match.group(0)}")

    # Save raw HTML for reference
    print(f"Raw (first 500 chars): {card[:500]}")