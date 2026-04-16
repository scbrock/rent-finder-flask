import requests, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
}

# Fetch the rental listings URL
url = 'https://www.kijiji.ca/b-apartments-condos/city-of-toronto/apartment-for-rent/k0c37l1700273'
r = requests.get(url, headers=HEADERS, timeout=20)
print(f'Status: {r.status_code}')

m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
if m:
    data = json.loads(m.group(1))
    apollo = data.get('props',{}).get('pageProps',{}).get('__APOLLO_STATE__',{})
    real = [(k,v) for k,v in apollo.items() if isinstance(v,dict) and v.get('__typename')=='RealEstateListing']
    print(f'RealEstateListing: {len(real)}')

    # Inspect first listing attributes
    if real:
        first = real[0][1]
        print('\nAttributes field:')
        attrs = first.get('attributes', {})
        if isinstance(attrs, dict):
            for k, v in attrs.items():
                print(f'  {k}: {v}')
        else:
            print(f'  Raw: {str(attrs)[:200]}')

        print('\nAll keys:', list(first.keys()))
        print('URL:', first.get('url',''))
        print('location:', first.get('location',''))