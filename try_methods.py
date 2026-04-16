import httpx, json, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json; charset=utf-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.viewit.ca/Listings",
}

client = httpx.Client(timeout=30, follow_redirects=True)

# Get VS first
r = client.get("https://www.viewit.ca/Listings?sort=price&dir=asc", headers={"User-Agent": HEADERS["User-Agent"], "Accept-Language": "en-CA"})
vs = re.search(r'id="__VIEWSTATE" value="([^"]+)"', r.text)
ev = re.search(r'id="__EVENTVALIDATION" value="([^"]+)"', r.text)
print(f"VS: {len(vs.group(1)) if vs else 0} chars, EV: {len(ev.group(1)) if ev else 0} chars")

base = "https://www.viewit.ca/vwdefault.aspx"
for method in ["GetListingsSmartSearch", "GetPlacePredictions", "GetZoneGeocodes"]:
    for payload in [
        json.dumps({"sSearch": "Toronto"}),
        json.dumps(""),
        '{"sSearch":"Toronto"}',
    ]:
        try:
            r2 = client.post(f"{base}/{method}", content=payload.encode(), headers=HEADERS, timeout=15)
            print(f"{method} | {payload[:30]}... => HTTP {r2.status_code}, ct={r2.headers.get('content-type','?')[:40]}")
            print(f"  {r2.text[:200]}")
        except Exception as e:
            print(f"{method} | error: {e}")
        break