from scrape_viewit import get_listings_page, extract_listings_from_html, fetch_individual_listing

html = get_listings_page(1)
print(f"HTML len: {len(html)}")
listings = extract_listings_from_html(html)
print(f"Listings from page 1: {len(listings)}")
for l in listings:
    print(f"  [{l['listing_id']}] src={l['source']}")

# Try fetching first listing
if listings:
    first = listings[0]['listing_id']
    data = fetch_individual_listing(first)
    print(f"\nFirst listing {first} full data: {data}")