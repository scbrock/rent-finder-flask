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
    "distillery": "St.Andrew-Windfields",
    "midtown": "Yonge-Eglinton",
    "north york": "Lansing-Westgate",
    "east york": "Old East York",
    "scarborough": "Woburn",
    "etobicoke": "Etobicoke West Mall",
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
    # MC-333: Off-Toronto municipalities that appear as raw neighbourhood
    # values in scraped data. Mapping to "" (empty) marks them as
    # off_toronto so the default /api/deals view hides them and the
    # /api/meta sidebar doesn't surface them.
    "kleinburg": "",
    "woodbridge": "",
    "concord": "",
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
    # MC-320 additions: common scraped variants that fuzzy-matched wrongly
    "king west": "Niagara",
    "kingsway south": "Kingsway South",
    "dupont and dufferin": "Dufferin Grove",
    "dufferin and davenport": "Dufferin Grove",
    "dovercourt and bloor": "Dovercourt-Wallace Emerson-Junction",
    "roncesvalles and queen": "Roncesvalles",
    "ossington and queen": "Trinity-Bellwoods",
    "spadina and queen": "Kensington-Chinatown",
    "yonge and eglinton": "Yonge-Eglinton",
    "yonge and sheppard": "Willowdale East",
    "yonge and finch": "Willowdale West",
    "dundas and spadina": "Kensington-Chinatown",
    "dundas and bathurst": "Trinity-Bellwoods",
    "bloor and bathurst": "Annex",
    "bloor and spadina": "Annex",
    "bloor and yonge": "Church-Yonge Corridor",
    "queen and broadview": "South Riverdale",
    "broadview and dundas": "North Riverdale",
    "junction area": "Junction Area",
    # MC-333: More intersection / address-fragment patterns. These appear
    # in scraped listings where the "neighborhood" column is actually a
    # street intersection or street address. Mapping them to the nearest
    # official neighbourhood lets the row slot into a real segment instead
    # of being flagged as low-signal.
    "king street west": "Niagara",
    "king st w": "Niagara",
    "queen street west": "University",
    "queen st w": "University",
    "queen and bathurst": "Trinity-Bellwoods",
    "queen and spadina": "Kensington-Chinatown",
    "king and bathurst": "Niagara",
    "king and spadina": "Kensington-Chinatown",
    "king and dufferin": "South Parkdale",
    "spadina and bloor": "Annex",
    "spadina and dundas": "Kensington-Chinatown",
    "spadina and college": "Kensington-Chinatown",
    "spadina and queen": "Kensington-Chinatown",
    "bay and college": "Bay Street Corridor",
    "bay and bloor": "Church-Yonge Corridor",
    "bay and dundas": "Bay Street Corridor",
    "yonge and bloor": "Church-Yonge Corridor",
    "yonge and college": "Church-Yonge Corridor",
    "yonge and dundas": "Church-Yonge Corridor",
    "yonge and eglinton": "Yonge-Eglinton",
    "yonge and sheppard": "Willowdale East",
    "yonge and finch": "Willowdale West",
    "yonge and st clair": "Rosedale-Moore Park",
    "yonge and wellesley": "Church-Yonge Corridor",
    "bathurst and college": "Kensington-Chinatown",
    "bathurst and dundas": "Trinity-Bellwoods",
    "bathurst and st clair": "Forest Hill North",
    "bathurst and eglinton": "Englemount-Lawrence",
    "dundas and keele": "Dovercourt-Wallace Emerson-Junction",
    "dundas and ossington": "Dovercourt-Wallace Emerson-Junction",
    "dundas and dufferin": "Dovercourt-Wallace Emerson-Junction",
    "dupont and lansdowne": "Dovercourt-Wallace Emerson-Junction",
    "dupont and ossington": "Dovercourt-Wallace Emerson-Junction",
    "ossington and dundas": "Dovercourt-Wallace Emerson-Junction",
    "ossington and queen": "Trinity-Bellwoods",
    "islington and bloor": "Islington-City Centre West",
    "kipling and bloor": "Etobicoke West Mall",
    "broadview and queen": "South Riverdale",
    "broadview and gerrard": "North Riverdale",
    "broadview and danforth": "Playter Estates-Danforth",
    "bathurst and front": "Waterfront Communities-The Island",
    "queen and parliament": "Regent Park",
    "queen and carlaw": "South Riverdale",
    # MC-324: Street-name patterns common in URL slugs.
    # Listings with neighborhood="Toronto" / "" often have street+avenue/road/drive
    # encoded in the URL slug (e.g. "toronto-829-pape-ave-bsmt-junior-1bed").
    "pape ave": "Old East York",
    "pape avenue": "Old East York",
    "annette st": "Runnymede-Bloor West Village",
    "annette street": "Runnymede-Bloor West Village",
    "madison ave": "Annex",
    "madison avenue": "Annex",
    "scarlett rd": "Weston-Pellam Park",
    "scarlett road": "Weston-Pellam Park",
    "rockvale ave": "L'Amoreaux",
    "rockvale avenue": "L'Amoreaux",
    "o'connor dr": "Old East York",
    "o'connor drive": "Old East York",
    "oconnor dr": "Old East York",
    "oconnor drive": "Old East York",
    "yore rd": "Newtonbrook East",
    "yore road": "Newtonbrook East",
    "jane st": "Downsview-Roding-CFB",
    "jane street": "Downsview-Roding-CFB",
    "eglinton ave": "Yonge-Eglinton",
    "eglinton avenue": "Yonge-Eglinton",
    "eglinton ave w": "Forest Hill South",
    "eglinton ave e": "Mount Pleasant East",
    "eglinton avenue west": "Forest Hill South",
    "eglinton avenue east": "Mount Pleasant East",
    "st clair": "Casa Loma",
    "st clair ave": "Casa Loma",
    "st clair ave w": "Casa Loma",
    "st clair ave e": "Mount Pleasant East",
    "casa loma": "Casa Loma",
    "lawrence": "Lawrence Park North",
    "lawrence ave": "Lawrence Park North",
    "lawrence ave w": "Yorkdale-Glen Park",
    "lawrence ave e": "Lawrence Park North",
    "sheppard": "Willowdale East",
    "sheppard ave": "Willowdale East",
    "sheppard ave w": "Bathurst Manor",
    "sheppard ave e": "Willowdale East",
    "kipling": "Etobicoke West Mall",
    "islington": "Islington-City Centre West",
    "roncesvalles": "Roncesvalles",
    "high park": "High Park-Swansea",
    "morningside": "Morningside",
    "morningside ave": "Morningside",
    "finch": "Willowdale West",
    "finch ave": "Willowdale West",
    "finch ave w": "Bathurst Manor",
    "finch ave e": "Willowdale West",
    "warden": "L'Amoreaux",
    "warden ave": "L'Amoreaux",
    "mccowan": "Agincourt South-Malvern West",
    "mccowan rd": "Agincourt South-Malvern West",
    "victoria park": "Victoria Village",
    "victoria park ave": "Victoria Village",
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


