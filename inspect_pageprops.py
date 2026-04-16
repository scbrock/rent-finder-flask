"""Inspect the Next.js SSR data and the actual data loaded by the client."""

import httpx, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
    c.get("https://www.kijiji.ca/")
    r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")

next_match = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
data = json.loads(next_match.group(1))

# Print the full pageProps
page_props = data["props"]["pageProps"]
print("pageProps keys:", list(page_props.keys()))

# Look at everything in pageProps
for k, v in page_props.items():
    v_str = str(v)
    print(f"\n{k} ({len(v_str)} chars): {v_str[:500]}")