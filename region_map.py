"""
Toronto region mapper — comprehensive neighbourhood → region mapping.
Maps neighbourhood names to one of 6 Toronto regions:
  Downtown, East End, West End, North York, Etobicoke, Scarborough
Also handles non-Toronto municipalities (Mississauga, Brampton, Richmond Hill,
Oakville, Vaughan, Oshawa) by returning the empty string (excluded from scoring).
MC-249: Rent finder: filter listings by Toronto region
"""

import re


# ── Non-Toronto municipalities (outside the city proper) ─────────────────────

_NON_TORONTO = {
    "mississauga", "mississauga, on", "brampton", "oakville",
    "richmond hill", "richmond hill, ontario", "vaughan",
    "oshawa", "york region", "markham", "caledon", "halton hills",
    "pickering", "ajax", "whitby",
}


# ── Normalization helpers ──────────────────────────────────────────────────────

def _normalize(n: str) -> str:
    """Strip common noise from neighbourhood strings and lowercase."""
    n = str(n).strip().lower()
    # Remove known address noise (civic numbers + street names)
    n = re.sub(r"^\d+\s+[\w\s]+(ave|avenue|st|street|road|rd|drive|dr|cres|crescent|cir|circle|blvd|boulevard|gate|place|pl|terrace|ter)\b.*", "", n)
    # Remove "toronto, " prefix
    n = re.sub(r"^toronto\s*,\s*", "", n)
    n = re.sub(r"^city of toronto\s*,?\s*", "", n)
    n = re.sub(r"^downtown toronto\s*-.*", "downtown toronto", n)
    # Remove parenthetical suffixes
    n = re.sub(r"\s*[\[\(].*?[\]\)]$", "", n)
    # Remove trailing commas/spaces
    n = n.strip().rstrip(",").strip()
    return n


def _key(n: str) -> str:
    """Canonical lookup key for a neighbourhood string."""
    return _normalize(n).strip()


# ── Master neighbourhood → region lookup ────────────────────────────────────