# MC-333: Names that are *fallback* resolutions (returned by standardize()
# when the raw input is too vague to pinpoint a real neighbourhood).
# Used to flag rows as low-signal even when a resolution is technically
# available. Only checked when the *raw* input is itself generic (so real
# Kijiji API listings legitimately named "Bay Street Corridor" still pass
# through as 'resolved').
_CATCHALL_NAMES = frozenset({
    'toronto', 'city of toronto', 'downtown toronto',
    'bay street corridor',  # the DIRECT_MAP fallback for raw "toronto"
    'ontario', 'gt', 'gta',
})


# MC-333: Non-Toronto cities. Reused by resolve_neighbourhood() to flag
# addresses like "Mississauga, Ontario" / "Aurora, ON" / "Richmond hill"
# as off_toronto without requiring the exact _DIRECT_MAP entry. Strings
# in this list are matched as case-insensitive substrings against the
# raw input.
_NON_TORONTO_CITIES = (
    'mississauga', 'vaughan', 'brampton', 'markham', 'oakville',
    'oshawa', 'richmond hill', 'pickering', 'ajax', 'milton',
    'burlington', 'hamilton', 'kitchener', 'waterloo', 'guelph',
    'aurora', 'newmarket', 'barrie', 'st. catharines', 'st catharines',
    'orangeville', 'caledon', 'king city', 'bolton', 'stouffville',
    'whitby', 'clarington', 'georgina', 'innisfil', 'east gwillimbury',
    'grand valley', 'Uxbridge',
)


