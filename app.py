"""
Toronto Rent Deal Finder — Flask Web App
MC-262: Serves deals from SQLite (listings.db) with browsable, filterable UI.
MC-267/268/270: POI proximity — grocery, gym, TTC via Overpass + ORS.
"""

import os, sys, json, time, hashlib, math
from flask import Flask, render_template, jsonify, request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'listings.db')
DEALS_CSV = os.path.join(APP_DIR, 'deals_output.csv')

app = Flask(__name__, template_folder=os.path.join(APP_DIR, 'templates'))

# Ensure data dir and DB schema exist on startup (important for Render cold boots)
os.makedirs(DATA_DIR, exist_ok=True)
try:
    from persist import init_db
    init_db()
except Exception:
    pass


def _days_ago_str(days_ago: int) -> str:
    if days_ago is None:
        return '—'
    if days_ago == 0:
        return 'TODAY'
    if days_ago == 1:
        return '1d ago'
    if days_ago <= 7:
        return f'{days_ago}d ago'
    return f'{days_ago}d'


# MC-267: POI proximity cache (neighbourhood => grocery store info)
def _load_poi_cache() -> dict:
    cache_path = os.path.join(DATA_DIR, 'poi_cache.json')
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _days_ago_class(days_ago: int) -> str:
    """CSS class for color coding: green <=3, yellow 4-14, red >14."""
    if days_ago is None:
        return 'age-neutral'
    if days_ago <= 3:
        return 'age-fresh'
    if days_ago <= 14:
        return 'age-medium'
    return 'age-stale'


# MC-267/268/270: POI walk time thresholds (imported from poi.py to avoid circular imports)
MAX_GROCERY_WALK_MIN = 20  # overridden after poi import
MAX_GYM_WALK_MIN = 30
MAX_STATION_WALK_MIN = 20
MAX_PARKING_WALK_MIN = 15  # MC-269


_ROOM_RENTAL_KEYWORDS = (
    'room in', 'private room', 'master bedroom', 'bedroom in',
    'looking for', 'roommate', 'room for rent', '1 room', 'one room',
    'shared', 'room only',
)


def _is_room_rental(d: dict) -> bool:
    title = (d.get('title') or '').lower()
    return any(kw in title for kw in _ROOM_RENTAL_KEYWORDS)


def _compute_cautions(d: dict) -> list[str]:
    """
    MC-255: Compute caution flags for a listing.
    Returns list of caution strings.
    """
    cautions = []
    pct_under = d.get('pct_under', 0)

    # Room rental detection — must run before price cautions to avoid false positives
    if _is_room_rental(d):
        cautions.append('Possible room rental — confirm it\'s a full unit')

    if pct_under is not None and pct_under > 20:
        cautions.append('Unusually cheap — verify condition')
    if pct_under is not None and pct_under > 40:
        cautions.append('Extremely cheap — likely room rental, scam, or data error')
    days_ago = d.get('days_ago')
    if days_ago is not None and days_ago > 30:
        cautions.append('Listing may be stale')
    sqft = d.get('sqft', '')
    if sqft is None or str(sqft).strip() in ('', 'None', 'nan'):
        cautions.append('Size not disclosed')
    price = d.get('price', 0)
    beds = d.get('beds')
    region = d.get('region', '').lower()
    # Below-typical basement threshold for 1BR downtown
    if beds == 1 and price < 1100 and 'downtown' in region:
        cautions.append('Below typical basement threshold')
    # MC-267: No grocery store nearby warning
    walk_min = d.get('grocery_walk_min')
    if walk_min is not None and walk_min > MAX_GROCERY_WALK_MIN:
        cautions.append('No grocery store nearby')

    # MC-268: No gym nearby when listing has no in-building gym
    has_gym = d.get('has_gym', False)
    if not has_gym:
        gym_walk = d.get('gym_walk_min')
        if gym_walk is not None and gym_walk > MAX_GYM_WALK_MIN:
            cautions.append('No gym nearby (none in building)')

    # MC-270: No TTC station within 20 min walk
    station_walk = d.get('station_walk_min')
    if station_walk is not None and station_walk > MAX_STATION_WALK_MIN:
        cautions.append('No TTC station within 20 min walk')

    # MC-269: No nearby parking when listing has no included parking
    has_parking = d.get('has_parking', False)
    if not has_parking:
        parking_walk = d.get('parking_walk_min')
        if parking_walk is None or parking_walk > MAX_PARKING_WALK_MIN:
            cautions.append('No nearby parking available')

    return cautions


