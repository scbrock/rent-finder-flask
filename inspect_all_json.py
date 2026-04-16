"""Inspect Kijiji search API by looking at all script tag data."""

import httpx, re, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
    c.get("https://www.kijiji.ca/")
    r = c.get("https://www.kijiji.ca/b-rentals/city-of-toronto/l1700273")

# Check all JSON script tags
json_scripts = re.findall(
    r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', r.text, re.DOTALL
)
print(f"JSON script blocks: {len(json_scripts)}")
for i, js in enumerate(json_scripts):
    try:
        d = json.loads(js)
        keys = list(d.keys()) if isinstance(d, dict) else type(d).__name__
        print(f"\nBlock {i} ({len(js)} chars): keys={keys}")
        if isinstance(d, dict):
            # Check for any nested data
            for k, v in d.items():
                v_str = str(v)
                if len(v_str) > 5000:
                    v_str = v_str[:5000] + "..."
                print(f"  {k}: {v_str[:300]}")
    except json.JSONDecodeError:
        print(f"\nBlock {i}: not JSON, starts: {js[:100]}")

# Also look for any window.__ state objects
window_states = re.findall(
    r'window\.(\w+)\s*=\s*(\{.*?\})\s*;', r.text, re.DOTALL
)
print(f"\nWindow state objects: {len(window_states)}")
for name, content in window_states[:5]:
    print(f"  window.{name}: {content[:200]}")