def _looks_off_toronto(text: str) -> bool:
    """True if `text` contains a known non-Toronto municipality (case-insensitive substring match)."""
    if not text:
        return False
    lower = text.lower()
    for city in _NON_TORONTO_CITIES:
        if city in lower:
            return True
    return False


# MC-333: Street-suffix tokens used by _looks_like_address() to flag raw
# strings that are likely an address (not a real neighbourhood name).
# These complement the more specific patterns already in _STREET_PATTERNS
# (which are matched via _DIRECT_MAP). _looks_like_address() is a
# *classification* helper — it doesn't try to resolve; it just detects
# that the raw text is an address so callers can hide it as low-signal.
_ADDRESS_SUFFIX_TOKENS = (
    'ave', 'avenue', 'st', 'street', 'road', 'rd',
    'drive', 'dr', 'cres', 'crescent', 'circle', 'cir',
    'court', 'ct', 'crt', 'place', 'pl', 'lane', 'ln',
    'way', 'gardens', 'gdns', 'manor', 'blvd', 'boulevard',
    'terrace', 'terr', 'gate', 'square', 'sq', 'sqr',
    'trail', 'trl', 'path', 'walk', 'row',
)


def _is_intersection(text: str) -> bool:
    """
    Detect street intersections of the form 'X and Y' / 'X & Y' / 'X / Y'.
    Both X and Y must contain a letter (so '2 and 3' is excluded).
    """
    if not text:
        return False
    t = text.strip()
    for sep in (' and ', ' AND ', ' & ', ' + ', ' / '):
        if sep in t:
            a, _, b = t.partition(sep)
            a, b = a.strip(), b.strip()
            if not a or not b:
                continue
            if any(c.isalpha() for c in a) and any(c.isalpha() for c in b):
                return True
    return False


def _looks_like_address(text: str) -> bool:
    """
    Heuristic: does this string look like a street address (rather than
    a neighbourhood name)?

    Returns True for:
      - '30 Carabob Court', '1A Bansley Ave', '15 Martha Eaton Way'
      - 'Bloor St W & Bathurst St', 'Bloor and Yonge', 'DUNDAS AND KEELE'
      - 'Montrose Ave', 'Niska Rd', 'Conference Blvd'
      - '81 Navy Wharf Court - Spadina Avenue / Bremner Blvd   M5V3S2'
      - 'Whitmore Ave, Toronto', 'Beech Avenue'

    Returns False for:
      - 'Bay Street Corridor', 'Annex', 'Niagara', 'Woburn'
      - 'Toronto', 'city of toronto', ''
      - 'Agincourt North'

    Implementation: a string is an address if any of these are true:
      1. Starts with a house number ('30 Carabob Court', '1A Bansley Ave').
      2. Contains an intersection marker ('X and Y' / 'X & Y' / 'X / Y').
      3. The LAST token is a known street suffix ('Montrose Ave',
         'Niska Rd', 'Beech Avenue'). We require the suffix to be the
         final word so real neighbourhood names like 'Bay Street
         Corridor' (suffix 'corridor') don't false-positive.
    """
    if not text:
        return False
    t = text.strip()
    if not t:
        return False

    # 1. Starts with a house number (digit, optionally followed by a letter
    #    like "1A Bansley Ave", then space, then text).
    import re as _re
    if _re.match(r'^\d+[A-Za-z]?\s+', t):
        return True

    # 2. Intersection form.
    if _is_intersection(t):
        return True

    # 3. Last token is a known street suffix.
    lower = t.lower()
    tokens = _re.findall(r"[A-Za-z]+", lower)
    if tokens and tokens[-1] in _ADDRESS_SUFFIX_TOKENS:
        return True

    # 4. "...Suffix, City" pattern (e.g. "Whitmore Ave, Toronto"). The
    #    street suffix is the second-to-last token; the last is a city
    #    name. We only apply this when the second-to-last token is the
    #    suffix (not the city's name) so we don't false-positive on
    #    real neighbourhood names like "Bay Street Corridor" (whose
    #    last 2 tokens are "Street" + "Corridor" — "corridor" isn't
    #    a city).
    if len(tokens) >= 2 and tokens[-2] in _ADDRESS_SUFFIX_TOKENS:
        # "City" can be any of: a known non-Toronto city (Brampton,
        # Mississauga, etc.), 'toronto', 'on', 'ontario', or a
        # common postal suffix. We allow 'toronto' explicitly so
        # "Whitmore Ave, Toronto" classifies as an address.
        last = tokens[-1]
        if (last in _NON_TORONTO_CITIES
                or last in ('toronto', 'on', 'ontario', 'markham',
                            'etobicoke', 'scarborough', 'north york')):
            return True

    return False


