"""MC-246: viewit.ca Listings?near=3 endpoint (ASP.NET form post for apartments)."""

import httpx, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://www.viewit.ca/Listings",
}

client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)

def extract_form_fields(html: str) -> dict:
    """Extract all hidden form fields from ASP.NET WebForms page."""
    fields = {}
    for m in re.finditer(r'<input[^>]+type="hidden"[^>]*>', html):
        name = re.search(r'name="([^"]+)"', m.group(0))
        value = re.search(r'value="([^"]*)"', m.group(0))
        if name and value:
            fields[name.group(1)] = value.group(1)
    # Fallback: name/value in any order
    for m in re.finditer(r'<input[^>]+(?:name|value)="[^"]*"[^>]*/?>', html):
        n = re.search(r'name="([^"]+)"', m.group(0))
        v = re.search(r'value="([^"]*)"', m.group(0))
        if n and n.group(1) not in fields:
            fields[n.group(1)] = v.group(1) if v else ""
    return fields

def post_listings(page: int = 1, near: int = 3) -> tuple[str, dict]:
    """Load listings via ASP.NET form post."""
    url = f"https://www.viewit.ca/Listings?near={near}&page={page}"
    resp = client.get(url)
    fields = extract_form_fields(resp.text)
    print(f"Page {page}: got {len(fields)} hidden fields, VS={len(fields.get('__VIEWSTATE',''))} chars")

    # Look for listing content
    has_listings = "GridView" in resp.text or "listing-item" in resp.text.lower() or "hero-featured" in resp.text
    print(f"  Has listing markup: {has_listings}")

    # Check for any text content that looks like rental listings
    prices = re.findall(r'\$(\d{3,5})', resp.text)
    print(f"  Prices found: {sorted(set(prices))[:15]}")

    return resp.text, fields

for near_val in [3, 2, 1]:
    print(f"\n=== near={near_val} ===")
    for page in [1, 2]:
        html, fields = post_listings(page, near_val)
        print(f"  Page {page}: {len(html)} chars")
        if "__EVENTTARGET" not in fields:
            fields["__EVENTTARGET"] = ""
        if "__EVENTARGUMENT" not in fields:
            fields["__EVENTARGUMENT"] = ""
        break  # Just check first page for now