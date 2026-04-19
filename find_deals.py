"""
Toronto Rental Deal Finder
MC-245 — Finds underpriced Toronto rental listings.

Usage: python find_deals.py [--region Downtown|East End|West End|North York|Etobicoke|Scarborough]
Output: console table + deals_output.csv
"""

import sys, os, warnings, json, argparse
warnings.filterwarnings("ignore")

import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()


def parse_args():
    parser = argparse.ArgumentParser(description="Toronto Rent Deal Finder")
    parser.add_argument(
        "--region",
        choices=["Downtown", "East End", "West End", "North York", "Etobicoke", "Scarborough"],
        default=None,
        help="Filter results to a specific Toronto region",
    )
    parser.add_argument(
        "--max-commute",
        type=int,
        default=None,
        dest="max_commute",
        help="Maximum commute time in minutes from destination",
    )
    parser.add_argument(
        "--destination",
        type=str,
        default=None,
        dest="destination",
        help="Destination address for commute calculation (e.g. 'Union Station, Toronto')",
    )
    return parser.parse_args()

# ── Data Collection ────────────────────────────────────────────────────────────

def scrape_zumper(pages=3) -> pd.DataFrame:
    """
    Scrape Toronto rentals from Zumper.com.
    Returns DataFrame with: price, beds, baths, sqft, neighborhood, listing_age_days, link
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-CA,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    listings = []
    seen_ids = set()

    for page in range(1, pages + 1):
        url = f"https://www.zumper.com/apartments-for-rent/toronto/on/?page={page}"
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                print(f"  Zumper page {page} → HTTP {resp.status_code}")
                continue
            soup = BeautifulSoup(resp.text, "html.parser")

            # Zumper uses <article> cards with data-testid
            cards = soup.find_all("article")
            if not cards:
                # Try div-based listing containers
                cards = soup.select('[data-testid="listing-card"]')

            if not cards:
                print(f"  Zumper page {page}: no listing cards found")
                continue

            for card in cards:
                try:
                    # Link
                    link_el = card.find("a", href=True)
                    if not link_el:
                        continue
                    href = link_el["href"]
                    if not href.startswith("http"):
                        href = "https://www.zumper.com" + href

                    # Listing ID (dedup)
                    listing_id = href.split("/")[-2] if "/" in href else href
                    if listing_id in seen_ids:
                        continue
                    seen_ids.add(listing_id)

                    # Price
                    price_el = card.find(class_=lambda c: c and "price" in c.lower())
                    if not price_el:
                        price_el = card.find(string=lambda t: t and "$" in t and "/" in t)
                    price_text = price_el.get_text(strip=True) if price_el else ""
                    price = int("".join(filter(str.isdigit, price_text.split("/")[0]))) if price_text else 0

                    # Beds/Baths
                    beds_el = card.find(class_=lambda c: c and "bed" in c.lower())
                    beds_text = beds_el.get_text(strip=True) if beds_el else "0"
                    beds = int("".join(filter(str.isdigit, beds_text.split(" ")[0]))) if beds_text else 0

                    baths_el = card.find(class_=lambda c: c and "bath" in c.lower())
                    baths_text = baths_el.get_text(strip=True) if baths_el else "0"
                    baths = int("".join(filter(str.isdigit, baths_text.split(" ")[0]))) if baths_text else 0

                    # Sqft
                    sqft_el = card.find(class_=lambda c: c and "sqft" in c.lower() or "ft" in c.lower())
                    sqft_text = sqft_el.get_text(strip=True) if sqft_el else ""
                    sqft = int("".join(filter(str.isdigit, sqft_text))) if sqft_text else None

                    # Neighborhood / address
                    addr_el = card.find(class_=lambda c: c and ("address" in c.lower() or "neighborhood" in c.lower() or "location" in c.lower()))
                    neighborhood = addr_el.get_text(strip=True) if addr_el else "Toronto"

                    # Listing age (days posted)
                    age_el = card.find(class_=lambda c: c and ("day" in c.lower() or "hour" in c.lower() or "new" in c.lower() or "ago" in c.lower()))
                    age_text = age_el.get_text(strip=True) if age_el else "3 days ago"
                    days_ago = 3  # default
                    for num_word in ["1", "one", "2", "two", "3", "three", "5", "five", "7", "seven", "14"]:
                        if num_word in age_text.lower():
                            days_ago = int("".join(filter(str.isdigit, age_text)))
                            break

                    if price > 500:  # filter junk
                        listings.append({
                            "source": "Zumper",
                            "price": price,
                            "beds": beds,
                            "baths": baths,
                            "sqft": sqft,
                            "neighborhood": neighborhood[:60],
                            "days_ago": days_ago,
                            "link": href,
                        })
                except Exception:
                    continue

            print(f"  Zumper page {page}: got {len(listings)} total listings so far")
        except Exception as e:
            print(f"  Zumper page {page} error: {e}")
            continue

    return pd.DataFrame(listings)


def _clamp_beds(v: float) -> int:
    """Clamp beds to valid range 0-10, treating 0 as studio."""
    v = int(v)
    if v < 0:
        return 0
    if v > 10:
        return 0  # garbled value like "12980286bed" → treat as unknown
    return v


def _clamp_baths(v: float) -> float:
    """Clamp baths to valid range 0-6 (realistic bathroom counts).
    Rejects garbage like 2.51, 11, 21 extracted from prices/addresses."""
    v = float(v)
    if v < 0.5 or v > 6:
        return 0
    return round(v, 1)


def _save_raw(listings, date_str: str):
    """Save raw scraped listings to rent_finder/data/raw_YYYY-MM-DD.json."""
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"raw_{date_str}.json")
    data = [{
        "listing_id": lst.listing_id,
        "title": lst.title,
        "price": lst.price,
        "price_str": lst.price_str,
        "location": lst.location,
        "beds_raw": lst.beds,
        "baths_raw": lst.baths,
        "url": lst.url,
        "image_url": lst.image_url,
    } for lst in listings]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Raw listings saved: {path}")


def scrape_kijiji(pages=5) -> pd.DataFrame:
    """
    Scrape Toronto rental listings from Kijiji.
    Uses the apartment-for-rent subcategory with HTML SSR card parsing (MC-246).
    """
    import scrape_kijiji as _kj
    import re as _re

    all_listings = []
    date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        listings = _kj.scrape(pages=pages)
        print(f"  Kijiji: got {len(listings)} total listings")
        # Save raw listings BEFORE any processing (AC3)
        _save_raw(listings, date_str)
        for lst in listings:
            # Parse beds/baths from text fields like "2 bedbd" or "002 BEDbd"
            beds_raw = lst.beds or ""
            baths_raw = lst.baths or ""
            # Validate extracted numbers are in sane range
            beds_num = 0
            if _re.search(r"\d+", beds_raw):
                try:
                    beds_num = _clamp_beds(float(_re.search(r"\d+", beds_raw).group()))
                except (ValueError, AttributeError):
                    beds_num = 0
            baths_num = 0.0
            if _re.search(r"\d+(?:\.\d+)?", baths_raw):
                try:
                    baths_num = _clamp_baths(float(_re.search(r"\d+(?:\.\d+)?", baths_raw).group()))
                except (ValueError, AttributeError):
                    baths_num = 0.0

            # Neighborhood = location part before first comma, or full location
            neighborhood = lst.location.split(",")[0].strip() if lst.location else "Toronto"

            all_listings.append({
                "source": "Kijiji",
                "price": int(lst.price),
                "beds": beds_num,
                "baths": baths_num,
                "sqft": None,
                "neighborhood": neighborhood[:60],
                "days_ago": getattr(lst, 'days_ago', 5),
                "is_stale": getattr(lst, 'is_stale', False),
                "link": lst.url,
            })
    except Exception as e:
        print(f"  Kijiji error: {e}")

    return pd.DataFrame(all_listings)


def scrape_craigslist(pages: int = 5) -> pd.DataFrame:
    """Scrape Toronto rental listings from Craigslist. MC-258."""
    import scrape_craigslist as _cl

    all_listings = []
    try:
        listings = _cl.scrape(pages=pages)
        print(f"  Craigslist: got {len(listings)} total listings")
        for lst in listings:
            try:
                beds_num = int(float(lst.beds)) if lst.beds not in (None, "") else 0
            except (ValueError, TypeError):
                beds_num = 0
            try:
                baths_num = float(lst.baths) if lst.baths not in (None, "") else 0.0
            except (ValueError, TypeError):
                baths_num = 0.0
            all_listings.append({
                "source": "Craigslist",
                "price": int(lst.price),
                "beds": beds_num,
                "baths": baths_num,
                "sqft": None,
                "neighborhood": lst.location[:60] if lst.location else "Toronto",
                "days_ago": lst.days_ago,
                "is_stale": lst.is_stale,
                "link": lst.url,
            })
    except Exception as e:
        print(f"  Craigslist error: {e}")
    return pd.DataFrame(all_listings)


# ── Sample Data Fallback ────────────────────────────────────────────────────────

def sample_data() -> pd.DataFrame:
    """
    Generate 60 realistic Toronto rental listings for testing.
    Based on actual 2025 Toronto market rates.
    """
    import random
    random.seed(42)
    np.random.seed(42)

    neighborhoods = [
        "Downtown Toronto", "Liberty Village", "Queen West", "Yorkville",
        "Financial District", "King West", "Distillery District", "St. James Town",
        "Regent Park", "Corktown", "Leslieville", "Riverdale", "The Beaches",
        "High Park", "Roncesvalles", "Parkdale", "Queen West", "Little Italy",
        "Kensington Market", "Annex", "Dufferin Grove", "Ossington", "Bathurst Manor",
        "Willowdale", "Bayview Village", "Don Mills", " Flemingdon Park", "Victoria Village",
        "Etobicoke Centre", "The Kingsway", "Mimico", "Long Branch",
        "North York", "Scarborough Town Centre", "Agincourt", "Milliken",
        "Markham Road", "Steeles", "Woodbine", "Eglinton East",
    ]

    data = []
    # 1BR: $1800-$2500 (fair ~$2150 avg)
    # 2BR: $2400-$3500 (fair ~$2900 avg)
    # 3BR: $3200-$4500 (fair ~$3700 avg)

    configs = [
        (1, 1850, 2500),  # 1BR
        (1, 1750, 2100),  # 1BR slightly cheaper
        (2, 2400, 3100),  # 2BR
        (2, 2350, 2700),  # 2BR cheaper area
        (3, 3200, 4000),  # 3BR
    ]

    for beds, min_p, max_p in configs:
        for _ in range(12):
            fair_price = (min_p + max_p) // 2
            # Some are overpriced, some underpriced
            discount = random.uniform(-0.15, 0.20)  # -15% to +20% from fair
            price = int(fair_price * (1 + discount))
            # Round to nearest 25
            price = (price // 25) * 25

            neighborhood = random.choice(neighborhoods)
            sqft = random.choice([None, 550, 650, 750, 800, 900, 950, 1100])
            days_ago = random.randint(1, 30)

            data.append({
                "source": "Sample",
                "price": price,
                "beds": beds,
                "baths": beds,
                "sqft": sqft,
                "neighborhood": neighborhood,
                "days_ago": days_ago,
                "link": f"https://www.zumper.com/apartment/sample-{len(data)}",
            })

    df = pd.DataFrame(data)
    return df


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_deals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Score deals: excess = (fair - price) / fair.
    Higher score = more underpriced.
    Boost for fresh listings.
    Excludes stale (>30 days) listings from fair value and scoring.
    """
    df = df.copy()

    # Separate active vs stale
    is_stale_col = "is_stale" in df.columns
    if is_stale_col:
        active = df[~df["is_stale"]].copy()
        stale = df[df["is_stale"]].copy()
    else:
        active = df.copy()
        stale = pd.DataFrame()

    # Fair value: computed from active listings only (not stale)
    if len(active) == 0:
        df["fair_value"] = np.nan
        df["pct_under"] = np.nan
        df["score"] = np.nan
        df["freshness_boost"] = np.nan
        df["final_score"] = np.nan
        return df

    fair = active.groupby(["neighborhood", "beds"])["price"].transform("mean")
    active["fair_value"] = fair

    # If no group data, use global median by beds
    active["fair_value"] = active["fair_value"].fillna(
        active.groupby("beds")["price"].transform("median")
    )

    # % under market
    active["pct_under"] = (active["fair_value"] - active["price"]) / active["fair_value"] * 100

    # Base score: 0–1 scale (max pct_under observed)
    max_under = active["pct_under"].max()
    if max_under > 0:
        active["score"] = active["pct_under"] / max_under
    else:
        active["score"] = 0.0

    # Freshness boost: < 7 days -> +0.1, < 14 days -> +0.05
    active["freshness_boost"] = active["days_ago"].apply(
        lambda d: 0.15 if d <= 5 else (0.08 if d <= 14 else 0.0)
    )

    # Final score
    active["final_score"] = active["score"] + active["freshness_boost"]

    # Rank
    active = active.sort_values("final_score", ascending=False).reset_index(drop=True)
    active["rank"] = range(1, len(active) + 1)

    # Stale listings: fair_value and score remain NaN (not scored)
    if len(stale) > 0:
        stale["fair_value"] = np.nan
        stale["pct_under"] = np.nan
        stale["score"] = np.nan
        stale["freshness_boost"] = np.nan
        stale["final_score"] = np.nan
        stale["rank"] = np.nan

    df = pd.concat([active, stale], ignore_index=True)

    return df


