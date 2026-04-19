"""
Neighbourhood lookup — maps raw scraped neighbourhood strings to
official City of Toronto neighbourhood names using fuzzy matching.

MC-260: Rent finder: proper Toronto neighbourhood data from City open data
"""

import json, os, re
from difflib import SequenceMatcher

APP_DIR = os.path.dirname(os.path.abspath(__file__))
OFFICIAL_JSON = os.path.join(APP_DIR, 'data', 'toronto_neighbourhoods.json')

# ── Official neighbourhood data ─────────────────────────────────────────────

def _load_official() -> dict[str, dict]:
    """Load official neighbourhood centroids from data/toronto_neighbourhoods.json."""
    if os.path.exists(OFFICIAL_JSON):
        with open(OFFICIAL_JSON, encoding='utf-8') as f:
            return json.load(f)
    return {}

OFFICIAL_NEIGHBOURHOODS: dict[str, dict] = _load_official()
OFFICIAL_NAMES: list[str] = sorted(OFFICIAL_NEIGHBOURHOODS.keys())

# ── Normalization ────────────────────────────────────────────────────────────

def _normalize(n: str) -> str:
    """Strip noise from neighbourhood strings."""
    n = str(n).strip().lower()
    n = re.sub(r"^\d+\s+[\w\s]+(ave|avenue|st|street|road|rd|drive|dr|cres|crescent|cir|circle|blvd|boulevard|gate|place|pl|terrace|ter)\b.*", "", n)
    n = re.sub(r"^toronto\s*,\s*", "", n)
    n = re.sub(r"^city of toronto\s*,?\s*", "", n)
    n = re.sub(r"^downtown toronto\s*-.*", "downtown toronto", n)
    n = re.sub(r"\s*[\[\(].*?[\]\)]$", "", n)
    n = n.strip().rstrip(",").strip()
    return n

# ── Direct overrides for common scraped variants ────────────────────────────

