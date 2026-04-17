"""
Toronto region mapper.
Maps neighbourhood names to one of 6 Toronto regions:
  Downtown, East End, West End, North York, Etobicoke, Scarborough
"""

def neighbourhood_to_region(n: str) -> str:
    n = n.strip()
    if n in (
        "Toronto", "City of Toronto",
        "North St.James Town", "Regent Park", "Old Town",
        "Alexandra Park", "Little Italy", "Church Wellesley", "Fashion District",
        "Liberty Village", "Moss Park", "Corktown", "Distillery District",
        "Queen West", "Kensington Market", "University", "Harbourfront",
        "Garden District", "St. James Town", "Playter Estates", "Broadview North",
        "Woodbine Park", "Parkview", "South Riverdale", "Riverdale",
        "Tuxedo Park",
    ):
        return "Downtown"

    if n in (
        "The Beaches", "Woodbine Beach", "Kew Beach", "Balmy Beach",
        "Murray Hill", "South Marine", "Silverthorn", "Jones Valley",
        "Oakridge", "Greenwood", "Chinbury", "Danforth", "East York",
        "Woodbine Heights", "East Toronto", "Birchcliffe-Cliffside",
        "Cliffside", "Guildwood", "Woodbine Corridor", "Eglinton East",
        "Broadview North", "Brockton Village",
    ):
        return "East End"

    if n in (
        "High Park", "Roncesvalles", "Swansea", "The Junction",
        "Bloor West Village", "Runnymede", "Lambton", "Lakeshore",
        "Mimico", "New Toronto", "Long Branch", "The Queensway",
        "King Street West", "Parkdale", "South Parkdale",
        "Roncesvalles Village", "Grenadier", "High Park-Swansea",
        "The Junction Area", "Junction Area", "Bloordale Gardens",
        "Earlscourt", "Oakwood", "Silverthorn",
        "Edenbridge-Humber Valley", "Pelmo Park-Humberlea",
        "Humber Summit", "Rockcliffe-Smythe", "West Shore",
        "Dovercourt Village", "Dufferin Grove", "Little Portugal", "Niagara",
    ):
        return "West End"

    if n in (
        "North York", "Willowdale", "Newtonbrook", "Bayview Village",
        "York Mills", "Don Mills", "Fairview", "Hillcrest Village",
        "Henry Farm", "Stong", "Yorkview", "Sunset",
        "Baycrest", "Flemingdon Park", "Dean Park",
        "North Toronto", "Midtown", "Davisville", "Leaside-Bennington",
        "Leaside", "Golfdale Gardens", "Englemount-Lawrence",
        "York University Heights", "Clanton Park", "Cedar Wood",
        "L'Amoreaux West",  # technically Scarborough but close to North York boundary
    ):
        return "North York"

    if n in (
        "Etobicoke", "The Kingsway", "Humber Bay", "Lakeview",
        "South Etobicoke", "Alderwood", "Eringate", "Markland",
        "Princess-Royal", "Etobicoke City Centre", "The West Mall",
        "Kingsway", "Cloverdale", "Islington", "Princess Gardens",
        "West Humber", "Richview", "Islington City Centre",
        "Sonoma Heights",
    ):
        return "Etobicoke"

    if n in (
        "Scarborough", "Agincourt", "L'Amoreaux", "Milliken",
        "Steeles", "Woburn", "Cedar", "Dorset Park", "Bendale",
        "Golden Mile", "Wexford", "Highland Creek", "Rouge",
        "Morningside", "Maltby", "Ion", "Falmouth", "Jay",
        "Kennedy", "McCowan", "Midland", "Not", "Tam", "Mary",
        "Fender", "Glen", "Bermond",
    ):
        return "Scarborough"

    # Catch-all: default to Downtown
    return "Downtown"


def region_summary() -> dict:
    """Return counts per region for current deals."""
    import csv, os
    deals = os.path.join(os.path.dirname(__file__), "deals_output.csv")
    regions = {"Downtown": 0, "East End": 0, "West End": 0, "North York": 0, "Etobicoke": 0, "Scarborough": 0}
    with open(deals, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r = neighbourhood_to_region(row.get("neighborhood", ""))
            regions[r] = regions.get(r, 0) + 1
    return regions


if __name__ == "__main__":
    print("Region coverage:")
    for region, count in region_summary().items():
        print(f"  {region}: {count}")