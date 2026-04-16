import httpx, re

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537", "Accept-Language": "en-CA,en;q=0.9"}
c = httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)

# Get homepage to get cookies
c.get("https://www.kijiji.ca/")

# Try different URL patterns
urls_to_try = [
    "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/l1700273",
    "https://www.kijiji.ca/b-apartments-condos/ontario/l1700273",
    "https://www.kijiji.ca/b-apartments-condos/canada/l1700273",
]

# Check the page for any rental category link
r = c.get(urls_to_try[0])
# Find rental links
rent_links = re.findall(r'href="(/b-rentals[^"]+)"', r.text)
print(f"Rentals links: {rent_links[:5]}")
# Find apartment links
apt_links = re.findall(r'href="(/b-apartments-condos[^"]+)"', r.text)
print(f"Apartment links: {apt_links[:5]}")

# Check the actual category structure
# Look for any JavaScript state that tells us the correct URL
js_state = re.findall(r'"categoryUrl"\s*:\s*"([^"]+)"', r.text)
print(f"Category URLs: {js_state[:5]}")

# Check for any Next.js route data
next_routes = re.findall(r'"route"\s*:\s*"([^"]+)"', r.text)
print(f"Next routes: {next_routes[:10]}")

# Look for the actual search results URL in the JavaScript
search_urls = re.findall(r'["\'](/search[^"\']*toronto[^"\']*)["\']', r.text[:20000])
print(f"Search URLs: {search_urls[:10]}")

# Check if there's an API endpoint in the HTML
api_urls = re.findall(r'apiUrl["\s:]+([^,\n]+)', r.text[:10000])
print(f"apiUrl: {api_urls[:5]}")