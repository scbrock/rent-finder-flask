"""Toronto Rental Listings Scraper — Kijiji Real-Estate API
Uses Kijiji's Next.js page that embeds rental listings in __NEXT_DATA__ Apollo state.
No browser needed — pure requests.
"""
import sys, os, json, re, time
import requests
import pandas as pd
from datetime import datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def extract_listings(html: str) -> list[dict]:
    """Extract RealEstateListing entries from Kijiji page's Apollo state."""
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return []

    data = json.loads(m.group(1))
    apollo = data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__", {})

    listings = []
    seen_ids = set()

    for key, value in apollo.items():
        if not isinstance(value, dict):
            continue
        if value.get("__typename") != "RealEstateListing":
            continue

        lid = value.get("id", "")
        if lid in seen_ids:
            continue
        seen_ids.add(lid)

        # Price — amount is in cents (e.g., 157500 = $1,575.00/month)
        price_data = value.get("price", {})
        if isinstance(price_data, dict):
            price = price_data.get("amount", 0) or 0
        else:
            try:
                price = int(str(price_data).replace(",", ""))
            except:
                price = 0

        if price < 100:  # Less than $1/month is invalid
            continue

        # Convert from cents to dollars
        price = round(price / 100.0)

        # Extract bedrooms and bathrooms from attributes
        attrs = value.get("attributes", {}) or {}
        beds = 0
        baths = 1
        sqft = None
        unit_type = ""

        if isinstance(attrs, dict) and attrs.get("__typename") == "RealEstateListingAttributes":
            for attr in attrs.get("all", []):
                name = attr.get("canonicalName", "")
                vals = attr.get("canonicalValues", [])
                val = vals[0] if vals else None
                if name == "numberbedrooms" and val and val != "0":
                    try:
                        beds = int(val)
                    except:
                        pass
                elif name == "numberbathrooms" and val and val != "0":
                    try:
                        baths = int(val)
                    except:
                        pass
                elif name == "areainfeet" and val and val != "0":
                    try:
                        sqft = int(val)
                    except:
                        pass
                elif name == "unittype" and val:
                    unit_type = val

        # Neighbourhood — resolve from neighbourhoodInfo ref
        location = value.get("location", {}) or {}
        neigh_ref = location.get("neighbourhoodInfo", {})
        neighborhood = "Downtown Toronto"
        if isinstance(neigh_ref, dict) and neigh_ref.get("__typename") == "NeighbourhoodInfo":
            # neighbourhoodInfo is a reference; try to resolve from apollo
            ref_key = f"NeighbourhoodInfo:{neigh_ref.get('id', '')}"
            neigh_data = apollo.get(ref_key, {})
            if isinstance(neigh_data, dict):
                neighborhood = neigh_data.get("name", "Downtown Toronto")
            elif isinstance(neigh_ref, dict):
                neighborhood = neigh_ref.get("name", "Downtown Toronto")

        # Fall back to address
        if neighborhood == "Downtown Toronto":
            addr = location.get("address", "")
            if addr:
                neighborhood = addr.split(",")[0] if "," in addr else addr[:40]

        # Listing URL
        url = value.get("url", "")
        if url and not url.startswith("http"):
            url = "https://www.kijiji.ca" + url

        # Title
        title = value.get("title", "").strip()

        # Date
        listed_date = value.get("activationDate", "") or ""

        listings.append({
            "source": "Kijiji",
            "price": price,
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "neighborhood": neighborhood[:60],
            "unit_type": unit_type,
            "listed_date": listed_date,
            "url": url,
            "title": title,
            "description": str(value.get("description", ""))[:500],
        })

    return listings


def scrape_kijiji(pages: int = 5) -> list[dict]:
    """
    Scrape Toronto apartment-for-rent listings from Kijiji.
    Uses the apartment-for-rent subcategory to get only rental listings (not for-sale).
    """
    all_listings = []

    # This URL filters to rental apartments in city of Toronto
    base = "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/apartment-for-rent/k0c37l1700273"

    for page in range(1, pages + 1):
        url = f"{base}?page={page}"
        print(f"  Page {page}: {url}", flush=True)
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code != 200:
                print(f"    HTTP {r.status_code}", flush=True)
                continue

            listings = extract_listings(r.text)
            new = len(listings)
            print(f"    Got {new} listings (total: {len(all_listings) + new})", flush=True)
            all_listings.extend(listings)

            if new == 0:
                break

            time.sleep(2.0)

        except Exception as e:
            print(f"    Error: {e}", flush=True)
            continue

    return all_listings


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print("=" * 70)
    print("  TORONTO RENTAL SCRAPER — Kijiji Real Estate API")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)
    print()

    print("[1] Scraping Kijiji Toronto apartment rentals...")
    listings = scrape_kijiji(pages=5)
    print(f"\n  Total listings collected: {len(listings)}")

    if len(listings) < 10:
        print(f"\n  ERROR: Only {len(listings)} listings. Check scraper.")
        sys.exit(1)

    df = pd.DataFrame(listings)
    df = df.drop_duplicates(subset=["url"]).reset_index(drop=True)
    df = df[df["price"] > 300].copy()  # filter out bad data / non-rental entries

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(out_dir, exist_ok=True)
    raw_path = os.path.join(out_dir, f"raw_{today}.json")
    df.to_json(raw_path, orient="records", indent=2)

    print(f"\n[2] Raw data saved to: {raw_path}")
    print()
    print("=" * 70)
    print(f"  DATASET PREVIEW — {len(df)} listings")
    print("=" * 70)

    display = ["source", "price", "beds", "baths", "neighborhood", "url"]
    pd.set_option("display.max_colwidth", 40)
    pd.set_option("display.width", 160)
    print(df[display].head(20).to_string(index=True))

    print()
    print(f"  Price range: ${df['price'].min():,} – ${df['price'].max():,}")
    print(f"  Median price: ${df['price'].median():,.0f}")
    print(f"  Beds: {sorted(df['beds'].unique())}")
    print(f"  Neighborhoods: {df['neighborhood'].nunique()}")
    print(f"  Sources: {df['source'].value_counts().to_dict()}")
    print("=" * 70)


if __name__ == "__main__":
    main()