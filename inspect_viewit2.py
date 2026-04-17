import requests, re
r = requests.get('https://www.viewit.ca/searchresults.aspx?search=apartment&location=Toronto&pricefrom=0&priceto=3500', headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}, timeout=15)
# Find class names
classes = re.findall(r'class="([^"]+)"', r.text)
unique_classes = sorted(set(classes))
print('Unique classes:', unique_classes[:30])
# Show forms
forms = re.findall(r'<form[^>]*id="([^"]+)"', r.text)
print('Forms:', forms[:5])
# Show links to listings
links = re.findall(r'href="([^"]*listing[^"]*)"', r.text, re.IGNORECASE)
print('Listing links:', links[:5])
# Sample of text
print('Text sample at 5000:', r.text[5000:5600])