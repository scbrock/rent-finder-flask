import re, json, os

# Check kijiji_category.html which should be rentals category
base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cat_path = os.path.join(base, "rent_finder", "kijiji_category.html")

with open(cat_path, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

print(f"kijiji_category.html length: {len(content)}")

next_match = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', content, re.DOTALL)
if next_match:
    data = json.loads(next_match.group(1))
    apollo = data.get('props',{}).get('pageProps',{}).get('__APOLLO_STATE__',{})
    real = sum(1 for k,v in apollo.items() if isinstance(v,dict) and v.get('__typename') == 'RealEstateListing')
    std = sum(1 for k,v in apollo.items() if isinstance(v,dict) and v.get('__typename') == 'StandardListing')
    print(f'RealEstateListing: {real}, StandardListing: {std}')

    # Show first 5 real ones
    count = 0
    for k,v in apollo.items():
        if isinstance(v,dict) and v.get('__typename') == 'RealEstateListing' and count < 5:
            price = v.get('price','')
            if isinstance(price, dict):
                price = price.get('amount','')
            print(f'  id={v.get("id")} title={v.get("title","")[:60]} price={price}')
            count += 1
else:
    print('No __NEXT_DATA__ found')
    # Check what HTML looks like
    print('First 200:', content[:200])