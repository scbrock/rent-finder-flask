"""MC-246: Call viewit.ca GetListingsSmartSearch ASP.NET AJAX endpoint with proper ViewState."""

import httpx, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json; charset=utf-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.viewit.ca/Listings",
}

BASE = "https://www.viewit.ca/vwdefault.aspx"

def get_viewstate(client: httpx.Client) -> tuple[str, str, str]:
    resp = client.get(f"{BASE}/Listings?sort=price&dir=asc", timeout=30)
    vs = re.search(r'id="__VIEWSTATE" value="([^"]+)"', resp.text)
    ev = re.search(r'id="__EVENTVALIDATION" value="([^"]+)"', resp.text)
    vsg = re.search(r'id="__VIEWSTATEGENERATOR" value="([^"]+)"', resp.text)
    return (
        vs.group(1) if vs else "",
        ev.group(1) if ev else "",
        vsg.group(1) if vsg else "",
    )

def parse_xml_listings(xml_str: str) -> list[dict]:
    """Parse GetListingsSmartSearch XML response into list of listing dicts."""
    listings = []

    # Extract City block
    city_ids = re.findall(r'<CityID>(\d+)</CityID>\s*<ProvinceCode>(\w+)</ProvinceCode>\s*<CityName>([^<]+)</CityName>', xml_str)
    print(f"Cities found: {city_ids}")

    # Extract listings - different possible XML structures
    # Look for Price, Address, # bed patterns
    price_blocks = re.findall(
        r'<Price>([^<]+)</Price>\s*<Address>([^<]+)</Address>\s*<Bedrooms>([^<]+)</Bedrooms>',
        xml_str
    )
    print(f"Price+Address+Beds blocks: {len(price_blocks)}")
    for pb in price_blocks[:10]:
        print(f"  ${pb[0]} - {pb[1]} - {pb[2]} beds")

    # Try generic column extraction
    rows = re.findall(r'<Table[^>]*>(.*?)</Table>', xml_str, re.DOTALL)
    for row in rows:
        cols = re.findall(r'<(\w+)>([^<]*)</\1>', row)
        col_dict = {k: v.strip() for k, v in cols}
        if col_dict:
            listings.append(col_dict)

    return listings

def call_smart_search(client: httpx.Client, vs: str, ev: str) -> str:
    """Call GetListingsSmartSearch with ASP.NET AJAX."""
    # The method expects JSON body with sSearch field
    # But based on the PageMethod signature: function(sSearch, onSuccess, onFailed, userContext)
    # We need to use the standard ASP.NET AJAX JSON endpoint

    payload = json.dumps({"sSearch": "Toronto"})  # Simple search first

    try:
        resp = client.post(
            f"{BASE}/GetListingsSmartSearch",
            content=payload,
            timeout=30,
        )
        print(f"POST GetListingsSmartSearch: HTTP {resp.status_code}, ct={resp.headers.get('content-type')}")
        print(f"Response ({len(resp.text)} chars): {resp.text[:500]}")
        return resp.text
    except Exception as e:
        print(f"POST error: {e}")
        return ""

def call_page_method(client: httpx.Client, vs: str, ev: str) -> str:
    """
    Call via standard ASP.NET PageMethods SOAP-like or direct call.
    The endpoint URL is /vwdefault.aspx/MethodName
    """
    # Try the JSON endpoint for each method
    for method in ["GetListingsSmartSearch", "GetZoneGeocodes", "GetPlacePredictions"]:
        payload = json.dumps({"": ""})  # Empty param for testing
        try:
            resp = client.post(
                f"{BASE}/{method}",
                content=payload,
                headers={"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"},
                timeout=20,
            )
            print(f"POST /{method}: HTTP {resp.status_code}")
            print(f"  Response: {resp.text[:300]}")
        except Exception as e:
            print(f"POST /{method}: {e}")

    return ""

if __name__ == "__main__":
    with httpx.Client(headers={k: v for k, v in {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
        "Accept-Language": "en-CA,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }.items()}, timeout=30, follow_redirects=True) as client:
        print("Getting ViewState...")
        vs, ev, vsg = get_viewstate(client)
        print(f"VS len={len(vs)}, EV len={len(ev)}, VSG={vsg[:20]}...")

        print("\nCalling SmartSearch...")
        xml_resp = call_smart_search(client, vs, ev)

        print("\nParsing listings...")
        if xml_resp:
            parse_xml_listings(xml_resp)