# Format: "canonical name" → "Region"
# Include common variants/spellings.
_NEIGHBOURHOOD_REGION = {

    # ── DOWNTOWN ────────────────────────────────────────────────────────────
    "toronto": "Downtown",
    "city of toronto": "Downtown",
    "downtown toronto": "Downtown",
    "downtown, toronto": "Downtown",
    "toronto, ontario": "Downtown",
    "toronto, on": "Downtown",
    "toronto, on canada": "Downtown",
    "annex": "Downtown",
    "annex toronto": "Downtown",
    "annex.toronto": "Downtown",
    "bloor west village": "West End",
    "bloor / ossington": "West End",
    "bloor west & bathurst st": "West End",
    "broadview": "East End",
    "broadview and danforth": "East End",
    "case loma": "Downtown",
    "church & wellesley": "Downtown",
    "church-yonge corridor": "Downtown",
    "church and wellesley": "Downtown",
    "corktown": "Downtown",
    "corso italia": "West End",
    "crosby": "Downtown",
    "distillery district": "Downtown",
    "dundas & ossington": "West End",
    "dundas and ossington": "West End",
    "entertainment - financial district": "Downtown",
    "entertainment district": "Downtown",
    "entertainment district/king west": "Downtown",
    "entertainment-financial district": "Downtown",
    "financial district": "Downtown",
    "garden district": "Downtown",
    "harbourfront": "Downtown",
    "harbourfront centre": "Downtown",
    "june callwood": "Downtown",
    "kensington market": "Downtown",
    "kensington-chinatown": "Downtown",
    "kensington chinatown": "Downtown",
    "liberty village": "Downtown",
    "little italy": "Downtown",
    "little portgual": "West End",   # typo: "Little Portugal"
    "little portugal": "West End",
    "moss park": "Downtown",
    "north st. james town": "Downtown",
    "north st james town": "Downtown",
    "north st.james town": "Downtown",
    "old town": "Downtown",
    "old town toronto": "Downtown",
    "ossington @ bloor st. west": "West End",
    "ossington @ bloor st west": "West End",
    "ossington and bloor": "West End",
    "parkdale": "West End",
    "parkdale, toronto": "West End",
    "palmerston-little italy, toronto": "Downtown",
    "palmerston little italy": "Downtown",
    "queen west": "Downtown",
    "queen west-kensington": "Downtown",
    "west queen west": "Downtown",
    "regent park": "Downtown",
    "riverside": "East End",
    "rosedale": "Downtown",
    "rosedale/annex": "Downtown",
    "south riverdale": "East End",
    "st lawrence market": "Downtown",
    "st. lawrence market": "Downtown",
    "stockyards/junction": "West End",
    "stockyards junction": "West End",
    "the daniel": "Downtown",
    "the danny": "Downtown",
    "theatre district": "Downtown",
    "toronto c08": "Downtown",
    "toronto downtown walk to eaton center, u of t, tmu, hospital": "Downtown",
    "toronto, christie pits": "West End",
    "toronto, little italy": "Downtown",
    "toronto, waterfront communities": "Downtown",
    "trinity bellwood": "Downtown",
    "trinity bellwoods": "Downtown",
    "trinity-bellwoods": "Downtown",
    "university and dundas": "Downtown",
    "university/dundas": "Downtown",
    "university": "Downtown",
    "wallace emerson": "West End",
    "waterfront communities": "Downtown",
    "yorkville": "Downtown",
    "yorkville, toronto": "Downtown",
    "south rosedale": "Downtown",
    "summerhill": "Downtown",
    "rosedale-moore park": "Downtown",
    " deer park": "Downtown",
    "deer park": "Downtown",
    "the annex": "Downtown",
    "harbord village": "Downtown",
    "bay street corridor": "Downtown",
    "central waterfront": "Downtown",
    "northy": "Downtown",
    "discovery district": "Downtown",
    "garden district": "Downtown",
    "corktown, toronto": "Downtown",
    "regent park, toronto": "Downtown",
    "moore park": "Downtown",
    "taddlewood": "Downtown",
    "north riverdale": "East End",
    "playter estates": "East End",
    "logan ave": "East End",
    "t帽": "Downtown",

    # ── EAST END ──────────────────────────────────────────────────────────
    "the beaches": "East End",
    "beaches": "East End",
    "woodbine beach": "East End",
    "kew beach": "East End",
    "balmy beach": "East End",
    "east end": "East End",
    "east york": "East End",
    "east toronto": "East End",
    "danforth": "East End",
    "the danforth": "East End",
    "broadview north": "East End",
    "woodbine heights": "East End",
    "woodbine-corridor": "East End",
    "woodbine lumsden": "East End",
    "woodbine-lumsden": "East End",
    "toronto beach": "East End",
    "toronto, woodbine-lumsden": "East End",
    "toronto beach": "East End",
    "riverdale": "East End",
    "south riverdale": "East End",
    "north riverdale": "East End",
    "leslieville": "East End",
    "jones valley": "East End",
    "oakridge": "East End",
    "oakwood": "West End",  # Oakwood Ave is near West End
    "birchcliffe-cliffside": "East End",
    "cliffside": "East End",
    "cliffside, scarborough": "East End",
    "guildwood": "East End",
    "swansea": "West End",  # Actually Swansea is West End (South of Bloor)
    "high park-swansea": "West End",
    "riverside": "East End",
    "the beach": "East End",
    "woodbine": "East End",
    "mainstreet": "East End",
    "danforth & pope": "East End",
    "toronto danforth & pope": "East End",
    "east york, toronto": "East End",
    "broadview and danforth": "East End",
    "greenwood": "East End",
    "chinbury": "East End",
    "keating": "East End",
    "sloane": "East End",
    "wynford": "East End",
    "parkwoods-donalda": "North York",
    "parkwoods": "North York",
    "donalda": "North York",
    "st. jamestown": "Downtown",

    # ── WEST END ──────────────────────────────────────────────────────────
    "west end": "West End",
    "junction": "West End",
    "the junction": "West End",
    "junction area": "West End",
    "roncesvalles": "West End",
    "roncesvalles village": "West End",
    "parkdale": "West End",
    "south parkdale": "West End",
    "bloordale": "West End",
    "dufferin grove": "West End",
    "dufferin": "West End",
    "dufferin, toronto": "West End",
    "little portugal": "West End",
    "little italy toronto": "West End",
    "ossington": "West End",
    "bathurst": "West End",
    "bathurst harbourbord": "Downtown",
    "bathurst/harbord": "Downtown",
    "bathurst/queens quay": "Downtown",
    "bathurst and queens quay": "Downtown",
    "bathurst manor": "North York",
    "jane and weston rd": "West End",
    "jane and weston": "West End",
    "jane & weston rd": "West End",
    "jane & weston": "West End",
    "weston": "West End",
    "weston, toronto": "West End",
    "weston rd": "West End",
    "weston, toronto": "West End",
    "mount dennis": "West End",
    "toronto, mount dennis": "West End",
    "mount dennis, toronto": "West End",
    "keele st and bloor st w": "West End",
    "keele st  and bloor st  w": "West End",
    "keele & bloor": "West End",
    "keele and bloor": "West End",
    "bloor west": "West End",
    "bloor oakwood": "West End",
    "lakeshore": "West End",
    "lakeshore district": "West End",
    "mimico": "Etobicoke",
    "new toronto": "Etobicoke",
    "long branch": "Etobicoke",
    "the queensway": "Etobicoke",
    "king west": "Downtown",
    "king street west": "Downtown",
    "princess-royal": "Etobicoke",
    "markland": "Etobicoke",
    "aleron": "West End",
    "earlscourt": "West End",
    "carlton": "Downtown",
    "college": "Downtown",
    "dundas": "Downtown",
    "queensway": "Etobicoke",
    "the kingsway": "Etobicoke",
    "humber bay": "Etobicoke",
    "humber": "West End",
    "humberlea": "West End",
    "humber summit": "North York",
    "rockcliffe-smythe": "West End",
    "edenbridge-humber valley": "West End",
    "pelmo park-humberlea": "West End",
    "west shore": "West End",
    "dovercourt village": "West End",
    "niagara": "West End",
    "t恤": "West End",

    # ── NORTH YORK ────────────────────────────────────────────────────────
    "north york": "North York",
    "north york, toronto": "North York",
    "north york, on": "North York",
    "toronto, willowdale east": "North York",
    "willowdale east": "North York",
    "willowdale": "North York",
    "willowdale west": "North York",
    "willowdale east, toronto": "North York",
    "newtonbrook": "North York",
    "newtonbrook west, toronto": "North York",
    "newtonbrook west": "North York",
    "newtonbrook east": "North York",
    "bayview village": "North York",
    "bayview": "North York",
    "york mills": "North York",
    "york mills, toronto": "North York",
    "yorkmills": "North York",
    "don mills": "North York",
    "don mills and lawrence avenue east": "North York",
    "don mills, toronto": "North York",
    "donmills": "North York",
    "fairview": "North York",
    "fairview, toronto": "North York",
    "hillcrest village": "North York",
    "henry farm": "North York",
    "stong": "North York",
    "yorkview": "North York",
    "sunset": "North York",
    "baycrest": "North York",
    "flemingdon park": "North York",
    "dean park": "North York",
    "north toronto": "North York",
    "midtown": "North York",
    "midtown toronto": "North York",
    "davisville": "North York",
    "davisville, toronto": "North York",
    "leaside": "North York",
    "leaside-bennington": "North York",
    "leaside-benington": "North York",
    "golfdale gardens": "North York",
    "englemount-lawrence": "North York",
    "clanton park": "North York",
    "clanton park, toronto": "North York",
    "cedar wood": "North York",
    "cedarwood": "North York",
    "l'amoreaux west": "North York",
    "l'amoreaux": "Scarborough",   # L'Amoreaux straddles North York/Scarborough boundary; use Scarborough
    "downsview": "North York",
    "downsview park": "North York",
    "black Creek": "North York",
    "black creek": "North York",
    "oakdale": "North York",
    "fion": "North York",
    "ion": "North York",
    "finch": "North York",
    "finch ave and willowdale avenue area": "North York",
    "finch and willowdale": "North York",
    "dufferin st. & sheppard ave. by subway": "North York",
    "dufferin and sheppard": "North York",
    "sheppard and dufferin": "North York",
    "sheppard / warden": "North York",
    "sheppard/warden": "North York",
    "sheppard and warden": "North York",
    "lawrence heights": "North York",
    "lawrence heights, toronto": "North York",
    "york university heights": "North York",
    "chalkfarm": "North York",
    "steldon": "North York",
    "bradstock": "North York",
    "dorset park": "Scarborough",
    "dorset park, toronto": "Scarborough",
    "warkworth": "North York",
    "morningside heights": "Scarborough",
    "morningside": "Scarborough",
    "malvern": "Scarborough",
    "malvern west": "Scarborough",
    "misted": "North York",
    "milliken": "Scarborough",
    "steeles": "Scarborough",
    "beechborough": "North York",
    "mount olive": "North York",
    "silverthorn": "West End",
    "silverthorn, toronto": "West End",
    "calder": "North York",
    "keeles": "North York",
    "glen": "North York",
    "glen, toronto": "North York",
    "fender": "North York",
    "tam": "North York",
    "mary": "North York",
    "not": "North York",
    "jay": "North York",
    "cedar": "Scarborough",
    "cedar, toronto": "Scarborough",

    # ── ETOBICOKE ────────────────────────────────────────────────────────
    "etobicoke": "Etobicoke",
    "etobicoke, mimico": "Etobicoke",
    "etobicoke centre": "Etobicoke",
    "etobicoke city centre": "Etobicoke",
    "the kingsway": "Etobicoke",
    "kingsway": "Etobicoke",
    "kingsway, toronto": "Etobicoke",
    "humber bay": "Etobicoke",
    "humber bay, toronto": "Etobicoke",
    "lakeview": "Etobicoke",
    "lakeshore": "Etobicoke",
    "lakeshore, toronto": "Etobicoke",
    "south etobicoke": "Etobicoke",
    "south etobicoke, toronto": "Etobicoke",
    "alderwood": "Etobicoke",
    "eringate": "Etobicoke",
    "eringate-marcel": "Etobicoke",
    "markland": "Etobicoke",
    "markland, toronto": "Etobicoke",
    "princess-royal": "Etobicoke",
    "princess gardens": "Etobicoke",
    "the west mall": "Etobicoke",
    "west mall": "Etobicoke",
    "islington": "Etobicoke",
    "islington, toronto": "Etobicoke",
    "islington city centre": "Etobicoke",
    "islington heights": "Etobicoke",
    "richview": "Etobicoke",
    "clawson": "Etobicoke",
    "edenwood": "Etobicoke",
    "elmhurst": "Etobicoke",
    "erindale": "Etobicoke",
    "etr": "Etobicoke",
    "catherine": "Scarborough",
    "norsmith": "Etobicoke",
    "sonoma heights": "Etobicoke",
    "the east mall": "Etobicoke",
    "the east": "Etobicoke",
    "centennial park": "Etobicoke",
    "century park": "Etobicoke",
    "east mall": "Etobicoke",
    "west Humber": "Etobicoke",
    "west humber": "Etobicoke",
    "humber valley village": "Etobicoke",
    "humber valley": "Etobicoke",
    "rexdale": "Etobicoke",
    "rexdale": "Etobicoke",
    "thistletown": "Etobicoke",
    "albion": "Etobicoke",
    "elmcrest": "Etobicoke",
    "richview": "Etobicoke",
    "woodbine heights": "East End",
    "mimico": "Etobicoke",
    "new toronto": "Etobicoke",
    "long branch": "Etobicoke",
    "southwest": "Etobicoke",

    # ── SCARBOROUGH ───────────────────────────────────────────────────────
    "scarborough": "Scarborough",
    "scarborough town centre": "Scarborough",
    "scarborough town centre, toronto": "Scarborough",
    "scarborough, toronto": "Scarborough",
    "scarborough, ontario": "Scarborough",
    "agincourt": "Scarborough",
    "agincourt, toronto": "Scarborough",
    "agincourt south": "Scarborough",
    "l'amoreaux": "Scarborough",
    "l'amoreaux, toronto": "Scarborough",
    "l'amoreaux west": "North York",
    "milliken": "Scarborough",
    "milliken, toronto": "Scarborough",
    "milliken hills": "Scarborough",
    "steeles": "Scarborough",
    "steeles ave": "Scarborough",
    "steeles avenue l": "Scarborough",
    "woburn": "Scarborough",
    "woburn, toronto": "Scarborough",
    "cedar": "Scarborough",
    "cedar grove": "Scarborough",
    "bendalc": "Scarborough",
    "bendale": "Scarborough",
    "golden mile": "Scarborough",
    "golden mile, toronto": "Scarborough",
    "wexford": "Scarborough",
    "wexford heights": "Scarborough",
    "highland creek": "Scarborough",
    "rougemount": "Scarborough",
    "rougemichael": "Scarborough",
    "rougemount, toronto": "Scarborough",
    "morningside": "Scarborough",
    "morningside heights": "Scarborough",
    "maltby": "Scarborough",
    "amberdale": "Scarborough",
    "highland creek, toronto": "Scarborough",
    "centennial": "Scarborough",
    "west hill": "Scarborough",
    "west hill, toronto": "Scarborough",
    "west hill, scarborough": "Scarborough",
    "mccowan": "Scarborough",
    "midland": "Scarborough",
    "kennedy": "Scarborough",
    "kennedy, toronto": "Scarborough",
    "cessfork": "Scarborough",
    "dorset park": "Scarborough",
    "ion": "Scarborough",
    "tam": "Scarborough",
    "mary": "Scarborough",
    "fender": "Scarborough",
    "glen": "Scarborough",
    "not": "Scarborough",
    "jay": "Scarborough",
    "kennedy road": "Scarborough",
    "lawrence east": "Scarborough",
    "markham": "Scarborough",
    "markham and lawrence": "Scarborough",
    "eglinton east": "Scarborough",
    "eglinton and victoria park": "Scarborough",
    "victoria park": "Scarborough",
    "birchmount": "Scarborough",
    "birchmount park": "Scarborough",
    "oakridge": "Scarborough",
    "oakridge, toronto": "Scarborough",
    " pharmacy": "Scarborough",
    "pharmacy": "Scarborough",
    "warden": "Scarborough",
    "warden and sheppard": "Scarborough",
    "sheppard / warden": "North York",
    "sheppard and warden": "North York",
    "mccowan and finch": "Scarborough",
    "morningside and finch": "Scarborough",
    "morningside and ella": "Scarborough",
    "morningside and northwood": "Scarborough",
    "catherine": "Scarborough",
    "f": "Scarborough",
    "westown": "Scarborough",
    "cedarcrest": "Scarborough",
    "cedarbrae": "Scarborough",
    "mangrove": "Scarborough",
    "tapscott": "Scarborough",
    "dianne": "Scarborough",
    "morningside village": "Scarborough",
}


