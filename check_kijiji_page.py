import re, json, os

with open('rent_finder/kijiji_page.html', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

print(f"Page length: {len(content)}")

m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', content, re.DOTALL)
if m:
    data = json.loads(m.group(1))
    apollo = data.get('props',{}).get('pageProps',{}).get('__APOLLO_STATE__',{})
    real = [(k,v) for k,v in apollo.items() if isinstance(v,dict) and v.get('__typename')=='RealEstateListing']
    print(f'RealEstateListing count: {len(real)}')
    for k,v in real[:5]:
        price = v.get('price',{})
        if isinstance(price,dict): price = price.get('amount','')
        print(f'  id={v.get("id")} title={v.get("title","")[:60]} price={price}')
        print(f'  description={str(v.get("description",""))[:100]}')
else:
    print('No __NEXT_DATA__ found')