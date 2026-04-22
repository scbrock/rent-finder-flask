import httpx, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537',
    'Accept-Language': 'en-CA,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)

url = 'https://www.viewit.ca/Listings?sort=price&dir=asc&page=1'
resp = client.get(url)
html = resp.text

# Look for ALL ASP.NET hidden fields
viewstate = re.findall(r'__VIEWSTATE[^"]*"[^>]*value="([^"]*)"', html)
eventvalidation = re.findall(r'__EVENTVALIDATION[^"]*"[^>]*value="([^"]*)"', html)
viewstategenerator = re.findall(r'__VIEWSTATEGENERATOR[^"]*"[^>]*value="([^"]*)"', html)
print('ViewState count:', len(viewstate))
print('EventValidation count:', len(eventvalidation))
print('ViewStateGenerator count:', len(viewstategenerator))

# Look for any form action URL
form_action = re.findall(r'<form[^>]+action="([^"]+)"', html)
print('Form action:', form_action)

# Look for any select/option elements with city/neighbourhood
options = re.findall(r'<option[^>]*value="([^"]+)"[^>]*>([^<]+)</option>', html)
print('Total options:', len(options))
for val, text in options[:30]:
    tl = text.lower()
    if any(w in tl for w in ['toronto', 'downtown', 'north york', 'scarborough', 'etobicoke', 'york', 'mississauga']):
        print(f'  Toronto-related: {val} = {text}')

# Check for any scripts with listing data
script_srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
print('Script srcs:', script_srcs[:10])

# Look for any WebMethod or pageMethods in scripts
page_methods = re.findall(r'PageMethods\.(\w+)', html)
print('PageMethods:', page_methods[:10])

# Look for inline scripts with data
inline_scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
print('Inline scripts:', len(inline_scripts))
for i, s in enumerate(inline_scripts):
    if len(s) > 100 and ('price' in s.lower() or 'listing' in s.lower() or 'address' in s.lower()):
        print(f'  Script {i} (len={len(s)}): {s[:300]}')
        break