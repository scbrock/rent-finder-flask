"""
Toronto Rent Deal Finder — Flask Web App
MC-262: Serves deals from SQLite (listings.db) with browsable, filterable UI.
MC-267/268/270: POI proximity — grocery, gym, TTC via Overpass + ORS.
"""

import os, sys, json, time, hashlib, math, re
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


# MC-324: days_listed = how long this listing has been on the market.
# Distinct from days_ago (which is "days since the activation/posting date
# we saw on the source page"). days_listed is computed from first_seen in
# SQLite (the durable "when did we first see this listing") and falls back
# to days_ago when SQLite data is unavailable.
#
# Why a separate column: days_listed reflects how long the listing has been
# competing for attention in our database. A listing posted 60 days ago but
# only rediscovered by our scraper last week will have a low days_ago but
# a high days_listed — useful for users who care about how long the unit has
# actually been available, and a stronger signal for "potentially negotiable".
from datetime import datetime, timezone

def _days_listed_from_first_seen(first_seen_raw, now_utc=None):
    """Compute integer days between first_seen ISO timestamp and now (UTC).
    Returns None if first_seen is missing/unparseable, or if the result is
    negative (data corruption guard)."""
    if not first_seen_raw or str(first_seen_raw).strip() in ('', 'None', 'nan'):
        return None
    try:
        # SQLite stores 'YYYY-MM-DDTHH:MM:SSZ' UTC
        ts = str(first_seen_raw).strip()
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        elif '+' not in ts and '-' not in ts[10:]:
            # Naive timestamp — treat as UTC (consistent with persist.py storage)
            ts = ts + '+00:00'
        first_seen_dt = datetime.fromisoformat(ts)
        now = now_utc or datetime.now(timezone.utc)
        if first_seen_dt.tzinfo is None:
            first_seen_dt = first_seen_dt.replace(tzinfo=timezone.utc)
        delta_days = (now - first_seen_dt).days
        # floor at 0 — a delta of -1 from a clock-skewed source means "today"
        return max(0, delta_days)
    except (ValueError, TypeError):
        return None


def _days_listed_str(days_listed) -> str:
    """Human label for the days_listed column (e.g. "3d listed", "30d listed")."""
    if days_listed is None:
        return '—'
    if days_listed == 0:
        return 'today'
    if days_listed == 1:
        return '1d listed'
    return f'{days_listed}d listed'


def _days_listed_class(days_listed) -> str:
    """CSS class for color coding: green <=7, yellow 8-30, red >30."""
    if days_listed is None:
        return 'listed-neutral'
    if days_listed <= 7:
        return 'listed-fresh'
    if days_listed <= 30:
        return 'listed-medium'
    return 'listed-stale'


# ---------------------------------------------------------------------------
# MC-321: Neighborhood stats helpers (slugify, aggregation, lookup)
# ---------------------------------------------------------------------------

_SLUG_STRIP_RE = re.compile(r'[^a-z0-9]+')


def _slugify(name: str) -> str:
    """Lowercase, hyphenate, strip leading/trailing hyphens. ASCII-only.

    "Bay Street Corridor" -> "bay-street-corridor"
    "Niagara (St. Lawrence)" -> "niagara-st-lawrence"
    "" -> ""
    """
    if not name:
        return ''
    s = str(name).strip().lower()
    s = _SLUG_STRIP_RE.sub('-', s).strip('-')
    return s


