import requests, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
}

# The for-rent category URL
url = 'https://www.kijiji.ca/b-for-rent/city-of-toronto/c30349001l1700273'
r = requests.get(url, headers=HEADERS, timeout=20)

m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
if m:
    data = json.loads(m.group(1))
    apollo = data.get('props',{}).get('pageProps',{}).get('__APOLLO_STATE__',{})
    real = [(k,v) for k,v in apollo.items() if isinstance(v,dict) and v.get('__typename')=='RealEstateListing']

    print(f'RealEstateListing count: {len(real)}')

    # Check for keywords that indicate RENT vs SALE
    for k,v in real:
        title = v.get('title','')
        desc = str(v.get('description',''))
        price_val = 0
        price = v.get('price',{})
        if isinstance(price,dict):
            price_val = price.get('amount',0) or 0
        else:
            try: price_val = int(price)
            except: pass

        is_rental = any(w in desc.lower() for w in ['monthly', '/month', 'per month', 'rent', 'lease', 'tenant'])
        print(f'  price={price_val} rental={is_rental} title={title[:50]}')
        if price_val < 50000:
            print(f'    DESC: {desc[:150]}')

    print('\n--- Looking for StandardListing rentals ---')
    std = [(k,v) for k,v in apollo.items() if isinstance(v,dict) and v.get('__typename')=='StandardListing']
    print(f'StandardListing count: {len(std)}')
    for k,v in std[:10]:
        price = v.get('price',{})
        if isinstance(price,dict): price = price.get('amount','')
        desc = str(v.get('description',''))[:100]
        print(f'  price={price} title={v.get("title","")[:50]}')
        print(f'    desc={desc}')