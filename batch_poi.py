"""
MC-269: Batch-populate poi_cache.json with gym (fitness_centre) and parking (amenity=parking)
POIs for all neighbourhoods in toronto_neighbourhoods.json.

Then add has_gym/has_parking columns to listings.db and backfill.
"""

import json, os, time, math, requests

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, 'data')
CACHE_PATH = os.path.join(DATA_DIR, 'poi_cache.json')
NEIGHBOURHOODS_JSON = os.path.join(DATA_DIR, 'toronto_neighbourhoods.json')
DB_PATH = os.path.join(DATA_DIR, 'listings.db')
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ORS_WALK_SPEED_M_PER_MIN = 83

OVERPASS_RADIUS_M = 1500
PARKING_RADIUS_M = 500

POI_TYPES = {
    "fitness_centre": {"radius": OVERPASS_RADIUS_M, "threshold": 30},
    "parking": {"radius": PARKING_RADIUS_M, "threshold": 15},
}


def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _ors_walk_time(from_lat, from_lng, to_lat, to_lng):
    api_key = os.environ.get('ORS_API_KEY', '')
    if not api_key:
        return None
    url = "https://api.openrouteservice.org/v2/directions/foot-walking"
    headers = {'Authorization': api_key, 'Content-Type': 'application/json'}
    body = {"start": [from_lng, from_lat], "end": [to_lng, to_lat]}
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=15)
        resp.raise_for_status()
        route = resp.json()['features'][0]['properties']['segments'][0]
        return round(route['duration'] / 60, 1)
    except Exception:
        return None


def _walk_time_fallback(from_lat, from_lng, to_lat, to_lng):
    dist = _haversine_m(from_lat, from_lng, to_lat, to_lng)
    return round(dist / ORS_WALK_SPEED_M_PER_MIN, 1)


def _overpass_query(lat, lng, overpass_tag, radius):
    # Handle tag expressions like "amenity=supermarket" for Overpass QL
    if '=' in overpass_tag and not overpass_tag.startswith('"'):
        key, value = overpass_tag.split('=', 1)
        node_filter = f'node["{key}"="{value}"](around:{radius},{lat},{lng})'
        way_filter = f'way["{key}"="{value}"](around:{radius},{lat},{lng})'
    else:
        node_filter = f'node["{overpass_tag}"](around:{radius},{lat},{lng})'
        way_filter = f'way["{overpass_tag}"](around:{radius},{lat},{lng})'
    query = f"""
[out:json][timeout:25];
(
  {node_filter};
  {way_filter};
);
out center;
"""
    try:
        resp = requests.get(OVERPASS_URL, params={'data': query}, timeout=30)
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


def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_cache(cache):
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def neighbourhood_centroids():
    """Yield (official_name, lat, lng) for all neighbourhoods."""
    with open(NEIGHBOURHOODS_JSON, encoding='utf-8') as f:
        data = json.load(f)
    for official_name, entry in data.items():
        yield official_name, entry['lat'], entry['lng']


def main():
    cache = load_cache()
    original_count = len(cache)

    for poi_type, config in POI_TYPES.items():
        radius = config['radius']
        threshold = config['threshold']
        print(f"\n=== Populating {poi_type} ({radius}m radius) ===")

        for name, lat, lng in neighbourhood_centroids():
            cache_key = f"{name}|{poi_type}"
            if cache_key in cache:
                print(f"  {name}|{poi_type}: already cached, skipping")
                continue

            print(f"  {name}|{poi_type}: querying Overpass...", end='', flush=True)
            overpass_tag = f"amenity={poi_type}"
            results = _overpass_query(lat, lng, overpass_tag=overpass_tag, radius=radius)

            if not results:
                cache[cache_key] = None
                print(" no results")
                save_cache(cache)
                continue

            best = results[0]
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
            print(f" {best['name']} {walk_min} min ({best['distance_m']}m)")
            save_cache(cache)
            time.sleep(1.2)  # be polite to Overpass

    print(f"\nDone. Cache grew from {original_count} to {len(cache)} entries.")


if __name__ == '__main__':
    main()
