"""Test various rental APIs."""
import requests, json

tests = [
    ("liv.rent API", "https://api.liv.rent/public/v1/listings?city_id=1&limit=5"),
    ("rent.ca API", "https://www.rentals.ca/api/listings?city=Toronto&limit=5"),
    ("rent.ca JSON", "https://www.rentals.ca/toronto/rentals?format=json"),
    ("Kijiji REST", "https://www.kijiji.ca/api/v1/listings?location=toronto&category=34"),
]

for name, url in tests:
    try:
        r = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        })
        print(f"{name}: {r.status_code} | {r.headers.get('content-type','')[:50]}")
        if r.status_code == 200:
            try:
                data = r.json()
                print(f"  JSON keys: {list(data.keys())[:8]}")
            except:
                print(f"  Non-JSON response: {r.text[:200]}")
        else:
            print(f"  Body: {r.text[:150]}")
        print()
    except Exception as e:
        print(f"{name}: ERROR - {e}\n")