def resolve_neighbourhood(raw: str, url: str = '', title: str = '') -> tuple[str, str]:
    """
    MC-333: Resolve a raw scraped neighbourhood string to an official
    Toronto neighbourhood name, with a *status* describing how confident
    the match is.

    Returns a (name, status) tuple where:
      - name: the user-facing neighbourhood label to display. When status
              is 'toronto_catchall' we keep the original raw value so the
              user sees what was actually on the listing (e.g. "Toronto"),
              not the ambiguous "Bay Street Corridor" fallback that
              standardize() would otherwise produce.
      - status: one of:
          'resolved'           — matched an official Toronto neighbourhood
          'toronto_catchall'   — raw was generic ("Toronto" / "city of
                                  toronto" / "downtown toronto") and no
                                  specific match was found in title or URL
                                  slug. Should be hidden from default view.
          'off_toronto'        — non-Toronto municipality (Brampton /
                                  Mississauga / etc.). Should be filtered
                                  by region or hidden.
          'low_signal_address' — raw looks like a street address (numbered
                                  prefix / intersection / street suffix).
                                  Should be hidden from default view.
          'fallback_raw'       — no match, raw doesn't look like an address
                                  (e.g. "Downtown Pickering" mis-typed).
                                  Kept as-is; UI shows it with no chip.

    Resolution order:
      1. If raw is in _GENERIC_NEIGHBOURHOOD_INPUTS ('Toronto' / 'city of
         toronto' / '' / etc.), call standardize(raw, title, url_slug) and
         see if a specific neighbourhood comes back. If yes -> 'resolved'.
         If the resolution itself is a catch-all (Bay Street Corridor
         fallback) or None -> 'toronto_catchall' (keep raw).
      2. If raw is non-generic, call standardize(raw, '', '') (no fallback —
         we have specific data). If it resolves to a name -> 'resolved'.
         If it returns '' -> 'off_toronto' (non-Toronto city).
         If it returns None:
           a. If raw looks like an address -> 'low_signal_address'
           b. Else -> 'fallback_raw'
    """
    raw = (raw or '').strip()
    if not raw:
        # Truly empty — no signal at all. Treat as low-signal so it doesn't
        # pollute /api/meta with empty-string entries.
        return ('', 'low_signal_address')

    url_slug = extract_url_slug(url) if url else ''
    title = title or ''
    raw_lower = raw.lower()
    is_generic_raw = raw_lower in _GENERIC_NEIGHBOURHOOD_INPUTS

    if is_generic_raw:
        # Use the full fallback pipeline (title + url_slug) since the raw
        # value carries no signal on its own.
        result = standardize(raw, title, url_slug)
        if result == '':
            # URL slug contained a non-Toronto city (mississauga/vaughan/...)
            return (raw or 'Non-Toronto', 'off_toronto')
        if result is None:
            # Nothing matched anywhere — keep raw so the user sees the
            # original "Toronto" / "city of toronto" label.
            return (raw, 'toronto_catchall')
        # We got a name. Check if it's still a catch-all fallback (e.g.
        # raw="Toronto" -> "Bay Street Corridor" via the direct map).
        if result.lower() in _CATCHALL_NAMES:
            return (raw, 'toronto_catchall')
        # Genuinely resolved (e.g. raw="Toronto" + url_slug with "yonge
        # and bloor" -> "Yorkville").
        return (result, 'resolved')

    # Non-generic raw. Trust the lookup; only use direct map / exact /
    # substring / fuzzy. Skip title/slug fallback since we have specific
    # data already.
    result = standardize(raw, '', '')
    if result == '':
        return (raw or 'Non-Toronto', 'off_toronto')
    if result is None:
        # No match — classify the raw text.
        if _looks_off_toronto(raw):
            return (raw, 'off_toronto')
        if _looks_like_address(raw):
            return (raw, 'low_signal_address')
        return (raw, 'fallback_raw')
    return (result, 'resolved')


