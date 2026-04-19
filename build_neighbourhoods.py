"""
Build toronto_neighbourhoods.json from official City of Toronto GeoJSON.
Uses shapely to compute polygon centroids from the jasonicarter/toronto-geojson repo.
MC-260: Rent finder: proper Toronto neighbourhood data from City open data
"""

import urllib.request, json, os
from shapely import geometry as shg

def download_and_build():
    url = 'https://raw.githubusercontent.com/jasonicarter/toronto-geojson/master/toronto_crs84.geojson'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    resp = urllib.request.urlopen(req, timeout=30)
    data = resp.read()
    gj = json.loads(data.decode('utf-8'))

    neighbourhoods = {}
    for feat in gj['features']:
        name = feat['properties']['AREA_NAME']
        # Strip area code suffix like ' (97)'
        clean_name = name.split(' (')[0].strip()
        geom = shg.shape(feat['geometry'])
        cx, cy = geom.centroid.x, geom.centroid.y  # GeoJSON [lng, lat] → we store {lat, lng}
        neighbourhoods[clean_name] = {'lat': round(cy, 6), 'lng': round(cx, 6)}

    out = os.path.join(os.path.dirname(__file__), 'data', 'toronto_neighbourhoods.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(neighbourhoods, f, indent=2, ensure_ascii=False)
    print(f'Saved {len(neighbourhoods)} neighbourhoods to {out}')
    return neighbourhoods

if __name__ == '__main__':
    data = download_and_build()
    print(f'\nSample entries:')
    for k in list(data.keys())[:10]:
        print(f'  {k}: {data[k]}')