def _safe_float(v):
    """Return float(v) or None if v is empty/None/non-numeric."""
    if v is None or v == '' or v == 'None' or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _median(values):
    """Return median of a non-empty list of numbers; None for empty input."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _compute_price_per_sqft(price, sqft):
    """MC-327: Compute $/sqft for a listing.

    Returns None if either price or sqft is missing / non-positive / non-numeric.
    Returns a float rounded to 2 decimals (matches the UI '$X.XX' format).

    Robust against all the junk that creeps into scraped fields:
    - empty strings, None, 'None', 'nan' (string or float)
    - numeric strings like '650' or '650.5'
    - floats, ints, Decimals (via duck-typing on the float() call)
    - zero/negative/missing sqft (which would divide by zero or invert sign)
    """
    def _to_num(v):
        if v is None:
            return None
        s = str(v).strip()
        if s in ('', 'None', 'nan', 'NaN', 'NAN'):
            return None
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    p = _to_num(price)
    s = _to_num(sqft)
    if p is None or s is None or p <= 0 or s <= 0:
        return None
    return round(p / s, 2)


def _price_per_sqft_str(pps):
    """Format $/sqft value for the UI.

    Empty/None -> em-dash placeholder ('\u2014') so the cell renders as a
    graceful '—' instead of an empty box. Otherwise format with commas +
    2 decimals when fractional, 0 decimals when whole-dollar (e.g. '$4' not
    '$4.00', matching how apartment listings tend to be cited).
    """
    if pps is None:
        return '\u2014'
    if pps == int(pps):
        return f"${int(pps):,}"
    return f"${pps:,.2f}"


def _price_per_sqft_class(pps):
    """Classify $/sqft for color-coded UI badge (cheap / fair / expensive).

    Returns:
        'pps-cheap'    if pps <= 3.0
        'pps-fair'     if pps <= 4.5
        'pps-expensive' otherwise
    None for missing data (caller renders as '—' with no chip).
    """
    if pps is None:
        return ''
    if pps <= 3.0:
        return 'pps-cheap'
    if pps <= 4.5:
        return 'pps-fair'
    return 'pps-expensive'


def _neighborhood_stats(deals, name: str) -> dict | None:
    """Compute aggregate stats for a single neighborhood.

    Returns None if no active listings match `name` (case-insensitive).
    The returned dict has the MC-321 AC-1 shape:
        neighborhood, slug, count, median_price, median_price_per_sqft,
        min_price, max_price, beds_breakdown, top_deals
    """
    if not name:
        return None
    needle = name.strip().lower()
    listings = [
        d for d in deals
        if (d.get('neighbourhood') or '').strip().lower() == needle
    ]
    if not listings:
        return None

    prices = sorted([d['price'] for d in listings if d.get('price')])
    sqft_prices = []
    for d in listings:
        sqft = _safe_float(d.get('sqft'))
        price = _safe_float(d.get('price'))
        if sqft and sqft > 0 and price:
            sqft_prices.append(price / sqft)

    beds_breakdown: dict = {}
    for d in listings:
        b = d.get('beds')
        if b is None or b == '':
            continue
        try:
            key = int(float(b))
        except (TypeError, ValueError):
            continue
        beds_breakdown[key] = beds_breakdown.get(key, 0) + 1

    # Top 5 deals sorted by final_score desc (filter out zero / negative scores).
    top = sorted(
        [d for d in listings if (d.get('final_score') or 0) > 0],
        key=lambda x: x.get('final_score') or 0,
        reverse=True,
    )[:5]

    return {
        'neighborhood': name,
        'slug': _slugify(name),
        'count': len(listings),
        'median_price': _median(prices),
        'median_price_per_sqft': _median(sqft_prices),
        'min_price': min(prices) if prices else None,
        'max_price': max(prices) if prices else None,
        'beds_breakdown': {str(k): v for k, v in sorted(beds_breakdown.items())},
        'top_deals': [
            {
                'listing_id': d.get('listing_id'),
                'title': d.get('title'),
                'price': d.get('price'),
                'price_fmt': d.get('price_fmt'),
                'beds': d.get('beds'),
                'baths': d.get('baths'),
                'sqft': d.get('sqft'),
                'pct_under': d.get('pct_under'),
                'days_ago': d.get('days_ago'),
                'final_score': d.get('final_score'),
                'link': d.get('link'),
                'image_url': d.get('image_url'),
            }
            for d in top
        ],
    }


def _neighborhoods_summary(deals) -> list:
    """Per-neighborhood aggregate stats for /api/meta sidebar population.

    Returns a list of dicts: {name, slug, count, median_price}, sorted by
    name (case-insensitive). Neighborhoods with no priced listings are
    omitted (count is still meaningful, median_price=None).
    """
    by_name: dict = {}
    for d in deals:
        n = (d.get('neighbourhood') or '').strip()
        if not n:
            continue
        if n not in by_name:
            by_name[n] = {'name': n, 'slug': _slugify(n), 'prices': [], 'count': 0}
        by_name[n]['count'] += 1
        p = _safe_float(d.get('price'))
        if p is not None:
            by_name[n]['prices'].append(p)

    out = []
    for name in sorted(by_name.keys(), key=lambda x: x.lower()):
        info = by_name[name]
        out.append({
            'name': info['name'],
            'slug': info['slug'],
            'count': info['count'],
            'median_price': _median(info['prices']),
        })
    return out


def _slug_to_neighborhood(deals, slug: str) -> str | None:
    """Reverse-lookup: given a URL slug, return the official neighborhood
    name as it appears in `deals`, or None if no listings match.
    """
    if not slug:
        return None
    seen: set = set()
    for d in deals:
        n = (d.get('neighbourhood') or '').strip()
        if not n or n in seen:
            continue
        seen.add(n)
        if _slugify(n) == slug:
            return n
    return None


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

        # MC-312: Resolve image_urls list. Supports three input shapes:
        #   1. raw JSON string in image_urls_json (DB row)
        #   2. pre-decoded list in image_urls (in-memory dict)
        #   3. None / missing (fallback to single image_url)
        raw_urls = r.get('image_urls')
        if isinstance(raw_urls, str):
            # Raw string — try JSON decode
            import json as _json
            try:
                decoded = _json.loads(raw_urls)
                image_urls_list = decoded if isinstance(decoded, list) else []
            except Exception:
                image_urls_list = []
        elif isinstance(raw_urls, list):
            image_urls_list = [u for u in raw_urls if isinstance(u, str) and u.startswith('http')]
        else:
            # Fallback: try image_urls_json column (DB row)
            raw_json = r.get('image_urls_json', '')
            if raw_json:
                import json as _json
                try:
                    decoded = _json.loads(raw_json)
                    image_urls_list = decoded if isinstance(decoded, list) else []
                except Exception:
                    image_urls_list = []
            else:
                # Fallback: wrap image_url into a 1-element list for the gallery carousel
                single = r.get('image_url', '') or ''
                image_urls_list = [single] if single else []

        row_dict = {
            'listing_id': r.get('listing_id') or r.get('url') or r.get('link', ''),
            'title': r.get('title', ''),
            'neighbourhood': r.get('neighborhood', ''),
            'neighborhood_slug': _slugify(r.get('neighborhood', '') or ''),
            'region': r.get('region', ''),
            # MC-316: Normalize source to lowercase canonical form for filtering.
            # The CSV/DB store 'Kijiji' / 'Craigslist'; emit lowercase so the filter
            # param is case-insensitive.
            'source': (r.get('source') or '').strip().lower(),
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
            # MC-324: days_listed — computed from first_seen (durable, SQLite-backed).
            # Fall back to days_ago when first_seen isn't available (CSV path),
            # so the field is always populated for active listings.
            'days_listed': _days_listed_from_first_seen(r.get('first_seen'))
                          if r.get('first_seen') else days_ago,
            'is_stale': is_stale,
            'is_new': is_new,
            'sqft': r.get('sqft', ''),
            # MC-327: price per square foot — universal rental value metric.
            # Populated only when both price > 0 and sqft > 0; null otherwise.
            # The str/class helpers cover empty-cell formatting + color coding
            # for the UI's Sqft Price column.
            'price_per_sqft': _compute_price_per_sqft(r.get('price'), r.get('sqft')),
            'price_per_sqft_str': '',   # filled in below once row_dict exists
            'price_per_sqft_class': '',
            'commute_minutes': float(r['commute_minutes']) if r.get('commute_minutes', '') not in ('', 'None', 'nan', None) else None,
            'link': r.get('url') or r.get('link', ''),
            'final_score': round(final_score, 3) if final_score else 0,
            'image_url': r.get('image_url', '') or '',  # MC-307: listing photo URL
            'image_urls': image_urls_list,            # MC-312: full photo list for gallery
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
        # MC-324: days_listed display helpers (after row_dict is assembled so
        # the values are visible to _compute_cautions / sort handlers / UI).
        row_dict['days_listed_str'] = _days_listed_str(row_dict.get('days_listed'))
        row_dict['days_listed_class'] = _days_listed_class(row_dict.get('days_listed'))
        # MC-332: has_image boolean — True iff this row has at least one usable
        # photo URL (image_url non-empty OR image_urls list has any http URL).
        # Drives the "With photos only" filter and the With photos count in
        # /api/meta. Empty strings, None, and non-http URLs are all rejected so
        # junk like "" or "javascript:..." never get a True.
        _single = (row_dict.get('image_url') or '').strip()
        _multi = row_dict.get('image_urls') or []
        _has_multi = any(isinstance(u, str) and u.strip().startswith('http') for u in _multi)
        row_dict['has_image'] = bool(_single) or _has_multi
        # MC-327: $/sqft display helpers (str for the cell, class for colour).
        _pps = row_dict.get('price_per_sqft')
        row_dict['price_per_sqft_str'] = _price_per_sqft_str(_pps)
        row_dict['price_per_sqft_class'] = _price_per_sqft_class(_pps)
        return row_dict
    except (ValueError, TypeError):
        return None


def _get_neighborhood_trends_safe(deals: list) -> dict:
    """
    MC-329: Compute the neighbourhood_trends map for the sidebar / /api/meta
    payload. Wraps get_neighborhood_trends_batch in try/except so a DB hiccup
    surfaces as an empty dict rather than 500-ing /api/meta.
    """
    try:
        unique = sorted({
            (d.get('neighbourhood') or '').strip()
            for d in deals
            if (d.get('neighbourhood') or '').strip()
        })
        if not unique:
            return {}
        from persist import get_neighborhood_trends_batch
        return get_neighborhood_trends_batch(unique, days=30)
    except Exception:
        return {}


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
                    # MC-325: Batch-enrich with price-drop fields (one SQLite
                    # query per drop, but iterated only over the active set).
                    deals = _enrich_price_drops(deals)
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
    # CSV path: price-drop enrichment still works if a SQLite DB with
    # price_history rows is present (the live SQLite path is what populates
    # price_history going forward via upsert_listings → upsert_price_history).
    deals = _enrich_price_drops(deals)
    return deals


def _enrich_price_drops(deals: list, days: int = 14, min_drop_pct: float = 5.0) -> list:
    """
    MC-325: Add price_dropped / price_drop_pct / price_drop_amount /
    price_drop_from_price / price_drop_days_ago fields to each deal dict
    based on the price_history table. Listings with no recorded drop
    receive price_dropped=False (and the other fields set to None).

    The enrichment uses a single batched call to persist.get_all_listing_price_drops()
    so we hit the SQLite price_history table at most once per request.
    """
    try:
        from persist import get_all_listing_price_drops
    except ImportError:
        # If persist can't be imported (shouldn't happen, but defensive),
        # leave the deals as-is with default fields below.
        for d in deals:
            d.setdefault('price_dropped', False)
            d.setdefault('price_drop_pct', None)
            d.setdefault('price_drop_amount', None)
            d.setdefault('price_drop_from_price', None)
            d.setdefault('price_drop_days_ago', None)
        return deals

    try:
        drops = get_all_listing_price_drops(days=days, min_drop_pct=min_drop_pct)
    except Exception:
        drops = {}

    for d in deals:
        lid = d.get('listing_id') or ''
        info = drops.get(lid)
        if info:
            d['price_dropped'] = True
            d['price_drop_pct'] = round(info['drop_pct'], 1)
            d['price_drop_amount'] = round(info['drop_amount'], 0)
            d['price_drop_from_price'] = round(info['from_price'], 0)
            d['price_drop_days_ago'] = info['days_ago_from']
        else:
            d['price_dropped'] = False
            d['price_drop_pct'] = None
            d['price_drop_amount'] = None
            d['price_drop_from_price'] = None
            d['price_drop_days_ago'] = None
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
    # MC-316: Source filter (kijiji / craigslist / all)
    source = request.args.get('source', '').strip().lower()
    # MC-323: Only NEW (6h) filter — surface listings marked fresh in MC-264.
    # Accepts 'true' / '1' / 'yes' / 'false' / '0' / 'no' / ''. Missing or empty
    # is treated as "no filter" so existing callers are unaffected.
    only_new_raw = (request.args.get('is_new', '') or '').strip().lower()
    only_new = only_new_raw in ('true', '1', 'yes')
    # MC-325: Price-dropped filter — show only listings whose current price is
    # at least 5% lower than the oldest recorded price in the last 14 days.
    # Accepts the same truthy/falsy values as the is_new filter for consistency.
    price_dropped_raw = (request.args.get('price_dropped', '') or '').strip().lower()
    price_dropped = price_dropped_raw in ('true', '1', 'yes')
    # MC-327: Max $/sqft filter. Numeric (step 0.5 in UI). Rows with null
    # price_per_sqft (no sqft disclosed) are excluded — a missing-data row
    # shouldn't be misclassified as "below the user's max $/sqft cap".
    try:
        max_price_per_sqft = float(request.args.get('price_per_sqft_max', '') or '')
    except (TypeError, ValueError):
        max_price_per_sqft = None
    # MC-332: With-photos filter. Accepts the same truthy values as the
    # only_new / price_dropped filters for consistency. Missing / empty /
    # false = no filter (all rows returned, regardless of photo presence).
    has_image_raw = (request.args.get('has_image', '') or '').strip().lower()
    has_image = has_image_raw in ('true', '1', 'yes')

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
    # MC-316: source filter — case-insensitive; empty/all returns both
    if source and source != 'all':
        deals = [d for d in deals if d.get('source', '') == source]
    # MC-323: Only NEW filter. Only applied when explicit truthy value is
    # passed so that GET /api/deals (no param) still returns everything.
    if only_new:
        deals = [d for d in deals if d.get('is_new', False) is True]
    # MC-325: Price-dropped filter — only applied when explicit truthy value
    # is passed. Combines cleanly with other filters (source, is_new, beds).
    if price_dropped:
        deals = [d for d in deals if d.get('price_dropped', False) is True]
    # MC-327: Max $/sqft filter. Drop rows where price_per_sqft is missing
    # (cannot validate them against the user's cap) or exceeds the cap.
    if max_price_per_sqft is not None and max_price_per_sqft > 0:
        deals = [d for d in deals
                 if d.get('price_per_sqft') is not None
                 and d['price_per_sqft'] <= max_price_per_sqft]
    # MC-332: With-photos filter. Only applied on explicit truthy value so
    # GET /api/deals (no param) returns the full row set unchanged. Uses the
    # has_image flag computed in _normalize_row (True iff any usable photo
    # URL exists). Combines cleanly with source/is_new/price_dropped/etc.
    if has_image:
        deals = [d for d in deals if d.get('has_image', False) is True]
    if max_commute is not None:
        deals = [d for d in deals if d.get('commute_minutes') is not None and d['commute_minutes'] <= max_commute]
        deals.sort(key=lambda d: d.get('commute_minutes', 999))

    # MC-270 AC5: Max subway walk filter
    if max_subway is not None:
        deals = [d for d in deals if d.get('station_walk_min') is not None and d['station_walk_min'] <= max_subway]

    # Sort
    reverse = sort_by not in ('price', 'days_ago', 'price_per_sqft')
    key_map = {
        'price': 'price',
        'pct': 'pct_under',
        'score': 'final_score',
        'beds': 'beds',
        'baths': 'baths',
        'days_ago': 'days_ago',
        # MC-324: days_listed — sort by how long a listing has been on the
        # market. The default UI label is "Longest Listed" so the natural
        # default order (reverse=False) is HIGHEST days_listed first. We
        # achieve this by sorting on a negated key when sort_by is days_listed.
        'days_listed': 'days_listed',
        # MC-327: $/sqft — best value (lowest $/sqft) at index 0 by default.
        'price_per_sqft': 'price_per_sqft',
    }
    key = key_map.get(sort_by, 'final_score')

    def _sort_key(d):
        v = d.get(key)
        if isinstance(v, (int, float)):
            return v
        # Missing data → -1 so it sorts last regardless of direction.
        return -1

    if key == 'days_listed':
        # AC3: asc = longest-listed first. Sort on negated days_listed with
        # reverse=False to get the highest days_listed at index 0.
        # To switch to "newest listed first", we'd add an explicit ?order= param
        # later; for now the default UX matches "Longest Listed".
        deals.sort(key=lambda d: -(_sort_key(d) if _sort_key(d) >= 0 else 1), reverse=False)
    elif key == 'price_per_sqft':
        # MC-327: Sort by $/sqft with nulls at the END regardless of direction.
        # Use float('inf') as the sentinel for nulls so ascending puts them
        # last, and descending (which reverses the whole list) keeps them
        # last because inf + reverse(True) — actually wait, reverse(True)
        # would put them first. To keep nulls last in BOTH directions we
        # use a tuple sort: (is_null, value), where is_null=True sorts after
        # is_null=False ascending.
        def _pps_sort(d):
            v = d.get('price_per_sqft')
            if isinstance(v, (int, float)):
                return (0, v)
            return (1, 0)  # 1 sorts after 0, pushing nulls to the end
        deals.sort(key=_pps_sort, reverse=False)
    else:
        deals.sort(key=_sort_key, reverse=reverse)

    # MC-261: segment-aware fair value (relative to filtered search results)
    if deals:
        from compute_segment_fv import compute_fair_value_with_fallback
        deals = compute_fair_value_with_fallback(deals)

    # MC-319: Server-side pagination. Defaults: limit=50, offset=0.
    # Limit is hard-capped at 200 to keep responses reasonable.
    try:
        limit = int(request.args.get('limit', 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))
    try:
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)

    total = len(deals)
    page = deals[offset:offset + limit]
    has_more = (offset + len(page)) < total

    # MC-329: Attach neighborhood_trend to each deal row. One batch call
    # covers all unique neighborhoods in the FULL filtered set (not just
    # the current page) so the UI trend data is stable across pagination.
    # Neighbourhoods with <2 days of price_history are silently absent
    # from the trends map; rows for those neighborhoods get neighborhood_trend
    # set to None (no badge rendered in the UI).
    try:
        unique_neighborhoods = sorted({
            (d.get('neighbourhood') or '').strip()
            for d in deals
            if (d.get('neighbourhood') or '').strip()
        })
        if unique_neighborhoods:
            from persist import get_neighborhood_trends_batch
            trends_map = get_neighborhood_trends_batch(unique_neighborhoods, days=30)
        else:
            trends_map = {}
        for d in page:
            nbhd = (d.get('neighbourhood') or '').strip()
            d['neighborhood_trend'] = trends_map.get(nbhd)   # None if not enough data
    except Exception as _e:
        # Persistence layer error must not 500 the request -- degrade
        # gracefully (all rows get None, badge is silently hidden).
        for d in page:
            d['neighborhood_trend'] = None

    return jsonify({
        'deals': page,
        'total': total,
        'limit': limit,
        'offset': offset,
        'has_more': has_more,
    })


@app.route('/api/meta')
def api_meta():
    """Return min/max ranges derived from actual data for UI slider construction."""
    deals = load_deals()
    if not deals:
        return jsonify({
            'beds': [], 'price': [0, 0], 'baths': [], 'regions': [], 'sources': [],
            'neighborhoods': [], 'new_count': 0, 'price_drop_count': 0,
            'with_photos_count': 0,
            'price_per_sqft_stats': {
                'count_with_sqft': 0, 'count_without_sqft': 0,
                'min': None, 'max': None, 'median': None, 'p25': None, 'p75': None,
            },
            'neighborhood_trends': {},
        })

    beds_vals = sorted(set(d['beds'] for d in deals if d['beds'] is not None))
    price_vals = [min(d['price'] for d in deals), max(d['price'] for d in deals)]
    baths_vals = sorted(set(d['baths'] for d in deals if d['baths'] is not None))
    regions = sorted(set(d.get('region', '') for d in deals if d.get('region', '')))
    # MC-316: Include available sources so the UI can render the filter dropdown
    sources = sorted(set(d.get('source', '') for d in deals if d.get('source', '')))
    # MC-321: Per-neighbourhood aggregate stats for sidebar / drill-down population
    neighborhoods = _neighborhoods_summary(deals)
    # MC-323: Count of is_new=1 listings so the UI can render "(N new)" hint
    # next to the Only NEW toggle. Computed before any user-supplied filter
    # so the count reflects the full data set (the "what's new today" total).
    new_count = sum(1 for d in deals if d.get('is_new', False) is True)
    # MC-325: Count of listings with a confirmed price drop in the last 14d
    # (default 5% threshold). Used by the UI to render a "(N drops)" badge
    # next to the Price Drop toggle so users see the total at a glance.
    price_drop_count = sum(1 for d in deals if d.get('price_dropped', False) is True)
    # MC-332: Count of listings with at least one usable photo. Computed over
    # the full data set (no other filters applied) so the UI badge reflects
    # the universe of photo-bearing listings, not whatever the user has
    # already narrowed down. Uses has_image from _normalize_row so the count
    # matches what ?has_image=true would include.
    with_photos_count = sum(1 for d in deals if d.get('has_image', False) is True)
    # MC-327: $/sqft distribution stats. Computed over ALL listings (not just
    # the filtered set returned by /api/deals) so the UI can render a max-$/sqft
    # slider with sensible bounds. Null price_per_sqft rows are excluded from
    # stats but counted in `count_without_sqft` so the UI can show "X listings
    # have no sqft data".
    pps_vals = [d['price_per_sqft'] for d in deals
                if isinstance(d.get('price_per_sqft'), (int, float))]
    pps_total = len(deals)
    pps_with = len(pps_vals)
    pps_without = pps_total - pps_with
    if pps_vals:
        pps_min = round(min(pps_vals), 2)
        pps_max = round(max(pps_vals), 2)
        pps_median = round(_median(pps_vals), 2)
        # Quick quartiles using sorted positions (no numpy / scipy dep).
        sorted_pps = sorted(pps_vals)
        n_pps = len(sorted_pps)
        def _q(qf):
            if n_pps == 1:
                return float(sorted_pps[0])
            pos = qf * (n_pps - 1)
            lo = int(pos)
            frac = pos - lo
            if lo + 1 < n_pps:
                return round(sorted_pps[lo] + frac * (sorted_pps[lo + 1] - sorted_pps[lo]), 2)
            return float(sorted_pps[lo])
        pps_p25 = _q(0.25)
        pps_p75 = _q(0.75)
    else:
        pps_min = pps_max = pps_median = pps_p25 = pps_p75 = None
    price_per_sqft_stats = {
        'count_with_sqft': pps_with,
        'count_without_sqft': pps_without,
        'min': pps_min,
        'max': pps_max,
        'median': pps_median,
        'p25': pps_p25,
        'p75': pps_p75,
    }

    return jsonify({
        'beds': beds_vals,
        'price': [int(price_vals[0]), int(price_vals[1])],
        'baths': baths_vals,
        'regions': regions,
        'sources': sources,
        'neighborhoods': neighborhoods,
        'new_count': new_count,
        'price_drop_count': price_drop_count,
        # MC-332: Photo-bearing listing total. Drives the "(N photos)" hint
        # next to the new "With photos only" toggle in the filter bar.
        'with_photos_count': with_photos_count,
        'price_per_sqft_stats': price_per_sqft_stats,
        # MC-329: Per-neighbourhood 30-day price-trend map. Same shape as
        # the field added to each /api/deals row. Neighbourhoods without
        # >=2 days of price_history are absent from the map; the UI can
        # iterate neighborhoods and look up trends_map[name].
        'neighborhood_trends': _get_neighborhood_trends_safe(deals),
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


# ── MC-321: Neighborhood stats drill-down ────────────────────────────────────


@app.route('/api/neighborhoods/<slug>/stats')
def api_neighborhood_stats(slug):
    """Per-neighborhood aggregate stats: count, median price + $/sqft,
    min/max price, beds breakdown, top-5 deals. 404 for unknown slug.
    """
    deals = load_deals()
    name = _slug_to_neighborhood(deals, slug)
    if not name:
        return jsonify({'error': 'neighborhood not found', 'slug': slug}), 404
    stats = _neighborhood_stats(deals, name)
    if not stats:
        return jsonify({'error': 'no listings for that neighborhood', 'slug': slug}), 404
    return jsonify(stats)


@app.route('/neighborhood/<slug>')
def neighborhood_page(slug):
    """HTML drill-down page for a single neighborhood.

    The page fetches /api/neighborhoods/<slug>/stats + /api/deals?neighbourhood=...
    client-side, so it always shows live data without a server roundtrip on each
    page view.
    """
    return render_template('neighborhood.html', slug=slug)


# ── MC-328: Neighborhood price trend chart ───────────────────────────────────

@app.route('/api/neighborhoods/<slug>/price-history')
def api_neighborhood_price_history(slug):
    """Per-neighbourhood price trend over the last N days.

    GET /api/neighborhoods/<slug>/price-history?days=30

    Returns:
      {
        'neighborhood': str,
        'slug':         str,
        'days':         int,
        'days_of_data': int,           # number of distinct days with >=1 data point
        'series':       [
          {
            'date_iso':              'YYYY-MM-DD',
            'median_price':          float | None,
            'median_price_per_sqft': float | None,
            'listing_count':         int,
            'dollar_per_sqft_min':   float | None,
            'dollar_per_sqft_max':   float | None,
          },
          ...
        ]
      }

    404 if the slug does not resolve to any active neighbourhood (matches
    the convention used by /api/neighborhoods/<slug>/stats).
    Empty `series` is a valid 200 response — the page shows its empty-state
    UI for "not enough data yet".
    """
    days = request.args.get('days', '30')
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 30
    # Clamp to a sensible range — the chart is meant to be a small sparkline,
    # not a multi-year deep dive.
    days = max(1, min(days, 365))

    deals = load_deals()
    name = _slug_to_neighborhood(deals, slug)
    if not name:
        return jsonify({'error': 'neighborhood not found', 'slug': slug}), 404

    from persist import get_neighborhood_price_history
    series = get_neighborhood_price_history(name, days=days)
    return jsonify({
        'neighborhood': name,
        'slug': slug,
        'days': days,
        'days_of_data': len(series),
        'series': series,
    })


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


@app.route('/api/compare')
def api_compare():
    """
    MC-313: Side-by-side deal comparison.

    Query: ?ids=<listing_id1>,<listing_id2>[,<listing_id3>]
    Returns a JSON object with the requested listings (2 or 3) and a `best` block
    identifying the winning column per metric (lowest price, lowest $/sqft,
    lowest $ over fair value, most photos).

    Errors:
      400 if `ids` missing, blank, wrong count (<2 or >3), or any individual id empty
      404 if any requested id is not found in the current deal list
    """
    raw = request.args.get('ids', '').strip()
    if not raw:
        return jsonify({'error': 'ids query param required (comma-separated listing_ids)'}), 400

    parts = [p.strip() for p in raw.split(',') if p.strip()]
    if len(parts) < 2 or len(parts) > 3:
        return jsonify({'error': '2 or 3 listing ids required'}), 400
    # De-dupe while preserving user-supplied order
    seen = set()
    ordered = []
    for p in parts:
        if p in seen:
            return jsonify({'error': f'duplicate id: {p}'}), 400
        seen.add(p)
        ordered.append(p)

    deals = load_deals()
    by_id = {d.get('listing_id'): d for d in deals if d.get('listing_id')}

    normalized = []
    missing = []
    for lid in ordered:
        d = by_id.get(lid)
        if d is None:
            missing.append(lid)
            continue
        # Re-normalize through the same pipeline so we don't depend on the caller's
        # in-memory shape. _normalize_row is idempotent for already-normalized dicts
        # because it only reads fields that survive the round-trip.
        norm = _normalize_row(d)
        if norm is None:
            missing.append(lid)
            continue
        # Compute $/sqft for best-value highlighting (None if sqft missing/zero)
        sqft = norm.get('sqft')
        try:
            sqft_n = float(sqft) if sqft not in (None, '', 'None', 'nan') else None
        except (ValueError, TypeError):
            sqft_n = None
        norm['sqft_num'] = sqft_n
        norm['price_per_sqft'] = round(norm['price'] / sqft_n, 2) if (sqft_n and sqft_n > 0 and norm['price']) else None
        norm['photo_count'] = len(norm.get('image_urls') or ([norm['image_url']] if norm.get('image_url') else []))
        norm['savings'] = round(float(norm.get('fair_value') or 0) - float(norm.get('price') or 0), 2)
        normalized.append(norm)

    if missing:
        return jsonify({'error': 'Listing not found', 'missing_ids': missing}), 404
    if len(normalized) != len(ordered):
        # Defensive: _normalize_row returned None for an id we located
        return jsonify({'error': 'failed to normalize one or more listings'}), 500

    # Determine best-value winners per metric. Lower is better for all price
    # metrics; higher is better for photo count.
    best = {}
    def _winner(metric, mode='min'):
        candidates = []
        for d in normalized:
            v = d.get(metric)
            if v is None:
                continue
            try:
                candidates.append((float(v), d['listing_id']))
            except (ValueError, TypeError):
                continue
        if not candidates:
            return None
        if mode == 'min':
            candidates.sort(key=lambda t: t[0])
        else:
            candidates.sort(key=lambda t: -t[0])
        return candidates[0][1]

    best['lowest_price'] = _winner('price', 'min')
    best['lowest_price_per_sqft'] = _winner('price_per_sqft', 'min')
    # "Lowest $ over fair value" == smallest savings (savings = FV - price).
    # A negative savings means the listing is priced above FV. The smallest
    # (least-negative or most-positive) savings is the best value relative to FV.
    best['smallest_savings_gap'] = _winner('savings', 'max')  # max savings = best deal
    best['most_photos'] = _winner('photo_count', 'max')

    return jsonify({'listings': normalized, 'best': best})


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
        'image_url': d.get('image_url', ''),  # MC-307: listing photo
        'image_urls': d.get('image_urls', []) or [],  # MC-312: gallery carousel list
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


@app.route('/saved-searches')
def page_saved_searches():
    """MC-322: Dedicated /saved-searches management page.

    Renders templates/saved_searches.html. Accepts ?email=<addr> in the URL
    (the page reads it client-side and stays usable when the param is absent).
    """
    return render_template('saved_searches.html')


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
        # MC-326: ensure the notify_on_match + last_notification_sent fields
        # are always exposed (defaults to 0 if the column is missing on an
        # older DB row), so the /saved-searches UI can render the 🔔/🔕.
        for s in searches:
            s['notify_on_match'] = int(s.get('notify_on_match') or 0)
            s['last_notification_sent'] = s.get('last_notification_sent')
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
        "min_score": 0.15,
        "filters_json": "{\"source\":\"kijiji\",\"sort\":\"pct\",...}"   # MC-322
    }

    MC-322: filters_json is optional. When provided, it's stored verbatim so
    the Save-Current-Filters button + Load-on-/saved-searches page can
    round-trip the *raw* filter state (keys not represented by the legacy
    columns, like source/sort/hide_stale/max_subway/has_parking). Back-compat:
    callers that omit filters_json keep working.
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

    # MC-322: normalize filters_json — accept either a dict (auto-serialize)
    # or a string (validate by re-parse). Reject obviously broken input early
    # rather than at the SQLite layer.
    raw_filters = data.get('filters_json')
    if raw_filters is None or raw_filters == '':
        filters_json_str = '{}'
    elif isinstance(raw_filters, dict):
        try:
            filters_json_str = json.dumps(raw_filters, ensure_ascii=False)
        except Exception:
            return jsonify({'error': 'filters_json must be JSON-serializable'}), 400
    elif isinstance(raw_filters, str):
        # Validate it's parseable JSON
        try:
            parsed = json.loads(raw_filters) if raw_filters.strip() else {}
        except Exception:
            return jsonify({'error': 'filters_json must be valid JSON'}), 400
        if not isinstance(parsed, dict):
            return jsonify({'error': 'filters_json must decode to an object'}), 400
        filters_json_str = raw_filters if raw_filters.strip() else '{}'
    else:
        return jsonify({'error': 'filters_json must be object or string'}), 400

    try:
        from persist import upsert_saved_search
        # MC-326: parse notify_on_match bool. Accept 1/0, true/false, "true"/"false".
        _notify_raw = data.get('notify_on_match')
        if _notify_raw is None:
            notify_on_match = None  # preserve existing on conflict
        elif isinstance(_notify_raw, bool):
            notify_on_match = _notify_raw
        else:
            notify_on_match = str(_notify_raw).strip().lower() in ('1', 'true', 'yes', 'on')

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
            filters_json=filters_json_str,
            notify_on_match=notify_on_match,
        )
        return jsonify({'success': True, 'search_id': search_id, 'notify_on_match': bool(notify_on_match) if notify_on_match is not None else None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/saved-searches/<int:search_id>', methods=['PUT'])
def api_saved_searches_update(search_id: int):
    """
    MC-266: Update a saved search.
    PUT body: same as POST body + ?email=... for ownership check.

    MC-322: also accepts filters_json in the PUT body; persisted verbatim.
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

    # MC-322: same normalization as POST.
    raw_filters = data.get('filters_json')
    if raw_filters is None or raw_filters == '':
        # Allow callers to *not* update filters_json; signal "keep existing"
        # with a sentinel by passing the existing value back.
        from persist import get_saved_search_by_id
        existing = get_saved_search_by_id(email, search_id)
        filters_json_str = (existing or {}).get('filters_json') or '{}'
    elif isinstance(raw_filters, dict):
        try:
            filters_json_str = json.dumps(raw_filters, ensure_ascii=False)
        except Exception:
            return jsonify({'error': 'filters_json must be JSON-serializable'}), 400
    elif isinstance(raw_filters, str):
        try:
            parsed = json.loads(raw_filters) if raw_filters.strip() else {}
        except Exception:
            return jsonify({'error': 'filters_json must be valid JSON'}), 400
        if not isinstance(parsed, dict):
            return jsonify({'error': 'filters_json must decode to an object'}), 400
        filters_json_str = raw_filters if raw_filters.strip() else '{}'
    else:
        return jsonify({'error': 'filters_json must be object or string'}), 400

    try:
        from persist import upsert_saved_search
        # upsert_saved_search uses (email, name) as the conflict key, not search_id.
        # We update by re-upserting with the same name to update fields.
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'name required for update'}), 400
        # MC-326: parse notify_on_match.
        _notify_raw = data.get('notify_on_match')
        if _notify_raw is None:
            notify_on_match = None
        elif isinstance(_notify_raw, bool):
            notify_on_match = _notify_raw
        else:
            notify_on_match = str(_notify_raw).strip().lower() in ('1', 'true', 'yes', 'on')

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
            filters_json=filters_json_str,
            notify_on_match=notify_on_match,
        )
        return jsonify({'success': True, 'search_id': search_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/saved-searches/load', methods=['GET'])
def api_saved_searches_load():
    """
    MC-322: Return a single saved search by id + email so the /saved-searches
    management page's Load button can hand the captured filters back to
    index.html's applySavedFilters() helper.

    Query params: ?email=<addr>&id=<int>
    Returns: {success, search: {search_id, name, filters_dict, beds_min,
            beds_max, baths_min, price_min, price_max, neighbourhood,
            region, min_score, max_commute, commute_dest}} on 200,
            or {error} on 400/404/500.
    """
    email = (request.args.get('email') or '').strip()
    search_id_raw = request.args.get('id') or ''
    if not email or '@' not in email:
        return jsonify({'error': 'email required'}), 400
    try:
        search_id = int(search_id_raw)
    except (TypeError, ValueError):
        return jsonify({'error': 'id must be an integer'}), 400
    try:
        from persist import get_saved_search_by_id
        row = get_saved_search_by_id(email, search_id)
        if not row:
            return jsonify({'error': 'Not found or not yours'}), 404
        # Strip internal fields, normalize top_match if present
        out = {
            'search_id': row['search_id'],
            'name': row['name'],
            'beds_min': row.get('beds_min'),
            'beds_max': row.get('beds_max'),
            'baths_min': row.get('baths_min'),
            'price_min': row.get('price_min'),
            'price_max': row.get('price_max'),
            'neighbourhood': row.get('neighbourhood'),
            'region': row.get('region'),
            'min_score': row.get('min_score'),
            'max_commute': row.get('max_commute'),
            'commute_dest': row.get('commute_dest'),
            'filters_json': row.get('filters_json') or '{}',
            'filters_dict': row.get('filters_dict') or {},
            'notify_on_match': int(row.get('notify_on_match') or 0),
            'last_notification_sent': row.get('last_notification_sent'),
        }
        return jsonify({'success': True, 'search': out})
    except Exception as e:
        import traceback; traceback.print_exc()
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


@app.route('/api/saved-searches/<int:search_id>/toggle-notify', methods=['POST'])
def api_saved_searches_toggle_notify(search_id: int):
    """
    MC-326: Toggle (or set) the notify_on_match flag for a saved search.

    POST body: {"email": "user@example.com", "notify": true|false}
    Returns 200 {success, search_id, notify_on_match} on success,
            400 if email missing or "notify" missing/invalid,
            404 if the search id doesn't exist for that email.
    """
    data = request.get_json(force=True) or {}
    email = (data.get('email') or '').strip()
    if not email or '@' not in email:
        return jsonify({'error': 'email required'}), 400
    if 'notify' not in data:
        return jsonify({'error': '"notify" field required (true|false)'}), 400
    raw = data.get('notify')
    if isinstance(raw, bool):
        notify = raw
    else:
        s = str(raw).strip().lower()
        if s in ('1', 'true', 'yes', 'on'):
            notify = True
        elif s in ('0', 'false', 'no', 'off', ''):
            notify = False
        else:
            return jsonify({'error': '"notify" must be true or false'}), 400

    try:
        from persist import update_saved_search_notify
        updated = update_saved_search_notify(search_id, email, notify)
        if updated is None:
            return jsonify({'error': 'Not found or not yours'}), 404
        return jsonify({
            'success': True,
            'search_id': search_id,
            'notify_on_match': int(updated.get('notify_on_match') or 0),
            'last_notification_sent': updated.get('last_notification_sent'),
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/saved-searches/run-checks', methods=['POST'])
def api_saved_searches_run_checks():
    """
    MC-326: Admin / cron endpoint that runs check_and_send_saved_search_alerts()
    and returns the summary dict. Optional JSON body:
      {"min_hours_between": 24, "send_fn": null}

    `send_fn` is intentionally NOT exposed — the worker uses the live
    email_alerts.send_saved_search_alert_email function (or the stub when
    SENDGRID_API_KEY is missing). Tests POST here with monkey-patched persist
    functions; production calls this from find_deals.py.
    """
    data = request.get_json(silent=True) or {}
    min_hours = int(data.get('min_hours_between') or 24)
    try:
        from persist import check_and_send_saved_search_alerts
        result = check_and_send_saved_search_alerts(min_hours_between=min_hours)
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        import traceback; traceback.print_exc()
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



# ── MC-308: Craigslist on-demand photo fetch ────────────────────────────────
#
# Craigslist search pages don't expose photos (MC-307 self-audit). When a
# user opens a Craigslist listing detail modal, this endpoint lazily fetches
# the individual listing page, extracts the first image, caches the result
# in `craigslist_photo_cache`, and returns the image URL.
#
# Rate limit: max 30 fetches per rolling 2-hour window (cron pipeline cycle).
# Cache TTL:  positive = 14 days, negative (404/timeout/parse-fail) = 1 hour.
#
# Endpoint contract:
#   GET /api/craigslist/photo?url=<listing_url>&token=<opaque>
#     200  -> {image_url, cached, fetched, is_negative}
#     400  -> missing or non-craigslist url
#     429  -> rate limited (budget exhausted)
#     502  -> upstream fetch error / no image

import craigslist_photo_fetcher as _cl_fetcher
from persist import (
    get_craigslist_photo_cache,
    upsert_craigslist_photo_cache,
    get_recent_cl_photo_fetches,
)

# 30 fetches per 2-hour cron cycle matches the live scrape cadence.
CL_PHOTO_BUDGET_PER_CYCLE = 30
CL_PHOTO_CYCLE_WINDOW_SECS = 2 * 60 * 60  # 2 hours
_LAST_CL_FETCH_AT = [0.0]  # module-level lock for 1 req/sec
_CL_FETCH_LOCK = __import__('threading').Lock()


def _is_craigslist_url(url):
    # Defensive: only fetch from craigslist.org to prevent SSRF.
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    return u.startswith('https://') and 'craigslist.org/' in u


def _cl_throttle():
    # Enforce 1 req/sec between consecutive Craigslist fetches so we don't
    # trip the site's basic anti-bot heuristics.
    import time as _time
    with _CL_FETCH_LOCK:
        now = _time.monotonic()
        delta = now - _LAST_CL_FETCH_AT[0]
        if delta < 1.0:
            _time.sleep(1.0 - delta)
        _LAST_CL_FETCH_AT[0] = _time.monotonic()


def _cl_rate_limit_ok():
    # True if we still have budget in the current cycle. Resets every
    # CL_PHOTO_CYCLE_WINDOW_SECS based on cache write timestamps.
    used = get_recent_cl_photo_fetches(CL_PHOTO_CYCLE_WINDOW_SECS)
    return used < CL_PHOTO_BUDGET_PER_CYCLE, used


@app.route('/api/craigslist/photo')
def api_craigslist_photo():
    listing_url = request.args.get('url', '').strip()
    if not listing_url:
        return jsonify({'error': 'url required'}), 400
    if not _is_craigslist_url(listing_url):
        return jsonify({'error': 'url must be a craigslist.org URL'}), 400

    # 1) Cache hit path
    cached = get_craigslist_photo_cache(listing_url)
    if cached is not None:
        return jsonify({
            'listing_url': listing_url,
            'image_url': cached['image_url'],
            'cached': True,
            'is_negative': bool(cached['is_negative']),
        })

    # 2) Rate-limit check
    ok, used = _cl_rate_limit_ok()
    if not ok:
        return jsonify({
            'error': 'budget_exhausted',
            'message': f'Craigslist photo fetch budget exhausted '
                       f'({used}/{CL_PHOTO_BUDGET_PER_CYCLE} per '
                       f'{CL_PHOTO_CYCLE_WINDOW_SECS // 60}min)',
        }), 429

    # 3) Throttle (1 req/sec)
    _cl_throttle()

    # 4) Upstream fetch
    try:
        image_url = _cl_fetcher.fetch_listing_photo(listing_url)
    except Exception as e:
        # Treat unhandled error as negative cache to avoid tight retry loop
        upsert_craigslist_photo_cache(listing_url, None, is_negative=True)
        return jsonify({'error': 'fetch_error', 'message': str(e)}), 502

    if not image_url:
        upsert_craigslist_photo_cache(listing_url, None, is_negative=True)
        return jsonify({
            'listing_url': listing_url,
            'image_url': None,
            'cached': False,
            'is_negative': True,
        }), 502

    # 5) Cache positive result
    upsert_craigslist_photo_cache(listing_url, image_url, is_negative=False)
    return jsonify({
        'listing_url': listing_url,
        'image_url': image_url,
        'cached': False,
        'is_negative': False,
    })