# MC-320: Title-based extraction fallback.
# Listings with neighborhood="Toronto" or "" often encode the real neighbourhood
# in the title text (e.g. "1BR in King West", "Annex 2BR condo").
_GENERIC_NEIGHBOURHOOD_INPUTS = frozenset({
    "toronto", "city of toronto", "gt", "gta", "ontario", "",
    "toronto, on", "toronto, ontario", "downtown toronto",
})

_TITLE_NEIGHBOURHOOD_HINTS = (
    # Ordered roughly by specificity — exact match first.
    "Bay Street Corridor", "Entertainment District", "Financial District",
    "Liberty Village", "Queen West", "King West", "Kensington Market",
    "Trinity Bellwoods", "Trinity-Bellwoods", "Distillery District",
    "Distillery", "St. Lawrence", "St. James Town", "Church-Wellesley",
    "The Beaches", "Leslieville", "Roncesvalles", "Little Italy",
    "Little Portugal", "The Annex", "Annex", "Cabbagetown", "Corktown",
    "Regent Park", "Moss Park", "Garden District", "Harbourfront",
    "Waterfront", "CityPlace", "Fort York", "Niagara", "Downsview",
    "Parkdale", "High Park", "Junction", "Dovercourt", "Dufferin Grove",
    "Palmerston", "Christie Pits", "Seaton Village", "Brockton",
    "Mimico", "Long Branch", "New Toronto", "Islington", "The Kingsway",
    "Yorkville", "Rosedale", "Summerhill", "The Junction",
    # MC-324 additions: extra hints commonly found in URL slugs and titles.
    "Midtown", "Bloor West", "East York", "Scarborough", "Etobicoke",
    "North York", "West End", "Old East York", "Downtown Core",
    "Danforth", "Danforth East York", "Greek Town", "Chinatown",
)


