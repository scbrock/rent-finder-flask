"""
POI proximity — nearest POI per neighbourhood via OpenStreetMap Overpass API.
MC-267: Rent finder: POI proximity — nearest grocery store with name and walk time
MC-268: Nearest gym (leisure=fitness_centre) when no in-building gym
MC-269: Nearest parking lot (amenity=parking) when no parking
MC-270: Nearest TTC subway station (railway=station + network=TTC)

Uses Overpass API (free, no key) to find POIs within 1.5km of neighbourhood centroid.
Walk time computed via ORS API (already in .env).

Cache: data/poi_cache.json keyed by neighbourhood_centroid_key|amenity_type.
Cache entry shape:
  {
    "store_name": "No Frills",
    "poi_type": "supermarket",
    "distance_m": 850,
    "walk_minutes": 11,
    "store_lat": 43.6486,
    "store_lng": -79.3978,
    "source": "overpass"
  }
  None if no POI found within threshold.
"""

import json, os, time
import requests

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, 'data')
CACHE_PATH = os.path.join(DATA_DIR, 'poi_cache.json')
NEIGHBOURHOODS_JSON = os.path.join(DATA_DIR, 'toronto_neighbourhoods.json')

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_RADIUS_M = 1500  # 1.5 km search radius

# ORS walk speed: 5 km/h (83 m/min)
ORS_WALK_SPEED_M_PER_MIN = 83

# Thresholds: no POI found if nearest is beyond these walk minutes
THRESHOLDS = {
    "supermarket": 20,
    "fitness_centre": 30,
    "parking": 10,
    "station": 20,
}

# ── Cache ───────────────────────────────────────────────────────────────────


def _load_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


# ── Overpass ────────────────────────────────────────────────────────────────