_DIRECT_MAP: dict[str, str] = {
    # Standardize scraped names → official names
    "the annex": "Annex",
    "annex.toronto": "Annex",
    "annex toronto": "Annex",
    "bay street corridor": "Bay Street Corridor",
    "the beaches": "The Beaches",
    "beaches": "The Beaches",
    "toronto beach": "The Beaches",
    "birchcliffe-cliffside": "Birchcliffe-Cliffside",
    "cliffside": "Birchcliffe-Cliffside",
    "cliffside, scarborough": "Birchcliffe-Cliffside",
    "blake-jones": "Blake-Jones",
    "bloor / ossington": "Dovercourt-Wallace Emerson-Junction",
    "bloor west & bathurst st": "Dovercourt-Wallace Emerson-Junction",
    "bloor west village": "Runnymede-Bloor West Village",
    "broadview": "Broadview North",
    "broadview and danforth": "Playter Estates-Danforth",
    "broadview north": "Broadview North",
    "church and wellesley": "Church-Yonge Corridor",
    "church & wellesley": "Church-Yonge Corridor",
    "church-yonge corridor": "Church-Yonge Corridor",
    "corktown": "Cabbagetown-South St.James Town",
    "corso italia": "Corso Italia-Davenport",
    "distillery district": "St.Andrew-Windfields",
    "dovercourt village": "Dovercourt-Wallace Emerson-Junction",
    "downtown toronto": "Bay Street Corridor",
    "downtown, toronto": "Bay Street Corridor",
    "toronto": "Bay Street Corridor",
    "city of toronto": "Bay Street Corridor",
    "downtown toronto near sick kids hospital, u of t, tmu create": "St.Andrew-Windfields",
    "downtown toronto near toronto general hospital, u of t": "St.Andrew-Windfields",
    "dufferin st. & sheppard ave. by subway": "Downsview-Roding-CFB",
    "dundas & ossington": "Dovercourt-Wallace Emerson-Junction",
    "dundas and ossington": "Dovercourt-Wallace Emerson-Junction",
    "edenbridge-humber valley": "Edenbridge-Humber Valley",
    "eglinton east": "Eglinton East",
    "englemount-lawrence": "Englemount-Lawrence",
    "entertainment district": "Bay Street Corridor",
    "entertainment - financial district": "Bay Street Corridor",
    "entertainment-financial district": "Bay Street Corridor",
    "entertainment district/king west": "Bay Street Corridor",
    "enterainment district": "Bay Street Corridor",
    "etobicoke": "Etobicoke West Mall",
    "etobicoke, mimico": "Mimico",
    "flemingdon park": "Flemingdon Park",
    "forest hill north": "Forest Hill North",
    "forest hill south / bathurst & st clair": "Forest Hill South",
    "garden district": "Cabbagetown-South St.James Town",
    "guildwood": "Guildwood",
    "harbourfront": "Waterfront Communities-The Island",
    "high park-swansea": "High Park-Swansea",
    "humber bay shores": "Humber Heights-Westmount",
    "humber summit": "Humber Summit",
    "jane and weston rd": "Mount Olive-Silverstone-Jamestown",
    "jane & weston rd": "Mount Olive-Silverstone-Jamestown",
    "jane & weston": "Mount Olive-Silverstone-Jamestown",
    "jane and weston": "Mount Olive-Silverstone-Jamestown",
    "junction area": "Junction Area",
    "keele st and bloor st w": "Keelesdale-Eglinton West",
    "keele st  and bloor st  w": "Keelesdale-Eglinton West",
    "keele and bloor": "Keelesdale-Eglinton West",
    "keele & bloor": "Keelesdale-Eglinton West",
    "kensington market": "Kensington-Chinatown",
    "lakeshore, etobicoke": "Mimico",
    "lawrence heights": "Lawrence Park North",
    "leaside-bennington": "Leaside-Bennington",
    "liberty village": "University",  # actually adjacent but not an official name
    "little portgual": "Little Portugal",
    "little portugal": "Little Portugal",
    "long branch": "Long Branch",
    "malvern west": "Agincourt South-Malvern West",
    "mimico": "Mimico",
    "moss park": "Moss Park",
    "mount pleasant & st. clair": "Mount Pleasant East",
    "l'amoreaux west": "L'Amoreaux",
    "north riverdale": "North Riverdale",
    "north st.james town": "North St.James Town",
    "north st. james town": "North St.James Town",
    "north st james town": "North St.James Town",
    "north toronto": "North St.James Town",  # actually North Toronto proper
    "north york": "Lansing-Westgate",
    "north york": "Lansing-Westgate",
    "old town": "St.Andrew-Windfields",
    "old east york": "Old East York",
    "ossington @ bloor st. west": "Dovercourt-Wallace Emerson-Junction",
    "ossington @ bloor st west": "Dovercourt-Wallace Emerson-Junction",
    "ossington and bloor": "Dovercourt-Wallace Emerson-Junction",
    "parkdale": "South Parkdale",
    "south parkdale": "South Parkdale",
    "parpkdale": "South Parkdale",
    "pelmo park-humberlea": "Pelmo Park-Humberlea",
    "playter estates": "Playter Estates-Danforth",
    "queen west": "University",  # Queen West is not an official neighbourhood
    "queen west-kensington": "Kensington-Chinatown",
    "regent park": "Regent Park",
    "riverside": "South Riverdale",
    "riverdale": "North Riverdale",
    "rockcliffe-smythe": "Rockcliffe-Smythe",
    "rosedale/annex": "Rosedale-Moore Park",
    "scarborough": "Woburn",
    "sheppard/warden": "L'Amoreaux",  # Sheppard & Warden is Scarborough
    "stockyards/junction": "Junction Area",
    "stockyards junction": "Junction Area",
    "the danny": "University",
    "the daniel": "University",
    "theatre district": "Bay Street Corridor",
    "toronto, christie pits": "Wychwood",
    "toronto, little italy": "Palmerston-Little Italy",
    "toronto, waterfront communities": "Waterfront Communities-The Island",
    "toronto, willowsdale east": "Willowdale East",
    "toronto, woodbine-lumsden": "Woodbine-Lumsden",
    "trinity bellwood": "Trinity-Bellwoods",
    "trinity bellwoods": "Trinity-Bellwoods",
    "trinity-bellwoods": "Trinity-Bellwoods",
    "university and dundas": "University",
    "university/dundas": "University",
    "waterfront communities": "Waterfront Communities-The Island",
    "west hill": "West Hill",
    "west hill, toronto": "West Hill",
    "west hill, scarborough": "West Hill",
    "west queen west": "University",
    "west shore": "Humber Heights-Westmount",
    "weston, toronto": "Weston",
    "woodbine corridor": "Woodbine Corridor",
    "yorkville": "Rosedale-Moore Park",
    "downtown toronto - south rosedale - summerhill - yorkville": "Rosedale-Moore Park",
    # ── Additional mappings from real scraped data ─────────────────────────
    "don mills and lawrence avenue east": "Banbury-Don Mills",
    "bathurst/queens quay": "Mimico",
    "crosby": "Cabbagetown-South St.James Town",
    "clanton park, toronto": "Clanton Park",
    "sonoma heights": "Kingsway South",
    "toronto, ontario": "Bay Street Corridor",
    "toronto, on": "Bay Street Corridor",
    "north riverdale": "North Riverdale",
    "northy": "North St.James Town",
    # Non-Toronto municipalities — return empty string so region_map excludes them
    "brampton": "",
    "markham": "",
    "mississauga": "",
    "mississauga, on": "",
    "oakville": "",
    "oshawa": "",
    "richmond hill": "",
    "vaughan": "",
    "york region": "",
    # Known invalid/neighbourhood noise that normalizes away
    "ontario": "",
    "christie pits": "",
    # Address noise that slips through normalization
    "278 archerhill circ": "L'Amoreaux",
    "dalton road": "L'Amoreaux",
}

