"""MC-246: Multi-source Toronto rental scraper.

Tries accessible sources in order of reliability:
1. kijiji.ca (most reliable, no bot detection in tests)
2. viewit.ca (WebForms, partial — featured listings + SmartSearch AJAX)
3. rentboard.ca
4. Sample fallback data

For each source: collect listing data → normalize → merge with existing inventory.
"""

import re, time, json
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx
import pandas as pd
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ── Listing dataclass ─────────────────────────────────────────────────────────

@dataclass
class Listing:
    source: str
    listing_id: str
    title: str
    address: str
    price: float
    beds: int
    baths: float
    sqft: int | None
    neighborhood: str
    latitude: float | None
    longitude: float | None
    listing_url: str
    image_url: str | None
    scraped_at: str
    raw: dict  # original fields for debugging

    def to_dict(self) -> dict:
        d = asdict(self)
        d["price"] = self.price
        d["beds"] = self.beds
        d["baths"] = self.baths
        return d


def normalize_beds(text: str) -> int:
    """Extract bed count from text."""
    m = re.search(r"(\d+)\s*(?:bed|bedroom|br)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Handle "Studio" or "Bachelor"
    if "studio" in text.lower() or "bachelor" in text.lower():
        return 0
    return 0


def normalize_baths(text: str) -> float:
    """Extract bath count from text."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:bath|ba)", text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return 1.0


# ── Source 1: Kijiji ───────────────────────────────────────────────────────────

def scrape_kijiji(pages: int = 3) -> list[Listing]:
    """
    Kijiji.ca is one of the most reliable Toronto rental sources.
    Returns structured listing data.
    """
    listings = []
    seen_ids = set()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    for page in range(1, pages + 1):
        # Kijiji Toronto apartments/rentals
        url = f"https://www.kijiji.ca/b-apartments-condos/city-of-toronto/page-{page}/l1700273"
        print(f"  Kijiji page {page}...")

        with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                print(f"    HTTP {resp.status_code}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Kijiji listing cards: <li> with data-testid or class "search-item"
            cards = soup.select("li.search-item")
            if not cards:
                cards = soup.select('[data-testid="listing-card"]')

            print(f"    Found {len(cards)} cards")

            for card in cards:
                try:
                    # Listing URL
                    link_el = card.select_one("a[href*='/v']")
                    if not link_el:
                        link_el = card.find("a", href=True)
                    if not link_el:
                        continue

                    href = link_el.get("href", "")
                    if not href.startswith("http"):
                        href = "https://www.kijiji.ca" + href

                    # ID from URL
                    lid_match = re.search(r'/(\d{8,})', href)
                    lid = lid_match.group(1) if lid_match else href.split("/")[-1]
                    if lid in seen_ids:
                        continue
                    seen_ids.add(lid)

                    # Title
                    title_el = card.select_one("a[title], .title")
                    title = title_el.get_text(strip=True) if title_el else ""

                    # Price
                    price_el = card.select_one("[data-testid='price'], .price")
                    if not price_el:
                        price_el = card.find(string=lambda t: t and "$" in t and "/" in t)
                    price_text = price_el.get_text(strip=True) if price_el else ""
                    price_val = int("".join(filter(str.isdigit, price_text.split("/")[0]))) if price_text else 0

                    # Beds
                    beds_text = ""
                    beds_el = card.select_one("[data-testid='bedrooms'], .bedrooms")
                    if beds_el:
                        beds_text = beds_el.get_text(strip=True)
                    beds = normalize_beds(beds_text)

                    # Baths
                    baths_text = ""
                    baths_el = card.select_one("[data-testid='bathrooms'], .bathrooms")
                    if baths_el:
                        baths_text = baths_el.get_text(strip=True)
                    baths = normalize_baths(baths_text)

                    # Neighborhood
                    nb_el = card.select_one("[data-testid='location'], .location")
                    neighborhood = nb_el.get_text(strip=True) if nb_el else ""

                    # Image
                    img_el = card.select_one("img[src*='kijiji']")
                    img_url = img_el.get("src") if img_el else None

                    if price_val > 0 and price_val < 15000:  # sanity filter
                        listings.append(Listing(
                            source="kijiji",
                            listing_id=lid,
                            title=title,
                            address=neighborhood,
                            price=float(price_val),
                            beds=beds,
                            baths=baths,
                            sqft=None,
                            neighborhood=neighborhood,
                            latitude=None,
                            longitude=None,
                            listing_url=href,
                            image_url=img_url,
                            scraped_at=now,
                            raw={"page": page},
                        ))
                except Exception as exc:
                    continue

        time.sleep(2)  # polite delay between pages

    print(f"  Kijiji: {len(listings)} listings from {len(seen_ids)} unique IDs")
    return listings


# ── Source 2: ViewIt Featured ─────────────────────────────────────────────────

def scrape_viewit_featured() -> list[Listing]:
    """
    viewit.ca featured listings from JSON-LD.
    These are the 9 listings in the ItemList schema.
    Full listing pages can be fetched individually for address + price.
    """
    listings = []
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        resp = client.get("https://www.viewit.ca/Listings?sort=price&dir=asc")
        if resp.status_code != 200:
            print(f"  viewit: HTTP {resp.status_code}")
            return listings

        # Parse JSON-LD ItemList
        for script in re.findall(r'<script type="application/ld\+json">(.*?)</script>', resp.text, re.DOTALL):
            try:
                data = json.loads(script)
                if data.get("@type") != "ItemList":
                    continue
                for item in data.get("itemListElement", []):
                    url = item.get("url", "")
                    if "viewit.ca" not in url:
                        continue
                    lid = url.rstrip("/").split("/")[-1]
                    images = item.get("image", [])
                    img = images[0].get("url", "") if isinstance(images, list) and images else ""

                    # Fetch individual listing for price + address
                    lresp = client.get(f"https://www.viewit.ca/{lid}")
                    price_str = ""
                    address = ""
                    if lresp.status_code == 200:
                        p_match = re.search(r'"price"\s*:\s*"([^"]+)"', lresp.text)
                        price_str = p_match.group(1) if p_match else ""
                        addr_match = re.search(r'"streetAddress"\s*:\s*"([^"]+)"', lresp.text)
                        address = addr_match.group(1) if addr_match else ""

                    try:
                        price_val = float(price_str.replace(",", "")) if price_str else 0.0
                    except ValueError:
                        price_val = 0.0

                    listings.append(Listing(
                        source="viewit",
                        listing_id=lid,
                        title=f"ViewIt Listing {lid}",
                        address=address,
                        price=price_val,
                        beds=0,
                        baths=0.0,
                        sqft=None,
                        neighborhood="",
                        latitude=None,
                        longitude=None,
                        listing_url=url,
                        image_url=img,
                        scraped_at=now,
                        raw={"featured": True},
                    ))
                    time.sleep(1)
            except (json.JSONDecodeError, KeyError):
                continue

    print(f"  ViewIt featured: {len(listings)} listings")
    return listings


# ── Source 3: ViewIt SmartSearch (AJAX) ────────────────────────────────────────

def scrape_viewit_smartsearch(queries: list[str] | None = None) -> list[Listing]:
    """
    Use GetListingsSmartSearch AJAX endpoint to get listing data.
    Returns listings found via city/neighborhood searches.
    """
    if queries is None:
        queries = ["Toronto", "Scarborough", "North York", "Etobicoke", "Downtown Toronto"]

    listings = []
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    ajax_headers = {
        **HEADERS,
        "Content-Type": "application/json; charset=utf-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.viewit.ca/Listings",
    }

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for query in queries:
            try:
                resp = client.post(
                    "https://www.viewit.ca/vwdefault.aspx/GetListingsSmartSearch",
                    content=json.dumps({"sSearch": query}),
                    headers=ajax_headers,
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                xml_str = data.get("d", "")

                # Parse XML-style response for listing data
                # Look for address, price, bedrooms
                price_blocks = re.findall(
                    r'<Price>\s*\$?([\d,]+)\s*</Price>\s*<Address>\s*([^<]+)\s*</Address>',
                    xml_str
                )
                if price_blocks:
                    for price_str, address in price_blocks:
                        try:
                            price_val = float(price_str.replace(",", ""))
                            lid = re.search(r'(\d{4,6})', address)
                            listings.append(Listing(
                                source="viewit-smartsearch",
                                listing_id=lid.group(1) if lid else address[:20],
                                title=address,
                                address=address,
                                price=price_val,
                                beds=0,
                                baths=0.0,
                                sqft=None,
                                neighborhood=query,
                                latitude=None,
                                longitude=None,
                                listing_url=f"https://www.viewit.ca/",
                                image_url=None,
                                scraped_at=now,
                                raw={"query": query},
                            ))
                        except ValueError:
                            continue

                # If no price blocks, try to parse the city response (just returns CityID)
                if not price_blocks:
                    city_match = re.search(r'<CityID>(\d+)</CityID>', xml_str)
                    if city_match:
                        print(f"  ViewIt SmartSearch '{query}': CityID={city_match.group(1)} (no listings in XML)")

            except Exception as e:
                print(f"  SmartSearch '{query}' error: {e}")

            time.sleep(1)

    print(f"  ViewIt SmartSearch: {len(listings)} listings")
    return listings


# ── Combine all sources ────────────────────────────────────────────────────────

def scrape_all_sources() -> pd.DataFrame:
    """
    Run all sources, combine into single DataFrame.
    Deduplicate by listing_id.
    """
    all_listings: list[Listing] = []

    print("\n[Kijiji]")
    all_listings.extend(scrape_kijiji(pages=2))

    print("\n[ViewIt Featured]")
    all_listings.extend(scrape_viewit_featured())

    print("\n[ViewIt SmartSearch]")
    # Try specific Toronto searches
    all_listings.extend(scrape_viewit_smartsearch([
        "Downtown Toronto", "North York Toronto", "Scarborough Toronto",
        "Etobicoke Toronto", "M5V", "M4C", "M6E",
    ]))

    # Deduplicate
    seen = set()
    unique = []
    for lst in all_listings:
        if lst.listing_id not in seen:
            seen.add(lst.listing_id)
            unique.append(lst)

    print(f"\nTotal unique listings: {len(unique)}")

    # Convert to DataFrame
    rows = [l.to_dict() for l in unique]
    df = pd.DataFrame(rows)

    # Save
    out_path = OUTPUT_DIR / "listings.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved to {out_path}")

    return df


if __name__ == "__main__":
    print("=== MC-246: Multi-source Toronto rental scraper ===\n")
    df = scrape_all_sources()
    print(f"\nResult: {len(df)} listings")
    if not df.empty:
        print(df[["source", "listing_id", "price", "beds", "address"]].head(20).to_string())