# Street patterns — MC-324 — used to extract neighbourhoods from URL slugs.
# Most match a known _DIRECT_MAP key. Order matters: longer patterns first.
_STREET_PATTERNS = (
    "eglinton avenue west", "eglinton avenue east",
    "eglinton ave w", "eglinton ave e",
    "eglinton avenue", "eglinton ave",
    "lawrence avenue west", "lawrence avenue east",
    "lawrence ave w", "lawrence ave e",
    "lawrence avenue", "lawrence ave",
    "sheppard avenue west", "sheppard avenue east",
    "sheppard ave w", "sheppard ave e",
    "sheppard avenue", "sheppard ave",
    "finch avenue west", "finch avenue east",
    "finch ave w", "finch ave e",
    "finch avenue", "finch ave",
    "victoria park avenue", "victoria park ave",
    "morningside avenue", "morningside ave",
    "mccowan road", "mccowan rd",
    "st clair avenue west", "st clair avenue east",
    "st clair ave w", "st clair ave e",
    "st clair avenue", "st clair ave",
    "o'connor drive", "o'connor dr",
    "oconnor drive", "oconnor dr",
    "rockvale avenue", "rockvale ave",
    "scarlett road", "scarlett rd",
    "madison avenue", "madison ave",
    "annette street", "annette st",
    "pape avenue", "pape ave",
    "yore road", "yore rd",
    "jane street", "jane st",
    "warden avenue", "warden ave",
    "casa loma",  # landmark
    "roncesvalles",  # street + neighbourhood
    "islington",  # street + neighbourhood
    "kipling",  # street + neighbourhood
    # MC-333: Intersection patterns. Order matters — longer first.
    # These are checked against URL slugs (after hyphen->space) so
    # "toronto-11-yonge-and-bloor-condo" becomes "...yonge and bloor..."
    # and resolves to Yorkville via _DIRECT_MAP. Many of these are already
    # in _DIRECT_MAP; adding them here just makes _scan_for_hint find
    # them in URL slugs / titles.
    "king and bathurst", "king and spadina", "king and dufferin",
    "queen and bathurst", "queen and spadina", "queen and parliament",
    "queen and broadview", "queen and carlaw",
    "bay and college", "bay and bloor", "bay and dundas",
    "yonge and bloor", "yonge and college", "yonge and dundas",
    "yonge and eglinton", "yonge and sheppard", "yonge and finch",
    "yonge and st clair", "yonge and wellesley",
    "bathurst and college", "bathurst and dundas", "bathurst and bloor",
    "bathurst and st clair", "bathurst and eglinton",
    "bathurst and front", "bathurst and queen",
    "dundas and bathurst", "dundas and spadina", "dundas and keele",
    "dundas and ossington", "dundas and dufferin",
    "bloor and bathurst", "bloor and spadina", "bloor and yonge",
    "spadina and bloor", "spadina and dundas", "spadina and queen",
    "spadina and college", "spadina and king",
    "dupont and lansdowne", "dupont and ossington",
    "ossington and dundas", "ossington and queen",
    "islington and bloor", "kipling and bloor",
    "broadview and queen", "broadview and gerrard",
    "broadview and danforth", "broadview and dundas",
    "king street west", "queen street west",
    "yonge street", "bay street",
)


def extract_url_slug(url: str) -> str:
    """
    Extract the descriptive slug from a rental listing URL.

    - Craigslist: /view/d/<slug>/<id>        -> '<slug>'
    - Kijiji:     /v-<cat>/<city>/<slug>/<id> -> '<slug>'

    Returns "" if URL is malformed or no slug can be extracted.
    """
    if not url or not isinstance(url, str):
        return ""
    try:
        from urllib.parse import urlparse
        parts = urlparse(url).path.strip('/').split('/')
        if 'craigslist.org' in url and len(parts) >= 4:
            # parts = ['view', 'd', '<slug>', '<id>']
            return parts[2] or ""
        elif 'kijiji.ca' in url and len(parts) >= 4:
            # parts = ['v-apartments-condos', 'city-of-toronto', '<slug>', '<id>']
            return parts[2] or ""
        # Generic fallback: second-to-last path segment is usually the slug
        elif len(parts) >= 2:
            return parts[-2] or ""
    except Exception:
        pass
    return ""


def _scan_for_hint(text: str) -> str | None:
    """
    Scan text for known neighbourhood hints. Returns the first match's
    official name or None.

    Checks in order:
    1. Street patterns (e.g. "pape ave" -> "Old East York") — most specific.
    2. Neighbourhood hints (e.g. "King West" -> "Niagara").
    """
    if not text:
        return None
    text_lower = text.lower()
    # 1. Street patterns — match via _DIRECT_MAP for accuracy
    for pattern in _STREET_PATTERNS:
        if pattern in text_lower:
            # Look up via _DIRECT_MAP (skip fuzzy)
            if pattern in _DIRECT_MAP and _DIRECT_MAP[pattern]:
                return _DIRECT_MAP[pattern]
    # 2. Neighbourhood hints
    for hint in _TITLE_NEIGHBOURHOOD_HINTS:
        if hint.lower() in text_lower:
            result = lookup(hint)
            if result is not None:
                return result['official_name']
    return None


