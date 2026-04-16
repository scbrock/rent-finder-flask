import requests
import sys

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.8",
}

# Try multiple rental listing RSS/API sources
sources = [
    ("Kijiji Toronto Condos RSS", "https://www.kijiji.ca/rss-srp-apartments-condos/toronto-on/c37l1700287"),
    ("Kijiji Downtown RSS", "https://www.kijiji.ca/rss-srp-apartments-condos/downtown-toronto/c37l1700287"),
    ("Craigslist Toronto", "https://toronto.craigslist.org/search/apa"),
    ("Viewit API", "https://api.viewit.ca/available.php?city=Toronto&region=Downtown"),
]

for name, url in sources:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        ct = r.headers.get("Content-Type", "")
        print(f"{name}: HTTP {r.status_code}, Content-Type: {ct[:60]}, Length: {len(r.text)}")
        if r.status_code == 200:
            print(r.text[:800])
        print()
    except Exception as e:
        print(f"{name}: ERROR {e}")
        print()
