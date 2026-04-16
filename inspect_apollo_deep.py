import re, json, os

# Inspect the Apollo state more carefully
with open('rent_finder/kijiji_category.html', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', content, re.DOTALL)
if m:
    data = json.loads(m.group(1))
    apollo = data.get('props',{}).get('pageProps',{}).get('__APOLLO_STATE__',{})

    # Find all RealEstateListing entries
    real = {k: v for k, v in apollo.items() if isinstance(v, dict) and v.get('__typename') == 'RealEstateListing'}
    std = {k: v for k, v in apollo.items() if isinstance(v, dict) and v.get('__typename') == 'StandardListing'}

    print(f'Total Apollo entries: {len(apollo)}')
    print(f'RealEstateListing: {len(real)}')
    print(f'StandardListing: {len(std)}')

    # Print all RealEstate listings
    print('\n--- RealEstateListing entries ---')
    for k, v in real.items():
        price = v.get('price', {})
        if isinstance(price, dict):
            price = price.get('amount', '')
        desc = str(v.get('description', ''))[:80]
        print(f'  id={v.get("id")} title={v.get("title","")[:60]} price={price}')
        print(f'    desc={desc}')

    # Now look for any key that might have the search results
    # Check if there's any AdsResult or ListingSearch result
    for k, v in apollo.items():
        if 'listing' in k.lower() or 'search' in k.lower() or 'ads' in k.lower():
            if isinstance(v, dict):
                print(f'  [Potentially relevant] {k}: typename={v.get("__typename")} keys={list(v.keys())[:5]}')

    # Also check for URL patterns
    url_entries = [(k,v) for k,v in apollo.items() if isinstance(v,dict) and v.get('__typename') == 'UrlEntry']
    print(f'\nUrlEntry entries: {len(url_entries)}')
    for k,v in url_entries[:5]:
        print(f'  {v.get("relativeUrl","")} -> {v.get("absoluteUrl","")}')