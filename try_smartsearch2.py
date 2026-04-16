import httpx, json, re

client = httpx.Client(timeout=30)
ajax_headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Content-Type": "application/json; charset=utf-8",
    "X-Requested-With": "XMLHttpRequest",
}

for query in ["M5V Toronto", "Downtown Toronto apartment", "1 bedroom Toronto"]:
    r = client.post(
        "https://www.viewit.ca/vwdefault.aspx/GetListingsSmartSearch",
        content=json.dumps({"sSearch": query}),
        headers=ajax_headers,
    )
    d = r.json()
    xml = d.get("d", "")
    has_price = "<Price>" in xml
    has_listing = "<ListingID>" in xml or "<Listing" in xml
    has_addr = "<Address>" in xml
    print(f"Query: {query}")
    print(f"  XML len: {len(xml)}, Price={has_price}, Listing={has_listing}, Address={has_addr}")
    print(f"  First 400: {xml[:400]}")
    print()