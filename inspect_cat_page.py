import re, json, os

# Check kijiji_category.html for the category ID vs the URL it was fetched from
with open('rent_finder/kijiji_category.html', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

print(f"Page length: {len(content)}")

# Look for any URLs in the HTML
urls = re.findall(r'https://www\.kijiji\.ca[^\s"\'<>]+', content[:5000])
print('Sample URLs:', urls[:5])

# Check the __NEXT_DATA__ for any listing count or page info
m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', content, re.DOTALL)
if m:
    data = json.loads(m.group(1))
    pp = data.get('props',{}).get('pageProps',{})
    print('pageProps keys:', list(pp.keys())[:15])
    search = pp.get('search',{})
    if search:
        print('search keys:', list(search.keys())[:10])
    else:
        print('No search key in pageProps')
        # Look for anything that might have listing count
        for k,v in list(pp.items())[:5]:
            print(f'  {k}: {str(v)[:100]}')