def _normalize_row(r: dict) -> dict:
    """Normalize a listing dict to the format expected by the UI."""
    try:
        price = float(r.get('price') or 0)
        fair_value = float(r.get('fair_value') or 0)
        pct_under = float(r.get('pct_under') or 0)
        final_score = float(r.get('score') or r.get('final_score') or 0)
        beds_raw = r.get('beds', '')
        beds = int(float(beds_raw)) if str(beds_raw) not in ('', 'None', 'nan') else None
        baths_raw = r.get('baths', '')
        baths = float(baths_raw) if str(baths_raw) not in ('', 'None', 'nan', '0', '0.0') else None
        is_stale_raw = str(r.get('is_stale', '')).strip().lower()
        is_stale = is_stale_raw in ('true', '1', 'yes', '1.0', '1')
        is_new_raw = str(r.get('is_new', '')).strip()
        is_new = is_new_raw in ('true', '1', 'yes', '1.0', '1', '1')
        days_ago_raw = r.get('days_ago', '')
        days_ago = int(float(days_ago_raw)) if str(days_ago_raw) not in ('', 'None', 'nan') else None
        row_dict = {
            'listing_id': r.get('listing_id') or r.get('url') or r.get('link', ''),
            'title': r.get('title', ''),
            'neighbourhood': r.get('neighborhood', ''),
            'region': r.get('region', ''),
            'beds': beds,
            'baths': baths,
            'price': price,
            'price_fmt': f"${price:,.0f}",
            'fair_value_fmt': f"${fair_value:,.0f}" if fair_value else '—',
            'pct_under': round(pct_under, 1),
            'pct_under_fmt': f"{pct_under:.1f}%",
            'days_ago': days_ago,
            'days_ago_str': _days_ago_str(days_ago),
            'days_ago_class': _days_ago_class(days_ago),
            'is_stale': is_stale,
            'is_new': is_new,
            'sqft': r.get('sqft', ''),
            'commute_minutes': float(r['commute_minutes']) if r.get('commute_minutes', '') not in ('', 'None', 'nan', None) else None,
            'link': r.get('url') or r.get('link', ''),
            'final_score': round(final_score, 3) if final_score else 0,
        }
        # MC-267: Enrich with grocery store proximity from poi_cache
        poi_cache = _load_poi_cache()
        neighbourhood_raw = r.get('neighborhood', '')
        if neighbourhood_raw:
            cache_key = f"{neighbourhood_raw}|supermarket"
            poi = poi_cache.get(cache_key)
            if poi:
                row_dict['grocery_name'] = poi.get('store_name', '')
                row_dict['grocery_walk_min'] = poi.get('walk_minutes')
                row_dict['grocery_dist_m'] = poi.get('distance_m')
            else:
                row_dict['grocery_name'] = None
                row_dict['grocery_walk_min'] = None
                row_dict['grocery_dist_m'] = None
        else:
            row_dict['grocery_name'] = None
            row_dict['grocery_walk_min'] = None
            row_dict['grocery_dist_m'] = None

        # MC-268: Gym POI (leisure=fitness_centre)
        if neighbourhood_raw:
            gym_key = f"{neighbourhood_raw}|fitness_centre"
            gym_poi = poi_cache.get(gym_key)
            if gym_poi:
                row_dict['gym_name'] = gym_poi.get('store_name', '')
                row_dict['gym_walk_min'] = gym_poi.get('walk_minutes')
            else:
                row_dict['gym_name'] = None
                row_dict['gym_walk_min'] = None
        else:
            row_dict['gym_name'] = None
            row_dict['gym_walk_min'] = None

        # MC-270: TTC station POI (station)
        if neighbourhood_raw:
            station_key = f"{neighbourhood_raw}|station"
            station_poi = poi_cache.get(station_key)
            if station_poi:
                row_dict['station_name'] = station_poi.get('store_name', '')
                row_dict['station_walk_min'] = station_poi.get('walk_minutes')
            else:
                row_dict['station_name'] = None
                row_dict['station_walk_min'] = None
        else:
            row_dict['station_name'] = None
            row_dict['station_walk_min'] = None

        # MC-269: Parking POI (amenity=parking)
        if neighbourhood_raw:
            parking_key = f"{neighbourhood_raw}|parking"
            parking_poi = poi_cache.get(parking_key)
            if parking_poi:
                row_dict['parking_name'] = parking_poi.get('store_name', '')
                row_dict['parking_walk_min'] = parking_poi.get('walk_minutes')
            else:
                row_dict['parking_name'] = None
                row_dict['parking_walk_min'] = None
        else:
            row_dict['parking_name'] = None
            row_dict['parking_walk_min'] = None
        row_dict['cautions'] = _compute_cautions(row_dict)
        return row_dict
    except (ValueError, TypeError):
        return None


