import requests, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
}

# Fetch the proper rental listings URL
url = 'https://www.kijiji.ca/b-apartments-condos/city-of-toronto/apartment-for-rent/k0c37l1700273'
r = requests.get(url, headers=HEADERS, timeout=20)
print(f'Status: {r.status_code}, size={len(r.text)}')

m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
if m:
    data = json.loads(m.group(1))
    apollo = data.get('props',{}).get('pageProps',{}).get('__APOLLO_STATE__',{})
    real = [(k,v) for k,v in apollo.items() if isinstance(v,dict) and v.get('__typename')=='RealEstateListing']
    print(f'RealEstateListing: {len(real)}')

    for k,v in real[:10]:
        price = v.get('price',{})
        if isinstance(price,dict): price = price.get('amount','')
        title = v.get('title','')
        desc = str(v.get('description',''))[:200]
        # Find bedrooms
        beds = ''
        for key in v:
            if 'bed' in key.lower() and isinstance(v[key],int):
                beds = str(v[key])
                break
        print(f'  price={price} beds={beds} title={title[:60]}')
        print(f'    DESC: {desc}')
        print()

    # Also check for any attribute containing "price" in different structures
    # Check first listing in detail
    first = real[0][1] if real else {}
    print('First listing keys:', list(first.keys()))
else:
    print('No __NEXT_DATA__')