def neighbourhood_to_region(n: str) -> str:
    """
    Map a neighbourhood string to one of 6 Toronto regions.
    Returns '' for non-Toronto municipalities (excluded from scoring).
    Returns 'Downtown' as default for unmapped Toronto neighbourhoods.
    """
    key = _key(n)

    # Explicit non-Toronto check
    if key in _NON_TORONTO:
        return ""

    # Exact match
    if key in _NEIGHBOURHOOD_REGION:
        return _NEIGHBOURHOOD_REGION[key]

    # Handle compound strings: "Neighbourhood1 / Neighbourhood2"
    if " / " in key:
        parts = [p.strip() for p in key.split(" / ")]
        # Pick the most recognizable/specific one
        for p in parts:
            if p in _NEIGHBOURHOOD_REGION:
                return _NEIGHBOURHOOD_REGION[p]
        # If mixed areas, prefer the one that's not generic
        for p in parts:
            if p not in ("downtown", "toronto", "city of toronto", "east end", "west end", "north york", "etobicoke", "scarborough"):
                if p in _NEIGHBOURHOOD_REGION:
                    return _NEIGHBOURHOOD_REGION[p]

    if " and " in key:
        parts = [p.strip() for p in key.split(" and ")]
        for p in parts:
            if p in _NEIGHBOURHOOD_REGION:
                return _NEIGHBOURHOOD_REGION[p]

    if " & " in key:
        parts = [p.strip() for p in key.split(" & ")]
        for p in parts:
            if p in _NEIGHBOURHOOD_REGION:
                return _NEIGHBOURHOOD_REGION[p]

    # Substring matching for edge cases like "Downtown Toronto near ..."
    for compound, region in _NEIGHBOURHOOD_REGION.items():
        if compound in key or key in compound:
            return region

    # Catch-all: unknown Toronto neighbourhoods default to Downtown
    # (most unmapped areas are in the downtown core)
    return "Downtown"


def region_summary() -> dict:
    """Return counts per region for current deals_output.csv."""
    import csv, os
    deals = os.path.join(os.path.dirname(__file__), "deals_output.csv")
    regions = {"Downtown": 0, "East End": 0, "West End": 0, "North York": 0, "Etobicoke": 0, "Scarborough": 0}
    if not os.path.exists(deals):
        return regions
    with open(deals, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r = neighbourhood_to_region(row.get("neighborhood", ""))
            if r:   # skip non-Toronto
                regions[r] = regions.get(r, 0) + 1
    return regions


if __name__ == "__main__":
    print("Region coverage from deals_output.csv:")
    for region, count in region_summary().items():
        print(f"  {region}: {count}")