# ── Fuzzy matching ────────────────────────────────────────────────────────────

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def lookup(raw_neighbourhood: str) -> dict | None:
    """
    Map a raw scraped neighbourhood string to official neighbourhood data.
    Returns dict with: official_name, lat, lng, or None if no match.
    """
    if not raw_neighbourhood:
        return None

    norm = _normalize(raw_neighbourhood)

    # Direct map lookup — empty string means non-Toronto (excluded from scoring)
    if norm in _DIRECT_MAP:
        official_name = _DIRECT_MAP[norm]
        if not official_name:
            return None  # Non-Toronto municipality
        if official_name in OFFICIAL_NEIGHBOURHOODS:
            d = OFFICIAL_NEIGHBOURHOODS[official_name].copy()
            d['official_name'] = official_name
            return d
        return None

    # Exact match on normalized
    for name in OFFICIAL_NAMES:
        if _normalize(name) == norm:
            d = OFFICIAL_NEIGHBOURHOODS[name].copy()
            d['official_name'] = name
            return d

    # Substring match
    for name in OFFICIAL_NAMES:
        norm_name = _normalize(name)
        if norm_name in norm or norm in norm_name:
            d = OFFICIAL_NEIGHBOURHOODS[name].copy()
            d['official_name'] = name
            return d

    # Fuzzy match — pick best of names where either is contained in the other
    best_score = 0.0
    best_name = None
    for name in OFFICIAL_NAMES:
        score = _similarity(norm, _normalize(name))
        if score > best_score:
            best_score = score
            best_name = name

    if best_score >= 0.6 and best_name:
        d = OFFICIAL_NEIGHBOURHOODS[best_name].copy()
        d['official_name'] = best_name
        d['match_score'] = round(best_score, 2)
        return d

    return None


def get_centroid(raw_neighbourhood: str) -> tuple[float, float] | None:
    """Return (lat, lng) for a raw neighbourhood, or None."""
    result = lookup(raw_neighbourhood)
    if result:
        return result['lat'], result['lng']
    return None


if __name__ == '__main__':
    # Test with actual scraped neighbourhood names
    test_cases = [
        'Annex', 'Annex.Toronto', 'Downtown Toronto', 'Kensington market',
        'High Park-Swansea', 'Trinity Bellwoods', 'The Beaches', 'Liberty Village',
        'Yorkville', 'Entertainment District', 'Little Portugal', 'Etobicoke, Mimico',
        'Don Mills and Lawrence Avenue East', 'Lawrence Heights', 'North York',
    ]
    print('Neighbourhood lookup test:')
    for tc in test_cases:
        result = lookup(tc)
        if result:
            name = result['official_name']
            lat = result['lat']
            lng = result['lng']
            print(f'  {repr(tc):50s} => {name} ({lat}, {lng})')
        else:
            print(f'  NOT FOUND: {repr(tc)}')
    print(f'Total official neighbourhoods: {len(OFFICIAL_NEIGHBOURHOODS)}')