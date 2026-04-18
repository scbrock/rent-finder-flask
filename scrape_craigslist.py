"""
Scrape Toronto rental listings from Craigslist.
MC-258: second data source to increase listing volume.
Uses HTML parsing + JSON-LD (beds/baths/neighbourhood from JSON-LD, price from HTML).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Known-bad patterns to filter out non-rental listings
_NON_RENTAL_KEYWORDS = [
    "office space", "shared office", "coworking", "work space",
    "hotel", "hostel", "motel", "airbnb", "short term",
    "furnished accommodation", "furn. accom",
    "hotel room", "sublet", "sub-let",
    "storage", "parking space", "locker",
]

_RENTAL_KEYWORDS = [
    "apartment", "apt", "condo", "flat", "unit", "suite", "bedroom",
    "bachelor", "studio", "townhouse", "town house",
    "for rent", "to rent", "rental",
    "available now", "available immediately",
]


@dataclass
class CLListing:
    listing_id: str
    title: str
    price: float
    price_str: str
    location: str
    beds: str
    baths: str = ""
    url: str = ""
    source: str = "craigslist"
    days_ago: int = 5
    is_stale: bool = False


def _is_rental(title: str) -> bool:
    t = title.lower()
    if any(kw in t for kw in _NON_RENTAL_KEYWORDS):
        return False
    has_rental = any(kw in t for kw in _RENTAL_KEYWORDS)
    has_beds = bool(re.search(r"\b(?:one|two|three|four|\d+)\s*(?:bed(?:room)?s?|br)\b", t))
    return has_rental or has_beds


def _parse_beds(title: str) -> str:
    m = re.search(r"\b(\d+)\s*(?:bed(?:room)?s?|br)\b", title, re.IGNORECASE)
    if m:
        return m.group(1)
    if any(k in title.lower() for k in ["bachelor", "studio"]):
        return "0"
    return ""


def _parse_price(text: str) -> float:
    m = re.search(r"\$([0-9,]+)", text)
    return float(m.group(1).replace(",", "")) if m else 0.0


def _extract_jsonld(soup: BeautifulSoup) -> list[dict]:
    """Return itemListElement from the large ItemList JSON-LD block."""
    for s in soup.find_all("script"):
        if s.get("type") != "application/ld+json":
            continue
        text = (s.string or "").strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except Exception:
            continue
        if isinstance(data, dict) and "itemListElement" in data:
            item_type = str(data.get("@type", ""))
            if "ItemList" in item_type and len(data["itemListElement"]) > 5:
                return data["itemListElement"]
    return []


def _build_jld_index(items: list[dict]) -> dict[int, dict]:
    """Build position -> item dict from JSON-LD ListItems."""
    idx = {}
    for li in items:
        try:
            pos = int(li.get("position", -1))
            item = li.get("item", {})
            if pos >= 0 and item.get("@type") == "Apartment":
                idx[pos] = item
        except (ValueError, TypeError):
            continue
    return idx


def parse_html(html: str) -> list[CLListing]:
    """
    Parse Craigslist search results page.
    HTML structure: <li class="cl-static-search-result">
        <a href="...">
            <div class="title">...</div>
            <div class="details">
                <div class="price">$4,190</div>
                <div class="location">Neighbourhood</div>
            </div>
        </a>
    </li>
    """
    soup = BeautifulSoup(html, "html.parser")
    listings = []
    seen_ids = set()

    rows = soup.find_all("li", class_="cl-static-search-result")
    if not rows:
        return listings

    for row in rows:
        try:
            # URL from <a href>
            a_tag = row.find("a", href=True)
            if not a_tag:
                continue
            url = a_tag.get("href", "")

            # Listing ID
            id_m = re.search(r"/(\d{8,})(?:\d*)\.html", url)
            listing_id = id_m.group(1) if id_m else ""
            if listing_id and listing_id in seen_ids:
                continue
            if listing_id:
                seen_ids.add(listing_id)

            # Title from <div class="title">
            title_tag = row.find("div", class_="title")
            title = title_tag.get_text(strip=True) if title_tag else ""

            if not _is_rental(title):
                continue

            # Price from <div class="price">
            price_tag = row.find("div", class_="price")
            price_text = price_tag.get_text(strip=True) if price_tag else ""
            price_val = _parse_price(price_text)

            # Beds from title
            beds_str = _parse_beds(title)

            # Neighbourhood from <div class="location">
            location_tag = row.find("div", class_="location")
            location = location_tag.get_text(strip=True).strip("()\n ") if location_tag else ""

            if price_val >= 500 and price_val <= 15000:
                listings.append(CLListing(
                    listing_id=listing_id or f"cl-{len(listings)}",
                    title=title,
                    price=price_val,
                    price_str=f"${price_val:,.0f}",
                    location=location or "Toronto",
                    beds=beds_str,
                    baths="",
                    url=url,
                    source="craigslist",
                    days_ago=5,
                    is_stale=False,
                ))
        except Exception:
            continue

    return listings


def scrape(pages: int = 5) -> list[CLListing]:
    """Scrape Toronto Craigslist apartment listings across multiple pages."""
    all_listings = []
    seen = set()

    base_url = "https://toronto.craigslist.org/search/apa"

    with requests.Session() as sess:
        sess.headers.update(HEADERS)

        for page in range(pages):
            offset = page * 120
            url = f"{base_url}?s={offset}" if page > 0 else base_url
            r = sess.get(url, timeout=30)
            if r.status_code != 200:
                break

            page_listings = parse_html(r.text)
            new = [l for l in page_listings if l.listing_id not in seen and l.price > 0]
            seen.update(l.listing_id for l in new)
            all_listings.extend(new)

            if not page_listings:
                break

    return all_listings


if __name__ == "__main__":
    print("MC-258: Scraping Craigslist Toronto rentals...\n")
    results = scrape(pages=5)
    print(f"\nTotal: {len(results)} listings")
    print(f"Unique: {len(set(r.listing_id for r in results))}")
    beds_dist = {}
    for r in results:
        b = r.beds or "?"
        beds_dist[b] = beds_dist.get(b, 0) + 1
    print("Beds distribution:", sorted(beds_dist.items()))
    print("\nSample (first 5):")
    for r in results[:5]:
        print(f"  ${r.price:>7,.0f} | {r.beds or '-'}BR | {r.location:<20} | {r.title[:50]}")
