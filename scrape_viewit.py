"""MC-246: Scrape viewit.ca via ASP.NET form post with ViewState."""

import httpx, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
}

client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)

def extract_viewstate(html: str) -> dict:
    """Extract all hidden ASP.NET form fields."""
    fields = {}
    for match in re.finditer(r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html):
        fields[match.group(1)] = match.group(2)
    # Also check for value in separate attribute
    for match in re.finditer(r'<input[^>]+value="([^"]*)"[^>]+name="([^"]+)"', html):
        name, value = match.group(2), match.group(1)
        if name not in fields:
            fields[name] = value
    return fields


def get_listings_page(page: int = 1, sort: str = "price", direction: str = "asc") -> str:
    """Get raw HTML for listings page."""
    url = f"https://www.viewit.ca/Listings?sort={sort}&dir={direction}&page={page}"
    resp = client.get(url)
    return resp.text


def extract_listings_from_html(html: str) -> list[dict]:
    """
    Extract listing data from the WebForms HTML response.
    The listing grid is in the main content area.
    """
    listings = []

    # Strategy 1: Parse JSON-LD ItemList (featured listings only)
    json_ld_scripts = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
    )
    for script in json_ld_scripts:
        try:
            data = json.loads(script)
            if data.get("@type") == "ItemList" and "itemListElement" in data:
                for item in data["itemListElement"]:
                    url = item.get("url", "")
                    if url and "viewit.ca" in url:
                        lid = url.rstrip("/").split("/")[-1]
                        images = item.get("image", [])
                        img = images[0].get("url", "") if isinstance(images, list) else ""
                        listings.append({
                            "listing_id": lid,
                            "url": url,
                            "image_url": img,
                            "source": "json-ld",
                        })
        except (json.JSONDecodeError, KeyError):
            continue

    # Strategy 2: Extract from page script that initializes listing data
    # Look for Sys.Application.add_init blocks that have listing data
    app_init = re.findall(r'Sys\.Application\.add_init\([^)]*\{(.*?)\}\s*,\s*function', html, re.DOTALL)
    for block in app_init:
        ids = re.findall(r'"listingId"\s*:\s*"?(\d+)', block)
        prices = re.findall(r'"price"\s*:\s*"?\$?([\d,]+)', block)
        addrs = re.findall(r'"address"\s*:\s*"([^"]+)"', block)
        for i, lid in enumerate(ids):
            listings.append({
                "listing_id": lid,
                "price": prices[i] if i < len(prices) else "",
                "address": addrs[i] if i < len(addrs) else "",
                "source": "app_init",
            })

    # Strategy 3: Look for data attributes in ASP.NET repeater items
    # e.g., data-listingid="26056" or similar
    listing_data_ids = re.findall(r'data-(?:listing|lid|item)[-_]?id="(\d+)"', html, re.IGNORECASE)
    for lid in listing_data_ids:
        listings.append({
            "listing_id": lid,
            "source": "data-attr",
        })

    return listings


def fetch_individual_listing(lid: str) -> dict | None:
    """Fetch a single listing page and extract structured data."""
    resp = client.get(f"https://www.viewit.ca/{lid}")
    if resp.status_code != 200:
        return None

    html = resp.text

    # Extract from JSON-LD
    for script in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
        try:
            data = json.loads(script)
            addr = data.get("address", {})
            if isinstance(addr, dict):
                street = addr.get("streetAddress", "")
                city = addr.get("addressLocality", "")
                postal = addr.get("postalCode", "")
            else:
                street = str(addr)

            price_match = re.search(r'"price"\s*:\s*"([^"]+)"', script)
            price = price_match.group(1) if price_match else ""

            return {
                "listing_id": lid,
                "address": street,
                "city": city,
                "postal_code": postal,
                "price": price,
                "source_url": f"https://www.viewit.ca/{lid}",
            }
        except (json.JSONDecodeError, KeyError):
            continue

    return {"listing_id": lid, "address": "", "price": "", "source_url": f"https://www.viewit.ca/{lid}"}


def scrape_all_listings(max_pages: int = 5, per_page: int = 20) -> list[dict]:
    """
    Full scraping pipeline for viewit.ca.
    1. Get listing IDs from listings pages (JSON-LD + data attributes)
    2. Fetch individual listing pages for full data
    """
    all_ids = set()
    seen = set()

    print("Scraping listings pages for IDs...")
    for page in range(1, max_pages + 1):
        html = get_listings_page(page)
        listings = extract_listings_from_html(html)
        new_ids = [l["listing_id"] for l in listings if l["listing_id"] not in seen]
        seen.update(new_ids)
        print(f"  Page {page}: found {len(listings)} listings ({len(new_ids)} new)")

        if not listings:
            break

    print(f"\nTotal unique listing IDs: {len(seen)}")
    print(f"IDs: {sorted(seen)}")

    # Fetch full details for each listing
    results = []
    for i, lid in enumerate(sorted(seen)):
        print(f"  Fetching {lid} ({i+1}/{len(seen)})...")
        data = fetch_individual_listing(lid)
        if data:
            results.append(data)

    return results


if __name__ == "__main__":
    print("=== MC-246: viewit.ca full scraper ===\n")
    results = scrape_all_listings(max_pages=3)
    print(f"\nTotal scraped: {len(results)}")
    for r in results:
        print(f"  [{r['listing_id']}] ${r.get('price', 'N/A')} - {r.get('address', 'N/A')}")