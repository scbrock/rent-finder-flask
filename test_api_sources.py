import requests, json

urls = [
    "https://api.padmapper.com/v1/listings?city=Toronto&maxPrice=5000",
    "https://www.padmapper.com/apartments-for-rent/toronto-ontario",
    "https://www.rentals.ca/toronto/rentals",
    "https://www.torontorentals.com/rentals",
    "https://www.liv.rent/toronto",
    "https://www.realtor.ca/map#?searchText=Toronto%2C%20ON&rent=1&priceMax=4000",
]

for url in urls:
    try:
        r = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/html, */*",
        })
        ct = r.headers.get("content-type", "")
        print(f"Status: {r.status_code} | CT: {ct[:40]} | {url[:70]}")
        if r.status_code == 200:
            preview = r.text[:300]
            print(f"  Preview: {preview}")
        print()
    except Exception as e:
        print(f"Error for {url[:60]}: {e}")
        print()