# ── Commute Time (OpenRouteService + Nominatim fallback) ───────────────────────

# Known destination shortcuts (avoid API calls for common Toronto locations)
KNOWN_DESTINATIONS = {
    "union station": (43.6455, -79.3833),
    "union station, toronto": (43.6455, -79.3833),
    "toronto union station": (43.6455, -79.3833),
    "king station": (43.6475, -79.3791),
    "billy bishop airport": (43.6275, -79.0951),
    "st. michael's hospital": (43.6547, -79.3737),
    "sick kids hospital": (43.6537, -79.3903),
    "u of t": (43.6629, -79.3958),
    "ryerson university": (43.6577, -79.3833),
    "yonge and bay": (43.6707, -79.3864),
    "yonge and dundas": (43.6561, -79.3802),
}


def geocode_address(address: str, api_key: str) -> tuple:
    """
    Geocode an address string to (lat, lon) using Nominatim (no API key needed)
    and/or OpenRouteService. Returns None on failure.
    """
    addr_lower = address.lower().strip()
    if addr_lower in KNOWN_DESTINATIONS:
        return KNOWN_DESTINATIONS[addr_lower]

    # Try Nominatim first (no key required, rate-limited to 1/sec)
    try:
        import time
        time.sleep(1.1)  # Respect Nominatim rate limit
        nom_url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": address + ", Toronto, ON",
            "format": "json",
            "limit": "1",
            "accept-language": "en",
        }
        headers = {"User-Agent": "RentFinderBot/1.0 (toronto-rent-deals)"}
        resp = requests.get(nom_url, params=params, headers=headers, timeout=15)
        data = resp.json()
        if data:
            return (float(data[0]["lat"]), float(data[0]["lon"]))
    except Exception:
        pass

    # Fallback: ORS geocoding
    try:
        url = "https://api.openrouteservice.org/geocode/v1/search"
        headers = {"Authorization": api_key}
        params = {
            "text": address,
            "size": 1,
            "lang": "en",
            "filters": {"place_type": "locality", "locality": "Toronto"},
        }
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        data = resp.json()
        if data.get("features"):
            coords = data["features"][0]["geometry"]["coordinates"]
            return (coords[1], coords[0])
    except Exception:
        pass

    return None