def _overpass_query(lat: float, lng: float, overpass_tag: str, radius: float = 1500.0) -> list[dict]:
    """
    Query Overpass API for nearest POIs near (lat, lng).
    overpass_tag: an Overpass tag expression e.g. "amenity=supermarket" or "railway=station".
    Returns list of {name, lat, lng, distance_m}, sorted by distance.
    """
    # Handle tag expressions like "railway=station" vs "amenity=supermarket"
    # Overpass QL syntax: node["key"="value"] for exact match
    if '=' in overpass_tag and not overpass_tag.startswith('"'):
        key, value = overpass_tag.split('=', 1)
        node_filter = f'node["{key}"="{value}"](around:{radius},{lat},{lng})'
        way_filter = f'way["{key}"="{value}"](around:{radius},{lat},{lng})'
    else:
        # Simple tag: node["amenity=foo"] — direct containment (legacy compat)
        node_filter = f'node["{overpass_tag}"](around:{radius},{lat},{lng})'
        way_filter = f'way["{overpass_tag}"](around:{radius},{lat},{lng})'
    query = f"""
[out:json][timeout:15];
(
  {node_filter};
  {way_filter};
);
out center;
"""
    try:
        resp = requests.get(OVERPASS_URL, params={'data': query}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    results = []
    for el in data.get('elements', []):
        name = el.get('tags', {}).get('name', '')
        if not name:
            continue
        if el['type'] == 'node':
            el_lat = el.get('lat')
            el_lng = el.get('lon')
        elif el['type'] == 'way':
            el_lat = el.get('center', {}).get('lat')
            el_lng = el.get('center', {}).get('lng')
        else:
            continue
        if not el_lat or not el_lng:
            continue
        dist_m = _haversine_m(lat, lng, el_lat, el_lng)
        results.append({'name': name, 'lat': el_lat, 'lng': el_lng, 'distance_m': dist_m})

    results.sort(key=lambda x: x['distance_m'])
    return results


# ── Geometry ────────────────────────────────────────────────────────────────


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance in metres between two lat/lng points."""
    import math
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _ors_walk_time(from_lat: float, from_lng: float,
                   to_lat: float, to_lng: float) -> float | None:
    """
    Compute walking time (minutes) via ORS directions API.
    Returns None on failure → caller falls back to haversine estimate.
    """
    api_key = os.environ.get('ORS_API_KEY', '')
    if not api_key:
        return None

    url = "https://api.openrouteservice.org/v2/directions/foot-walking"
    headers = {'Authorization': api_key, 'Content-Type': 'application/json'}
    body = {
        "start": [from_lng, from_lat],
        "end": [to_lng, to_lat]
    }
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=15)
        resp.raise_for_status()
        route = resp.json()['features'][0]['properties']['segments'][0]
        return round(route['duration'] / 60, 1)
    except Exception:
        return None


def _walk_time_fallback(from_lat: float, from_lng: float,
                        to_lat: float, to_lng: float) -> float:
    """Walking time estimate from haversine distance at 83 m/min."""
    dist = _haversine_m(from_lat, from_lng, to_lat, to_lng)
    return round(dist / ORS_WALK_SPEED_M_PER_MIN, 1)


# ── Neighbourhood centroid ───────────────────────────────────────────────────


def _neighbourhood_centroid(neighbourhood_raw: str) -> tuple[str, float, float] | None:
    """Return (official_name, lat, lng) for a neighbourhood string."""
    from neighbourhood_lookup import lookup
    result = lookup(neighbourhood_raw)
    if not result:
        return None
    return result['official_name'], result['lat'], result['lng']


# ── Generic POI fetch (cached) ─────────────────────────────────────────────


def _fetch_poi_for_neighbourhood(official_name: str, lat: float, lng: float,
                                poi_type: str) -> dict | None:
    """
    Fetch nearest POI of given type for a neighbourhood centroid.
    Caches result in poi_cache.json.
    Returns POI dict or None if nothing found within threshold.
    """
    cache = _load_cache()
    threshold = THRESHOLDS.get(poi_type, 20)
    cache_key = f"{official_name}|{poi_type}"

    if cache_key in cache:
        return cache[cache_key]  # None means cached "no result"

    # Build Overpass tag query — most poi_types map directly to OSM amenity tag,
    # but TTC subway stations use railway=station in OpenStreetMap.
    if poi_type == "station":
        overpass_tag = "railway=station"
    else:
        overpass_tag = f"amenity={poi_type}"
    stores = _overpass_query(lat, lng, overpass_tag=overpass_tag)
    if not stores:
        cache[cache_key] = None
        _save_cache(cache)
        return None

    best = stores[0]
    walk_min = _ors_walk_time(lat, lng, best['lat'], best['lng'])
    if walk_min is None:
        walk_min = _walk_time_fallback(lat, lng, best['lat'], best['lng'])

    entry = {
        'store_name': best['name'],
        'poi_type': poi_type,
        'distance_m': round(best['distance_m']),
        'walk_minutes': walk_min,
        'store_lat': best['lat'],
        'store_lng': best['lng'],
        'source': 'overpass'
    }
    cache[cache_key] = entry
    _save_cache(cache)
    return entry


# ── Public APIs ─────────────────────────────────────────────────────────────


def find_nearest_poi(neighbourhood_raw: str,
                     poi_type: str = "supermarket") -> dict | None:
    """
    Public API: find nearest POI of given type for a neighbourhood string.

    poi_type options:
      supermarket     — grocery stores (MC-267)
      fitness_centre   — gyms (MC-268)
      parking         — parking lots (MC-269)
      station         — TTC subway stations (MC-270)

    Returns dict with store_name, poi_type, walk_minutes, distance_m,
    store_lat, store_lng, or None.
    """
    centroid = _neighbourhood_centroid(neighbourhood_raw)
    if not centroid:
        return None
    official_name, lat, lng = centroid
    return _fetch_poi_for_neighbourhood(official_name, lat, lng, poi_type)


# ── Convenience wrappers (MC-267) ───────────────────────────────────────────

def find_nearest_grocery(neighbourhood_raw: str) -> dict | None:
    """Nearest supermarket for a neighbourhood (MC-267)."""
    return find_nearest_poi(neighbourhood_raw, poi_type="supermarket")


if __name__ == '__main__':
    # Quick smoke test
    test_cases = [
        ('Annex', 'supermarket'),
        ('Liberty Village', 'supermarket'),
        ('Church-Yonge Corridor', 'fitness_centre'),
    ]
    print("POI proximity smoke test:")
    for n, poi_type in test_cases:
        result = find_nearest_poi(n, poi_type=poi_type)
        if result:
            print(f"  {n} [{poi_type}]: {result['store_name']} · {result['walk_minutes']} min walk ({result['distance_m']}m)")
        else:
            print(f"  {n} [{poi_type}]: No {poi_type} found")
