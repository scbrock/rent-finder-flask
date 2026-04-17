import requests, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'en-CA,en;q=0.9',
    'Referer': 'https://www.viewit.ca/',
}

r = requests.get('https://www.viewit.ca/FeaturedListings.aspx', headers=HEADERS, timeout=15)

# Check for ASP.NET hidden fields
viewstate = re.findall(r'__VIEWSTATE[^ value=]*value="([^"]+)"', r.text)
eventvalidation = re.findall(r'__EVENTVALIDATION[^ value=]*value="([^"]+)"', r.text)
print(f'ViewState found: {len(viewstate) > 0}')
print(f'EventValidation found: {len(eventvalidation) > 0}')

# Check for ScriptManager (ASP.NET AJAX)
scripts = re.findall(r'ScriptService[^"]*"([^"]+)"', r.text)
print(f'ScriptServices: {scripts[:5]}')

# Check for WebMethod attributes
webmethods = re.findall(r'\[WebMethod\][^<]{0,200}', r.text)
print(f'WebMethods: {webmethods[:3]}')

# Look for any URLs in script tags
script_urls = re.findall(r'(https?://[^\s"\'`<>]+)', r.text)
print(f'URLs in page: {[u for u in script_urls if len(u) > 20][:10]}')

# Look for any data in JSON-LD
json_ld = re.findall(r'<script type="application/ld\+json">(.*?)</script>', r.text, re.DOTALL)
if json_ld:
    for j in json_ld:
        try:
            data = json.loads(j)
            print(f'JSON-LD type: {data.get("@type")}')
            if 'itemListElement' in data:
                print(f'  List items: {len(data["itemListElement"])}')
        except:
            print(f'JSON-LD raw: {j[:200]}')

# Check if there's a paged result mechanism
print(f'\nPage content check - all script tags:')
scripts_all = re.findall(r'<script[^>]*>(.*?)</script>', r.text, re.DOTALL)
for i, s in enumerate(scripts_all):
    if len(s) > 100 and 'http' in s.lower():
        print(f'  Script {i} (len={len(s)}): {s[:200]}')