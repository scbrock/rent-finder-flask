import requests, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
}

# Check the proper URL for rental listings
url = 'https://www.kijiji.ca/b-apartments-condos/city-of-toronto/apartment-for-rent/k0c37l1700273'
r = requests.get(url, headers=HEADERS, timeout=20)
print(f'URL: {url}')
print(f'  Status: {r.status_code}, size={len(r.text)}')

m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
if m:
    data = json.loads(m.group(1))
    apollo = data.get('props',{}).get('pageProps',{}).get('__APOLLO_STATE__',{})
    real = [(k,v) for k,v in apollo.items() if isinstance(v,dict) and v.get('__typename')=='RealEstateListing']
    print(f'  RealEstateListing: {len(real)}')
    for k,v in real[:5]:
        p = v.get('price',{}); p = p.get('amount','') if isinstance(p,dict) else p
        print(f'    {v.get("title","")[:60]} | price={p}')
else:
    print('  No __NEXT_DATA__ found')