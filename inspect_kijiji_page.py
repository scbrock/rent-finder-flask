import re, json, os

# Read the saved kijiji page
page_path = os.path.join(os.path.dirname(__file__), "kijiji_page.html")
with open(page_path, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

print(f"Page length: {len(content)}")

next_match = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', content, re.DOTALL)
if next_match:
    data = json.loads(next_match.group(1))
    apollo = data.get('props',{}).get('pageProps',{}).get('__APOLLO_STATE__',{})
    count = 0
    for key, val in apollo.items():
        if isinstance(val, dict) and val.get('__typename') in ('RealEstateListing', 'StandardListing'):
            count += 1
    print(f'Apollo entries (RealEstate/Standard): {count}')
    # Print first 5
    i = 0
    for key, val in apollo.items():
        if isinstance(val, dict) and val.get('__typename') in ('RealEstateListing', 'StandardListing') and i < 5:
            print(f'  [{i+1}] title={val.get("title","")[:60]} price={val.get("price","")} id={val.get("id","")} typename={val.get("__typename","")}')
            i += 1
else:
    print('No __NEXT_DATA__ found')
    print('First 300 chars:', content[:300])