def _try_text_as_neighbourhood(text: str) -> str | None:
    """
    Try to resolve `text` as a neighbourhood. Returns the official name,
    or "" for non-Toronto, or None if no match.
    """
    if not text:
        return None
    result = lookup(text)
    if result is not None:
        return result['official_name']
    # Non-Toronto check
    norm = _normalize(text)
    if norm in _DIRECT_MAP and not _DIRECT_MAP[norm]:
        return ""
    return None


def standardize(raw_neighbourhood: str, title: str = "", url_slug: str = "") -> str | None:
    """
    Map a raw scraped neighbourhood (with optional title and URL-slug fallback)
    to an official Toronto neighbourhood name. Returns None if no good match.

    Resolution order:
    1. If raw_neighbourhood is specific (not a generic "Toronto"/""):
       a. lookup(raw_neighbourhood) — exact / direct-map / substring / fuzzy
       b. If lookup succeeded, return official name.
    2. Check if raw_neighbourhood is a non-Toronto municipality (return "").
    3. Try the title (if provided):
       a. lookup(title) — may pick up "1BR in King West" -> "Niagara"
       b. Scan title for known hints ("King West", "Annex", "Yorkville", etc.)
    4. Try the URL slug (if provided) — listings often encode the real
       neighbourhood in the URL slug (e.g. "toronto-2br-annex-apartment-with-balcony").
       For slugs, we ONLY scan for known hints (street patterns + neighbourhood
       hints) — fuzzy lookup on noisy slug text returns garbage matches.
    5. Return None — caller should keep the original string.

    Returns:
        - str: official neighbourhood name (e.g. "Bay Street Corridor")
        - "": empty string if non-Toronto municipality (Mississauga, Vaughan, etc.)
        - None: if no match at all — caller should keep the original string
    """
    # Generic inputs like "Toronto" / "city of toronto" / "" are too vague for
    # the direct lookup path — the fuzzy match can return weird results
    # (e.g. lookup("city of toronto") -> "Agincourt North" via fuzzy noise).
    # Skip step 1 for generic values and rely on the title/slug scan instead.
    norm_lower = (raw_neighbourhood or "").lower().strip()
    is_generic = norm_lower in _GENERIC_NEIGHBOURHOOD_INPUTS

    if not is_generic:
        # 1. Direct lookup on specific neighbourhood
        if raw_neighbourhood:
            result = _try_text_as_neighbourhood(raw_neighbourhood)
            if result is not None:
                return result

    # 2. Try the title as a whole (e.g. "1BR Condo in King West")
    if title:
        result = _try_text_as_neighbourhood(title)
        if result is not None:
            return result
        hint_match = _scan_for_hint(title)
        if hint_match is not None:
            return hint_match

    # 3. Try the URL slug — scan for hints ONLY (fuzzy match on slug is noisy).
    # Check non-Toronto first via direct map scan (e.g. "mississauga" in slug).
    if url_slug:
        # Convert slug to readable text
        readable_slug = url_slug.replace('-', ' ').replace('_', ' ').strip()
        readable_lower = readable_slug.lower()
        # Non-Toronto slug check — scan for known non-Toronto municipalities
        non_toronto_cities = ('mississauga', 'vaughan', 'brampton', 'markham',
                              'oakville', 'oshawa', 'richmond hill', 'pickering',
                              'ajax', 'milton', 'burlington', 'hamilton',
                              'kitchener', 'waterloo', 'guelph')
        if any(city in readable_lower for city in non_toronto_cities):
            return ""
        hint_match = _scan_for_hint(readable_slug)
        if hint_match is not None:
            return hint_match

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