def load_deals():
    """
    Load active listings from SQLite (MC-262), falling back to CSV.
    """
    # Try SQLite first (MC-262)
    if os.path.exists(DB_PATH):
        try:
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM listings WHERE is_active = 1"
            ).fetchall()
            conn.close()
            if rows:
                deals = []
                for r in rows:
                    d = _normalize_row(dict(r))
                    if d:
                        deals.append(d)
                if deals:
                    return deals
        except Exception:
            pass

    # Fallback to CSV
    import csv
    if not os.path.exists(DEALS_CSV):
        return []
    with open(DEALS_CSV, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    deals = []
    for r in rows:
        d = _normalize_row(r)
        if d:
            deals.append(d)
    return deals


@app.route('/healthz')
def healthz():
    """Lightweight health check for Render free tier cold-start ping."""
    return 'ok', 200


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/deals')
def api_deals():
    deals = load_deals()

    # Parse filter params
    beds_min = request.args.get('beds_min', type=int)
    beds_max = request.args.get('beds_max', type=int)
    baths_min = request.args.get('baths_min', type=float)
    parking = request.args.get('has_parking', type=lambda v: v.lower() == 'true' if v else None)
    price_min = request.args.get('price_min', type=int)
    price_max = request.args.get('price_max', type=int)
    neighbourhood = request.args.get('neighbourhood', '').strip().lower()
    region = request.args.get('region', '').strip()
    sort_by = request.args.get('sort', 'score')
    max_commute = request.args.get('max_commute', type=int)
    max_subway = request.args.get('max_subway', type=int)
    commute_dest = request.args.get('commute_dest', '').strip()
    hide_stale = request.args.get('hide_stale', type=lambda v: v.lower() == 'true' if v else False)

    # Apply filters
    if beds_min is not None:
        deals = [d for d in deals if d['beds'] is not None and d['beds'] >= beds_min]
    if beds_max is not None:
        deals = [d for d in deals if d['beds'] is not None and d['beds'] <= beds_max]
    if baths_min is not None:
        deals = [d for d in deals if d['baths'] is not None and d['baths'] >= baths_min]
    if parking is True:
        deals = [d for d in deals if d['has_parking'] is True]
    if price_min is not None:
        deals = [d for d in deals if d['price'] >= price_min]
    if price_max is not None:
        deals = [d for d in deals if d['price'] <= price_max]
    if neighbourhood:
        deals = [d for d in deals if neighbourhood in d['neighbourhood'].lower()]
    if region:
        deals = [d for d in deals if d.get('region', '') == region]
    if hide_stale:
        deals = [d for d in deals if not d.get('is_stale', False)]
    if max_commute is not None:
        deals = [d for d in deals if d.get('commute_minutes') is not None and d['commute_minutes'] <= max_commute]
        deals.sort(key=lambda d: d.get('commute_minutes', 999))

    # MC-270 AC5: Max subway walk filter
    if max_subway is not None:
        deals = [d for d in deals if d.get('station_walk_min') is not None and d['station_walk_min'] <= max_subway]

    # Sort
    reverse = sort_by not in ('price', 'days_ago')
    key_map = {
        'price': 'price',
        'pct': 'pct_under',
        'score': 'final_score',
        'beds': 'beds',
        'baths': 'baths',
        'days_ago': 'days_ago',
    }
    key = key_map.get(sort_by, 'final_score')
    deals.sort(key=lambda d: d.get(key, 0) if isinstance(d.get(key), (int, float)) else 0, reverse=reverse)

    # MC-261: segment-aware fair value (relative to filtered search results)
    if deals:
        from compute_segment_fv import compute_fair_value_with_fallback
        deals = compute_fair_value_with_fallback(deals)

    return jsonify(deals[:50])


@app.route('/api/meta')
def api_meta():
    """Return min/max ranges derived from actual data for UI slider construction."""
    deals = load_deals()
    if not deals:
        return jsonify({'beds': [], 'price': [0, 0], 'baths': [], 'regions': []})

    beds_vals = sorted(set(d['beds'] for d in deals if d['beds'] is not None))
    price_vals = [min(d['price'] for d in deals), max(d['price'] for d in deals)]
    baths_vals = sorted(set(d['baths'] for d in deals if d['baths'] is not None))
    regions = sorted(set(d.get('region', '') for d in deals if d.get('region', '')))

    return jsonify({
        'beds': beds_vals,
        'price': [int(price_vals[0]), int(price_vals[1])],
        'baths': baths_vals,
        'regions': regions,
    })


@app.route('/api/deals/geo')
def api_deals_geo():
    """
    MC-256: Return deals enriched with lat/lng from neighbourhood centroids.
    Uses get_centroid() for fuzzy matching — no external API calls.
    Returns only listings that have a mappable neighbourhood.
    """
    from neighbourhood_lookup import get_centroid

    deals = load_deals()
    geo_deals = []
    for d in deals:
        coords = get_centroid(d.get('neighbourhood', ''))
        if coords:
            lat, lng = coords
            geo_deals.append({
                'neighbourhood': d.get('neighbourhood', ''),
                'region': d.get('region', ''),
                'beds': d.get('beds'),
                'baths': d.get('baths'),
                'price': d.get('price'),
                'price_fmt': d.get('price_fmt', ''),
                'pct_under': d.get('pct_under', 0),
                'pct_under_fmt': d.get('pct_under_fmt', ''),
                'days_ago': d.get('days_ago'),
                'days_ago_str': d.get('days_ago_str', ''),
                'link': d.get('link', ''),
                'final_score': d.get('final_score', 0),
                'cautions': d.get('cautions', []),
                'commute_minutes': d.get('commute_minutes'),
                'lat': lat,
                'lng': lng,
            })
    return jsonify(geo_deals)


@app.route('/api/deals/export.csv')
def api_export_csv():
    """CSV export endpoint for data users. MC-262."""
    import csv, io
    deals = load_deals()
    output = io.StringIO()
    if not deals:
        output.write("no data\n")
        return output.getvalue(), 200, {"Content-Type": "text/csv"}
    fieldnames = ['neighbourhood', 'region', 'beds', 'baths', 'price', 'price_fmt',
                  'fair_value_fmt', 'pct_under', 'days_ago', 'is_stale', 'cautions',
                  'commute_minutes', 'link', 'final_score']
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(deals)
    return output.getvalue(), 200, {"Content-Type": "text/csv", "Content-Disposition": "attachment; filename=deals.csv"}


# ── MC-259: Listing Detail Page ───────────────────────────────────────────────

@app.route('/api/listing/detail')
def api_listing_detail_by_id():
    """
    Look up a listing by listing_id (stable, survives re-sorts).
    Query param: ?id=<listing_id>
    """
    listing_id = request.args.get('id', '').strip()
    if not listing_id:
        return jsonify({'error': 'id required'}), 400
    deals = load_deals()
    d = next((x for x in deals if x.get('listing_id') == listing_id), None)
    if d is None:
        return jsonify({'error': 'Listing not found'}), 404
    idx = deals.index(d)
    return _build_listing_detail_response(d, idx)


@app.route('/api/listing/<int:listing_idx>')
def api_listing_detail(listing_idx: int):
    """
    MC-259: Return full detail for a single listing by its index in the current
    deal list (0-based). Includes deal breakdown and expanded caution explanations.
    """
    deals = load_deals()
    if listing_idx < 0 or listing_idx >= len(deals):
        return jsonify({'error': 'Listing not found'}), 404
    return _build_listing_detail_response(deals[listing_idx], listing_idx)


def _build_listing_detail_response(d: dict, idx: int):
    breakdown = {
        'listed_price': d['price'],
        'listed_price_fmt': d['price_fmt'],
        'fair_value': d.get('fair_value_fmt', '—'),
        'pct_under': d['pct_under'],
        'pct_under_fmt': d['pct_under_fmt'],
        'deal_score': d.get('final_score', 0),
        'segment': f"{d['beds']}BR in {d['neighbourhood']}, {d.get('region', 'Toronto')}",
    }

    caution_details = {
        'Possible room rental — confirm it\'s a full unit': 'The listing title suggests this may be a single room in a shared unit, not a full apartment. Check the listing description and photos carefully — room rentals are priced per room, making them appear as extreme deals when compared against whole-unit averages.',
        'Extremely cheap — likely room rental, scam, or data error': 'This listing is more than 40% below fair market value. In Toronto, this almost always means it is a room rental, a scam post, or a data scraping error. Do not proceed without verifying the full listing.',
        'Unusually cheap — verify condition': 'This listing is more than 20% below the market median for its segment. Unusually low prices may indicate hidden issues (condition, location, undisclosed problems). Verify the property in person before committing.',
        'Listing may be stale': 'This listing has been active for more than 30 days. It may already be rented or the price may have changed.',
        'Size not disclosed': 'The listing does not disclose square footage. Neighbourhood averages may not be directly comparable.',
        'Below typical basement threshold': 'A 1BR downtown listing under $1,100/mo is unusually cheap. Most basements in Downtown Toronto rent for $1,200–$1,800 for 1BR.',
    }
    expanded_cautions = []
    for c in (d.get('cautions') or []):
        expanded_cautions.append({
            'flag': c,
            'detail': caution_details.get(c, 'Review this listing carefully before contacting the landlord.')
        })

    days = d.get('days_ago')
    if days is None:
        freshness_str = "Listing age unknown"
    elif days == 0:
        freshness_str = "Listed today — very fresh!"
    elif days <= 3:
        freshness_str = f"Listed {days} days ago — fresh listing"
    elif days <= 14:
        freshness_str = f"Listed {days} days ago — normal age"
    elif days <= 30:
        freshness_str = f"Listed {days} days ago — consider verifying availability"
    else:
        freshness_str = f"Listed {days} days ago — likely stale, verify availability"

    return jsonify({
        'idx': idx,
        'listing_id': d.get('listing_id', ''),
        'title': d.get('title', ''),
        'neighbourhood': d.get('neighbourhood'),
        'region': d.get('region'),
        'beds': d.get('beds'),
        'baths': d.get('baths'),
        'sqft': d.get('sqft'),
        'price': d['price'],
        'price_fmt': d['price_fmt'],
        'fair_value_fmt': d.get('fair_value_fmt'),
        'pct_under': d['pct_under'],
        'pct_under_fmt': d['pct_under_fmt'],
        'days_ago': days,
        'days_ago_str': freshness_str,
        'days_ago_class': d.get('days_ago_class', 'age-neutral'),
        'is_stale': d.get('is_stale'),
        'commute_minutes': d.get('commute_minutes'),
        'link': d.get('link'),
        'cautions': expanded_cautions,
        'breakdown': breakdown,
    })


# ── MC-257: Commute Time Helpers ────────────────────────────────────────────

# In-memory cache for this request cycle (avoid redundant ORS calls per request)
_commute_dest_cache: dict = {}

# Persistent file cache keyed by f"nh_lower|dest_lower"
COMMUTE_CACHE_FILE = os.path.join(DATA_DIR, 'commute_cache.json')


def _load_commute_cache() -> dict:
    """Load persistent commute cache from disk."""
    if os.path.exists(COMMUTE_CACHE_FILE):
        try:
            with open(COMMUTE_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_commute_cache(cache: dict):
    """Persist commute cache to disk."""
    try:
        with open(COMMUTE_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f)
    except Exception:
        pass


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance in km between two lat/lon points."""
    R = 6371  # Earth radius km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.asin(math.sqrt(a))


# Known Toronto destination shortcuts (avoid API calls)
_KNOWN_DESTINATIONS = {
    "union station": (43.6455, -79.3833),
    "union station, toronto": (43.6455, -79.3833),
    "toronto union station": (43.6455, -79.3833),
    "king station": (43.6475, -79.3791),
    "yonge and dundas": (43.6561, -79.3802),
    "yonge and bay": (43.6707, -79.3864),
    "billy bishop airport": (43.6275, -79.0951),
    "u of t": (43.6629, -79.3958),
    "st. michael's hospital": (43.6547, -79.3737),
    "sick kids": (43.6537, -79.3903),
}


def _geocode_address(address: str, api_key: str) -> tuple:
    """
    Geocode a Toronto address string to (lat, lon).
    Checks known shortcuts first, then tries Nominatim (no key), then ORS.
    Returns None on failure.
    """
    addr_key = address.lower().strip()
    if addr_key in _KNOWN_DESTINATIONS:
        return _KNOWN_DESTINATIONS[addr_key]

    # Nominatim (no key needed, 1 req/sec rate limit)
    try:
        time.sleep(1.1)
        import requests as _requests
        nom_url = "https://nominatim.openstreetmap.org/search"
        params = {"q": address + ", Toronto, ON", "format": "json", "limit": "1", "accept-language": "en"}
        headers = {"User-Agent": "RentFinderBot/1.0 (scbrock)"}
        resp = _requests.get(nom_url, params=params, headers=headers, timeout=15)
        data = resp.json()
        if data:
            return (float(data[0]["lat"]), float(data[0]["lon"]))
    except Exception:
        pass

    # ORS geocoding fallback
    if api_key:
        try:
            import requests as _requests
            url = "https://api.openrouteservice.org/geocode/v1/search"
            headers = {"Authorization": api_key}
            params = {"text": address, "size": 1, "lang": "en",
                      "filters": {"place_type": "locality", "locality": "Toronto"}}
            resp = _requests.get(url, params=params, headers=headers, timeout=15)
            data = resp.json()
            if data.get("features"):
                coords = data["features"][0]["geometry"]["coordinates"]
                return (coords[1], coords[0])
        except Exception:
            pass

    return None


def _compute_commute_minutes(nbhd_lat: float, nbhd_lon: float,
                              dest_lat: float, dest_lon: float,
                              api_key: str) -> float:
    """
    Compute walking commute time from neighbourhood centroid to destination.
    Uses ORS foot-walking if api_key available, else Haversine estimate.
    Returns minutes (float).
    """
    if api_key:
        try:
            import requests as _requests
            url = "https://api.openrouteservice.org/v2/directions/foot-walking"
            headers = {"Authorization": api_key, "Content-Type": "application/json"}
            body = {"coordinates": [[nbhd_lon, nbhd_lat], [dest_lon, dest_lat]]}
            resp = _requests.post(url, json=body, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                duration_sec = data["routes"][0]["summary"]["duration"]
                return round(duration_sec / 60, 1)
        except Exception:
            pass

    # Fallback: Haversine estimate at 5 km/h walking speed
    dist_km = _haversine(nbhd_lat, nbhd_lon, dest_lat, dest_lon)
    return round(dist_km / 5.0 * 60, 1)


@app.route('/api/commute', methods=['POST'])
def api_commute():
    """
    MC-257: Compute walking commute times from each neighbourhood to a user-specified
    destination, using OpenRouteService. Results cached by neighbourhood+destination.

    POST body: {"destination": "Union Station, Toronto"}
    Returns:  {neighbourhood: {commute_minutes, walk_dist_km, source}, ...}
    """
    import requests as _requests
    data = request.get_json(force=True) or {}
    destination = (data.get('destination') or '').strip()
    if not destination:
        return jsonify({'error': 'destination required'}), 400

    api_key = os.environ.get('ORS_API_KEY', '')

    # Geocode destination
    dest_coords = _geocode_address(destination, api_key)
    if dest_coords is None:
        return jsonify({'error': f'Could not geocode destination: {destination}'}), 400
    dest_lat, dest_lon = dest_coords

    # Load persistent cache
    cache = _load_commute_cache()

    # Get unique neighbourhoods from active listings
    deals = load_deals()
    neighbourhoods = list({d['neighbourhood'] for d in deals if d.get('neighbourhood')})

    # Try to load neighbourhood coords (lazy import to avoid top-level dep)
    try:
        from neighbourhood_coords import neighbourhood_centroid
    except Exception:
        neighbourhood_centroid = None

    results = {}
    cache_dirty = False

    for nbhd in sorted(neighbourhoods):
        cache_key = f"{nbhd.lower()}|{destination.lower()}"
        if cache_key in cache:
            results[nbhd] = cache[cache_key]
            continue

        # Get neighbourhood centroid
        if neighbourhood_centroid:
            coords = neighbourhood_centroid(nbhd)
        else:
            coords = None

        if coords:
            nbhd_lat, nbhd_lon = coords
            minutes = _compute_commute_minutes(nbhd_lat, nbhd_lon, dest_lat, dest_lon, api_key)
            dist_km = round(_haversine(nbhd_lat, nbhd_lon, dest_lat, dest_lon), 2)
            source = 'ors' if api_key else 'estimate'
        else:
            minutes = None
            dist_km = None
            source = 'unavailable'

        entry = {'commute_minutes': minutes, 'walk_dist_km': dist_km, 'source': source}
        results[nbhd] = entry
        cache[cache_key] = entry
        cache_dirty = True

    if cache_dirty:
        _save_commute_cache(cache)

    return jsonify({'destination': destination, 'dest_coords': [dest_lon, dest_lat],
                    'times': results})


@app.route('/api/alerts', methods=['POST'])
def api_alerts_post():
    """
    MC-263: Subscribe to deal alerts.
    POST body: {"email": "user@example.com", "region": "Downtown",
                 "min_beds": 1, "max_price": 2500, "min_score": 0.15}
    Returns: {"success": true, "message": "Alert saved"}
    """
    data = request.get_json(force=True) or {}
    email = (data.get('email') or '').strip()
    if not email or '@' not in email:
        return jsonify({'error': 'valid email required'}), 400

    region = (data.get('region') or '').strip() or None
    min_beds = data.get('min_beds')
    max_price = data.get('max_price')
    min_score = data.get('min_score', 0.10)
    if min_beds is not None:
        try: min_beds = float(min_beds)
        except: min_beds = None
    if max_price is not None:
        try: max_price = float(max_price)
        except: max_price = None
    if min_score is not None:
        try: min_score = float(min_score)
        except: min_score = 0.10

    try:
        from persist import upsert_alert
        upsert_alert(email, region, min_beds, max_price, min_score)
        return jsonify({'success': True, 'message': 'Alert saved'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/alerts/<email>', methods=['DELETE'])
def api_alerts_delete(email):
    """MC-263: One-click unsubscribe — disables alert."""
    import sqlite3
    email = email.strip()
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE user_alerts SET is_enabled = 0 WHERE email = ?", (email,))
        conn.commit()
        rows_changed = conn.total_changes
        conn.close()
        return jsonify({'success': True, 'unsubscribed': rows_changed > 0})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── MC-284: SMS Subscriptions ────────────────────────────────────────────────

@app.route('/api/sms/subscribe', methods=['POST'])
def api_sms_subscribe():
    """
    MC-284: Subscribe to SMS deal alerts.
    POST body: {
        "phone": "+14165551234",
        "email": "user@example.com",
        "max_price": 2500,       -- optional
        "min_beds": 1,          -- optional
        "neighbourhood": "King West"  -- optional substring match
    }
    Returns: {"success": true, "sub_id": 123}
    """
    from sms_alerts import normalize_phone
    data = request.get_json(force=True) or {}
    phone = (data.get('phone') or '').strip()
    email = (data.get('email') or '').strip()
    if not phone or not email or '@' not in email:
        return jsonify({'error': 'valid phone and email required'}), 400

    max_price = data.get('max_price')
    min_beds  = data.get('min_beds')
    neighbourhood = (data.get('neighbourhood') or '').strip() or None

    try:
        normalized = normalize_phone(phone)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    try:
        from persist import upsert_sms_subscription
        sub_id = upsert_sms_subscription(
            phone=normalized,
            email=email,
            max_price=float(max_price) if max_price else None,
            min_beds=float(min_beds) if min_beds else None,
            neighbourhood=neighbourhood
        )
        return jsonify({'success': True, 'sub_id': sub_id, 'phone': normalized})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/sms/subscription/<phone>', methods=['GET'])
def api_sms_subscription_get(phone):
    """MC-284: Get SMS subscription for a phone number."""
    from sms_alerts import normalize_phone
    try:
        normalized = normalize_phone(phone)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    try:
        from persist import get_sms_subscription
        sub = get_sms_subscription(normalized)
        if not sub:
            return jsonify({'error': 'not found'}), 404
        return jsonify(sub)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/sms/subscription/<phone>', methods=['DELETE'])
def api_sms_subscription_delete(phone):
    """MC-284: Unsubscribe from SMS alerts."""
    from sms_alerts import normalize_phone
    try:
        normalized = normalize_phone(phone)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    try:
        from persist import deactivate_sms_subscription
        deactivate_sms_subscription(normalized)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── MC-266: Saved Searches ───────────────────────────────────────────────────

@app.route('/alerts')
def page_alerts():
    """Saved searches / watchlist dashboard (MC-266)."""
    return render_template('alerts.html')


@app.route('/api/saved-searches')
def api_saved_searches_list():
    """
    MC-266: List all saved searches for an email.
    Query param: ?email=user@example.com
    Returns match counts and top match preview.
    """
    email = request.args.get('email', '').strip()
    if not email or '@' not in email:
        return jsonify({'error': 'email required'}), 400

    try:
        from persist import get_saved_searches
        searches = get_saved_searches(email)
        # Normalize top_match rows for JSON serialization
        for s in searches:
            if s.get('top_match'):
                tm = s['top_match']
                s['top_match'] = _normalize_row(tm) if tm else None
        return jsonify({'searches': searches, 'count': len(searches)})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/saved-searches', methods=['POST'])
def api_saved_searches_create():
    """
    MC-266: Create or update a saved search.
    POST body: {
        "email": "user@example.com",
        "name": "My 1BR King West search",
        "beds_min": 1, "beds_max": 1,
        "region": "Downtown",
        "neighbourhood": "King West",
        "max_price": 2500,
        "min_score": 0.15
    }
    """
    data = request.get_json(force=True) or {}
    email = (data.get('email') or '').strip()
    name = (data.get('name') or '').strip()
    if not email or '@' not in email:
        return jsonify({'error': 'email required'}), 400
    if not name:
        return jsonify({'error': 'name required'}), 400

    def _f(v):
        if v is None: return None
        try: return float(v)
        except: return None

    try:
        from persist import upsert_saved_search
        search_id = upsert_saved_search(
            email=email, name=name,
            beds_min=_f(data.get('beds_min')),
            beds_max=_f(data.get('beds_max')),
            baths_min=_f(data.get('baths_min')),
            price_min=_f(data.get('price_min')),
            price_max=_f(data.get('price_max')),
            neighbourhood=data.get('neighbourhood') or None,
            region=data.get('region') or None,
            min_score=_f(data.get('min_score')),
            max_commute=_f(data.get('max_commute')),
            commute_dest=data.get('commute_dest') or None,
        )
        return jsonify({'success': True, 'search_id': search_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/saved-searches/<int:search_id>', methods=['PUT'])
def api_saved_searches_update(search_id: int):
    """
    MC-266: Update a saved search.
    PUT body: same as POST body + ?email=... for ownership check.
    """
    email = request.args.get('email', '').strip()
    if not email:
        return jsonify({'error': 'email required'}), 400

    data = request.get_json(force=True) or {}
    # Merge email into data so upsert can use it
    data['email'] = email

    def _f(v):
        if v is None: return None
        try: return float(v)
        except: return None

    try:
        from persist import upsert_saved_search
        # upsert_saved_search uses (email, name) as the conflict key, not search_id.
        # We update by re-upserting with the same name to update fields.
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'name required for update'}), 400
        upsert_saved_search(
            email=email, name=name,
            beds_min=_f(data.get('beds_min')),
            beds_max=_f(data.get('beds_max')),
            baths_min=_f(data.get('baths_min')),
            price_min=_f(data.get('price_min')),
            price_max=_f(data.get('price_max')),
            neighbourhood=data.get('neighbourhood') or None,
            region=data.get('region') or None,
            min_score=_f(data.get('min_score')),
            max_commute=_f(data.get('max_commute')),
            commute_dest=data.get('commute_dest') or None,
        )
        return jsonify({'success': True, 'search_id': search_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/saved-searches/<int:search_id>', methods=['DELETE'])
def api_saved_searches_delete(search_id: int):
    """
    MC-266: Delete a saved search.
    Query param: ?email=user@example.com (required for ownership check).
    """
    email = request.args.get('email', '').strip()
    if not email:
        return jsonify({'error': 'email required'}), 400

    try:
        from persist import delete_saved_search
        deleted = delete_saved_search(search_id, email)
        if deleted:
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Not found or not yours'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Shortlist / Saved Listings (MC-271) ──────────────────────────────────────

@app.route('/api/saved-listings')
def api_saved_listings_list():
    """
    MC-271: List all saved (shortlisted) listings for an email.
    Query param: ?email=user@example.com
    Returns list of saved listings with listing data.
    """
    email = request.args.get('email', '').strip()
    if not email or '@' not in email:
        return jsonify({'error': 'email required'}), 400
    try:
        from persist import get_saved_listings
        listings = get_saved_listings(email)
        for listing in listings:
            listing['is_saved'] = True  # client-side flag
        return jsonify({'saved_listings': listings, 'count': len(listings)})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/saved-listings', methods=['POST'])
def api_saved_listings_save():
    """
    MC-271: Save a listing to the user's shortlist.
    POST body: {"email": "user@example.com", "listing_id": "abc123", "note": "Love this place"}
    """
    data = request.get_json(force=True) or {}
    email = (data.get('email') or '').strip()
    listing_id = (data.get('listing_id') or '').strip()
    note = (data.get('note') or '').strip() or None
    if not email or '@' not in email:
        return jsonify({'error': 'email required'}), 400
    if not listing_id:
        return jsonify({'error': 'listing_id required'}), 400
    try:
        from persist import upsert_saved_listing
        saved_id = upsert_saved_listing(email, listing_id, note)
        return jsonify({'success': True, 'saved_id': saved_id})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/saved-listings/<int:saved_id>', methods=['DELETE'])
def api_saved_listings_delete(saved_id: int):
    """
    MC-271: Remove a listing from the user's shortlist.
    Query param: ?email=user@example.com (required for ownership check).
    """
    email = request.args.get('email', '').strip()
    if not email:
        return jsonify({'error': 'email required'}), 400
    try:
        from persist import delete_saved_listing
        deleted = delete_saved_listing(saved_id, email)
        if deleted:
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Not found or not yours'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/saved-listings/check')
def api_saved_listings_check():
    """
    MC-271: Check if specific listings are saved for an email.
    Query params: ?email=x&listing_ids=id1,id2,id3
    Returns dict {listing_id: True/False} for each requested id.
    """
    email = request.args.get('email', '').strip()
    ids_param = request.args.get('listing_ids', '').strip()
    if not email or '@' not in email:
        return jsonify({'error': 'email required'}), 400
    if not ids_param:
        return jsonify({'saved': {}})
    listing_ids = [lid.strip() for lid in ids_param.split(',') if lid.strip()]
    try:
        from persist import is_listing_saved
        result = {lid: is_listing_saved(email, lid) for lid in listing_ids}
        return jsonify({'saved': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/profile', methods=['GET', 'POST'])
def api_profile():
    """
    MC-273: Get or create/update user profile.
    GET ?email=x: returns profile dict
    POST: body JSON with email, preferred_beds, max_price, neighbourhoods[], commute_dest, status
    """
    if request.method == 'GET':
        email = request.args.get('email', '').strip()
        if not email or '@' not in email:
            return jsonify({'error': 'email required'}), 400
        from persist import get_profile
        profile = get_profile(email)
        if profile is None:
            return jsonify({'profile': None})
        return jsonify({'profile': profile})

    # POST
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({'error': 'invalid JSON'}), 400

    email = data.get('email', '').strip()
    if not email or '@' not in email:
        return jsonify({'error': 'valid email required'}), 400

    from persist import upsert_profile
    try:
        upsert_profile(
            email=email,
            preferred_beds=data.get('preferred_beds') or None,
            max_price=float(data['max_price']) if data.get('max_price') not in (None, '') else None,
            neighbourhoods=data.get('neighbourhoods') or None,
            commute_dest=data.get('commute_dest') or None,
            status=data.get('status') or None,
        )
        from persist import get_profile
        return jsonify({'profile': get_profile(email)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/profile')
def page_profile():
    """MC-273: Serve the profile settings page."""
    return render_template('profile.html')


@app.route('/shortlist')
def page_shortlist():
    """MC-274: Serve the shortlist page with 'You might also like' recommendations."""
    return render_template('shortlist.html')


@app.route('/api/price-drops/<email>', methods=['GET'])
def api_price_drops(email: str):
    """
    MC-272: Check for price drops on shortlisted listings.
    GET /api/price-drops/<email>
    Returns: {drops: [{listing_id, address, price_from, price_to, drop_amount}]}
    Optionally triggers email send if ?send=1 query param.
    After each scrape run, call with ?send=1 to notify users of drops.
    """
    from persist import get_shortlisted_listings_with_prices, has_price_drop_alert
    email = email.strip()
    if not email or '@' not in email:
        return jsonify({'error': 'valid email required'}), 400

    shortlisted = get_shortlisted_listings_with_prices(email)
    drops = []
    for item in shortlisted:
        lid = item['listing_id']
        price_at_save = item.get('price_at_save')
        if price_at_save is None:
            continue
        current = item['price']  # current price from JOIN with listings table
        if current is None:
            continue
        if current < price_at_save:
            drops.append({
                'listing_id': lid,
                'address': f"{item.get('neighborhood', 'Unknown')}, Toronto",
                'price_from': price_at_save,
                'price_to': current,
                'drop_amount': price_at_save - current,
                'already_sent': has_price_drop_alert(email, lid),
            })

    send = request.args.get('send', '0') == '1'
    if send and drops:
        from email_alerts import check_and_send_price_drops
        try:
            # Build minimal deal dicts with price + listing_id for check_and_send_price_drops
            deal_dicts = [{'listing_id': d['listing_id'], 'price': d['price_to'],
                           'pct_under': 0, 'score': 0, 'url': '',
                           'neighborhood': d['address']} for d in drops]
            sent = check_and_send_price_drops(deal_dicts, email)
            for d in drops:
                if d['listing_id'] in sent:
                    d['alert_sent'] = True
        except Exception as e:
            return jsonify({'error': f'Failed to send alerts: {e}'}), 500

    return jsonify({'email': email, 'drops': drops, 'count': len(drops)})


# ── MC-282: Price History Chart ──────────────────────────────────────────────

@app.route('/api/price-history')
def api_price_history():
    """
    MC-282: Return price history for a listing.
    GET /api/price-history?id=<listing_id>&days=30
    Returns: {listing_id, count, history: [{ts, price}], trend: "up"|"down"|"stable"}
    """
    from persist import get_price_history
    listing_id = request.args.get('id', '').strip()
    if not listing_id:
        return jsonify({'error': 'id required'}), 400
    days = min(max(int(request.args.get('days', 30)), 1), 90)
    history = get_price_history(listing_id, days=days)
    trend = 'stable'
    if len(history) >= 2:
        delta = history[-1]['price'] - history[0]['price']
        if delta < -0.5:
            trend = 'down'
        elif delta > 0.5:
            trend = 'up'
    return jsonify({
        'listing_id': listing_id,
        'count': len(history),
        'history': history,
        'trend': trend
    })


@app.route('/api/trends')
def api_trends():
    """
    MC-282: Return price trend for all active listings as a dict.
    GET /api/trends
    Returns: {trends: {"<listing_id>": "up"|"down"|"stable"}}
    """
    from persist import get_all_price_trends
    trends = get_all_price_trends(days=30)
    return jsonify({'count': len(trends), 'trends': trends})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)


# ── MC-274: Similar Listing Recommendations ─────────────────────────────────

@app.route('/api/similar/shortlist')
def api_similar_shortlist():
    """
    Return up to 5 listings similar to the user's shortlist.
    Query param: ?email=user@example.com
    """
    email = request.args.get('email', '').strip()
    if not email or '@' not in email:
        return jsonify({'error': 'valid email required'}), 400

    from similar_listings import get_similar_for_shortlist
    try:
        similar = get_similar_for_shortlist(email, limit=5)
        return jsonify({
            'email': email,
            'count': len(similar),
            'recommendations': [
                {
                    'listing_id': s.listing_id,
                    'title': s.title,
                    'price': s.price,
                    'price_fmt': s.price_fmt,
                    'beds': s.beds,
                    'neighbourhood': s.neighbourhood,
                    'url': s.url,
                    'final_score': s.final_score,
                    'similarity_explanation': s.similarity_explanation,
                }
                for s in similar
            ]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/similar/<listing_id>')
def api_similar_listing(listing_id):
    """
    Return up to 3 listings similar to a specific listing (for detail page).
    """
    from similar_listings import get_similar_for_listing
    try:
        similar = get_similar_for_listing(listing_id, limit=3)
        return jsonify({
            'listing_id': listing_id,
            'count': len(similar),
            'recommendations': [
                {
                    'listing_id': s.listing_id,
                    'title': s.title,
                    'price': s.price,
                    'price_fmt': s.price_fmt,
                    'beds': s.beds,
                    'neighbourhood': s.neighbourhood,
                    'url': s.url,
                    'final_score': s.final_score,
                    'similarity_explanation': s.similarity_explanation,
                }
                for s in similar
            ]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# MC-283: Telegram bot webhook — called by cron after each scrape run
@app.route('/api/telegram/webhook', methods=['POST'])
def api_telegram_webhook():
    """
    Called by the scraping cron after each run completes.
    Triggers Telegram deal alerts for all active subscribers.
    Expected payload (optional): {"deals": [...]}  — if absent, fetches from DB
    """
    try:
        deals_data = request.get_json() or {}
    except Exception:
        deals_data = {}

    import os
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not bot_token:
        return jsonify({'ok': False, 'error': 'TELEGRAM_BOT_TOKEN not configured'}), 503

    try:
        from telegram_bot import get_matching_deals_for_telegram, build_alert_message
        from persist import get_active_telegram_subscriptions, update_telegram_last_alerted
        from telegram import Bot
    except ImportError as e:
        return jsonify({'ok': False, 'error': f'Import error: {e}'}), 500

    try:
        bot = Bot(token=bot_token)
        subs = get_active_telegram_subscriptions()
        sent = 0
        errors = 0
        for sub in subs:
            try:
                matches = get_matching_deals_for_telegram(sub, limit=3)
                if not matches:
                    continue
                message = build_alert_message(matches)
                bot.send_message(chat_id=sub['telegram_chat_id'], text=message,
                                 parse_mode='Markdown')
                update_telegram_last_alerted(sub['telegram_chat_id'])
                sent += 1
            except Exception as e:
                errors += 1
        return jsonify({'ok': True, 'subscribers_notified': sent, 'errors': errors})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