def compute_commute_times(df: pd.DataFrame, dest_lat: float, dest_lon: float,
                          api_key: str, profile: str = "foot-walking") -> pd.DataFrame:
    """
    Compute walking commute time (minutes) from each listing's neighbourhood
    centroid to dest_lat/dest_lon using OpenRouteService or Haversine fallback.
    Adds 'commute_minutes' column to df.
    """
    from neighbourhood_coords import neighbourhood_centroid
    import math, time

    # Try ORS directions; on failure fall back to Haversine estimate
    use_ors = bool(api_key)
    if use_ors:
        try:
            # Quick ORS auth check
            test_url = f"https://api.openrouteservice.org/v2/directions/{profile}"
            test_resp = requests.get(
                test_url,
                headers={"Authorization": api_key},
                params={"start": "-79.3835,43.6515", "end": "-79.3835,43.6515"},
                timeout=10,
            )
            use_ors = test_resp.status_code != 401
        except Exception:
            use_ors = False

    commute_mins = []
    for _, row in df.iterrows():
        centroid = neighbourhood_centroid(str(row.get("neighborhood", "")))
        if centroid is None:
            centroid = (43.6515, -79.3835)
        src_lat, src_lon = centroid

        if use_ors:
            try:
                url = f"https://api.openrouteservice.org/v2/directions/{profile}"
                params = {"start": f"{src_lon},{src_lat}", "end": f"{dest_lon},{dest_lat}"}
                resp = requests.get(url, headers={"Authorization": api_key}, params=params, timeout=15)
                data = resp.json()
                if data.get("routes"):
                    duration_sec = data["routes"][0]["summary"]["duration"]
                    commute_mins.append(round(duration_sec / 60, 1))
                    time.sleep(1.1)  # Rate limit
                    continue
            except Exception:
                pass

        # Haversine fallback: straight-line / 5 km/h walking
        R = 6371
        dlat = math.radians(dest_lat - src_lat)
        dlon = math.radians(dest_lon - src_lon)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(src_lat)) * math.cos(math.radians(dest_lat)) *
             math.sin(dlon / 2) ** 2)
        dist_km = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        est_mins = round(dist_km / 5 * 60, 1)
        commute_mins.append(est_mins)

    df = df.copy()
    df["commute_minutes"] = commute_mins
    return df


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    region_filter = args.region
    max_commute = args.max_commute
    destination = args.destination

    print("=" * 80)
    print("  TORONTO RENTAL DEAL FINDER -- MC-245")
    if region_filter:
        print(f"  Region filter: {region_filter}")
    if destination:
        print(f"  Destination: {destination}")
    print("=" * 80)
    print()

    # Step 1: Collect listings
    print("[1] Collecting Toronto rental listings...")
    print("-" * 40)

    sources_tried = []
    df_kijiji = None

    # Kijiji (primary — 5 pages = ~200 listings)
    try:
        sources_tried.append("Kijiji")
        df_kijiji = scrape_kijiji(pages=5)
        print(f"  Kijiji: got {len(df_kijiji)} listings")
    except Exception as e:
        print(f"  Kijiji scrape failed: {e}")
        df_kijiji = pd.DataFrame()

    # Craigslist (secondary — MC-258)
    df_cl = pd.DataFrame()
    try:
        sources_tried.append("Craigslist")
        df_cl = scrape_craigslist(pages=5)
        print(f"  Craigslist: got {len(df_cl)} listings")
    except Exception as e:
        print(f"  Craigslist scrape failed: {e}")

    # Fallback: sample data if too few listings from both real sources
    if len(df_kijiji) < 30:
        sources_tried.append("Sample")
        print(f"  Kijiji returned {len(df_kijiji)} < 30; generating sample data...")

        import random
        random.seed(42)
        np.random.seed(42)
        neighborhoods = [
            "Downtown Toronto", "Liberty Village", "Queen West", "Yorkville",
            "Financial District", "King West", "Distillery District", "St. James Town",
            "Corktown", "Leslieville", "Riverdale", "The Beaches", "High Park",
            "Roncesvalles", "Parkdale", "Little Italy", "Kensington Market", "Annex",
            "Ossington", "Willowdale", "Bayview Village", "Don Mills",
            "Etobicoke Centre", "Mimico", "Long Branch", "North York",
            "Scarborough Town Centre", "Agincourt", "Milliken", "Steeles", "Woodbine",
        ]
        configs = [
            (1, 1900, 2500), (2, 2450, 3300), (3, 3200, 4300), (0, 1500, 2200),
        ]
        sample_rows = []
        for beds, lo, hi in configs:
            for _ in range(14):
                fair = (lo + hi) // 2
                discount = random.uniform(-0.18, 0.22)
                price = int((fair * (1 + discount)) // 25 * 25)
                nb = random.choice(neighborhoods)
                sample_rows.append({
                    "source": "Sample",
                    "price": price, "beds": beds, "baths": max(1, beds),
                    "sqft": random.choice([None, 550, 700, 800, 900, 1050]),
                    "neighborhood": nb,
                    "days_ago": random.randint(1, 30),
                    "link": "https://example.com/listing",
                })
        df_sample = pd.DataFrame(sample_rows)
        df = df_sample
    else:
        # Combine Kijiji + Craigslist
        frames = [df_kijiji, df_cl]
        df = pd.concat(frames, ignore_index=True)

        # Cross-source deduplication: hash (price, beds, neighbourhood_lower)
        # Listings within ~5% price and same beds/neighbourhood are considered duplicates
        if len(df) > 0:
            df["_nb_norm"] = df["neighborhood"].str.lower().str.strip()
            df["_dedup_key"] = (
                df["beds"].astype(str) + "|" +
                df["_nb_norm"] + "|" +
                (df["price"] // 50 * 50).astype(str)  # round to nearest $50
            )
            df = df.drop_duplicates(subset=["_dedup_key"]).reset_index(drop=True)
            df = df.drop(columns=["_nb_norm", "_dedup_key"])

    df = df[df["price"] > 800].copy()
    df = df.drop_duplicates(subset=["link"]).reset_index(drop=True)

    # Filter stale listings (Kijiji activationDate is often 60+ days old)
    df = df[df["days_ago"] <= 30].reset_index(drop=True)
    print(f"\n  Total listings: {len(df)} | Sources: {sources_tried}")

    # ── Dataset Preview (BEFORE scoring) ─────────────────────────────────────
    print()
    print("=" * 80)
    print("  [2] DATASET PREVIEW -- Before Scoring")
    print("=" * 80)
    print()
    preview = df[["source", "price", "beds", "baths", "sqft", "neighborhood", "days_ago", "link"]].copy()
    print(preview.to_string(index=False))
    print()
    print(f"  Price range: ${df['price'].min():,} - ${df['price'].max():,} | Median: ${df['price'].median():,.0f}")
    print(f"  Beds: {sorted(df['beds'].unique())} | Neighborhoods: {df['neighborhood'].nunique()}")

    # Step 3: Score
    print()
    print("=" * 80)
    print("  [3] DEAL SCORING")
    print("=" * 80)
    print()

    scored = score_deals(df)

    # Add region column
    from region_map import neighbourhood_to_region
    scored["region"] = scored["neighborhood"].apply(neighbourhood_to_region)

    # Compute commute times if destination provided
    if destination and max_commute:
        print()
        print(f"  Computing commute times to '{destination}'...")
        api_key = os.environ.get("ORS_API_KEY", "")
        if api_key:
            dest_coords = geocode_address(destination, api_key)
            if dest_coords:
                dest_lat, dest_lon = dest_coords
                scored = compute_commute_times(scored, dest_lat, dest_lon, api_key)
                print(f"  Commute times computed for {scored['commute_minutes'].notna().sum()} listings.")
            else:
                print("  Geocoding destination failed — skipping commute filter.")
        else:
            print("  ORS_API_KEY not set — skipping commute computation.")

    # Apply region filter if specified
    if region_filter:
        scored = scored[scored["region"] == region_filter].reset_index(drop=True)
        scored["rank"] = range(1, len(scored) + 1)

    # Apply max commute filter if specified
    if destination and max_commute and "commute_minutes" in scored.columns:
        before = len(scored)
        scored = scored[scored["commute_minutes"].notna() & (scored["commute_minutes"] <= max_commute)].reset_index(drop=True)
        scored["rank"] = range(1, len(scored) + 1)
        print(f"  Commute filter ({max_commute} min): {before} -> {len(scored)} listings")

    top = scored.head(10).copy()
    top["fair_value"] = top["fair_value"].round(0).astype(int)
    top["pct_under"] = top["pct_under"].round(1)
    top["final_score"] = top["final_score"].round(3)

    # Build output line with commute if available
    for _, row in top.iterrows():
        sqft_str = f"{row['sqft']:,}" if pd.notna(row["sqft"]) else "-"
        comm_str = f" | {row['commute_minutes']:.0f}min" if pd.notna(row.get("commute_minutes")) else ""
        stale_str = " [STALE]" if row.get("is_stale") else ""
        print(f"  {row['rank']:<3} ${row['price']:>7,} ${row['fair_value']:>7,} {row['pct_under']:>+6.1f}% {str(row['neighborhood'])[:30]:<30} {row['beds']:>3} {str(row['region']):<12}{comm_str}{stale_str} {row['final_score']:>6.3f}  {row['link'][:55]}")

    # ── SQLite Persistence (MC-262) ─────────────────────────────────────────────
    try:
        from persist import upsert_listings
        scored_rows = scored.rename(columns={
            "neighborhood": "neighborhood",
            "link": "url",
        }).to_dict("records")
        for r in scored_rows:
            r["listing_id"] = r.get("link", "") or r.get("listing_id", "")
        stats = upsert_listings(scored_rows, scored)
        print(f"\n  SQLite: {stats['total_active']} active listings, {stats['inactive_this_run']} marked inactive")

        # MC-263: check alerts after each scrape run
        try:
            from persist import check_and_send_alerts
            alert_results = check_and_send_alerts()
            print(f"\n  Alerts: {alert_results['sent']} sent, {alert_results['skipped_rate_limit']} rate-limited, "
                  f"{alert_results['skipped_no_matches']} no matches, {alert_results['errors']} errors "
                  f"(checked {alert_results['checked']} alerts)")
        except Exception as e:
            print(f"\n  Alerts check skipped: {e}")
    except Exception as e:
        print(f"\n  SQLite persistence skipped: {e}")

    # Save
    out_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(out_dir, "deals_output.csv")
    scored.to_csv(csv_path, index=False)

    underpriced = scored[scored["pct_under"] > 0]
    print()
    print(f"  Saved {len(scored)} listings -> {csv_path}")
    pct_under = f"{len(underpriced)/len(scored)*100:.0f}%" if len(scored) > 0 else "0%"
    print(f"  Under market: {len(underpriced)}/{len(scored)} ({pct_under})")
    if scored.empty:
        print("  No deals found for this region.")
    else:
        best = scored.iloc[0]
        best_pct = f"{best['pct_under']:+.1f}%" if best['pct_under'] > 0 else f"{best['pct_under']:.1f}%"
        print(f"  BEST DEAL: {best['neighborhood']} {best['beds']}BR @ ${best['price']:,} ({best_pct} under market, score={best['final_score']:.3f})")
    # ── Post to Discord ───────────────────────────────────────────────────────
    try:
        import tempfile, subprocess, json as _json

        underpriced = scored[scored["pct_under"] > 0]
        top3 = scored.head(3) if len(scored) >= 3 else scored

        if top3.empty:
            raise ValueError("no deals to post")

        medal = ["🥇", "🥈", "🥉"]
        lines = [
            f"🏠 **Toronto Rent Deals** — {datetime.now().strftime('%B %d, %Y')}",
            f"📊 *{len(scored)} listings scanned | {len(underpriced)} deals under market*",
            "",
        ]
        for _, row in top3.iterrows():
            emoji = medal[row["rank"] - 1]
            pct = f"+{row['pct_under']:.1f}%" if row['pct_under'] > 0 else f"{row['pct_under']:.1f}%"
            bed_str = f"{row['beds']}BR" if row['beds'] > 0 else "Studio"
            sqft_str = f" | {int(row['sqft']):,}ft²" if pd.notna(row.get("sqft")) and row.get("sqft", 0) > 10 else ""
            age_str = f" ({row['days_ago']}d ago)" if row.get("days_ago", 0) <= 7 else ""
            lines.append(
                f"{emoji} **{row['neighborhood']}** {bed_str} @ **${row['price']:,}/mo**"
                f" | {pct} under FV ${int(row['fair_value']):,}{sqft_str}{age_str}"
            )
            lines.append(f"   🔗 {row['link']}")
            lines.append("")

        msg = "\n".join(lines)
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
        tmp.write(msg); tmp.close()

        # Use openclaw message with PowerShell redirect to avoid -Raw issues
        ps_cmd = f"$Content = Get-Content -Path '{tmp.name}' -Raw; openclaw message send --channel discord --target 1485371628538822898 --account carl --message $Content"
        cmd = ["powershell", "-NoProfile", "-Command", ps_cmd]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        os.unlink(tmp.name)
        if result.returncode == 0:
            print("  Discord: posted top 3 deals.")
        else:
            print(f"  Discord: post skipped ({result.stderr.strip() or result.stdout.strip() or 'no webhook'}).")
    except Exception as e:
        print(f"  Discord: post skipped ({e}).")

    print("=" * 80)


if __name__ == "__main__":
    main()