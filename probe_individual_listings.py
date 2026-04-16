import requests, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537",
    "Accept-Language": "en-CA,en;q=0.9",
}

listing_ids = ["26056", "26601", "244796", "22134", "205885", "244963", "244964", "26049", "64525"]

for lid in listing_ids:
    r = requests.get(f"https://www.viewit.ca/{lid}", headers=HEADERS, timeout=15)
    prices = re.findall(r'\$[\d,]+', r.text)
    print(f"Listing {lid}: HTTP {r.status_code}, size={len(r.text)}, prices: {prices[:10]}")
    if r.status_code == 200:
        # Extract key fields
        address = re.search(r'"streetAddress"\s*:\s*"([^"]+)"', r.text)
        price = re.search(r'"price"\s*:\s*"([^"]+)"', r.text)
        beds = re.search(r'"numberOfBedrooms"\s*:\s*"([^"]+)"', r.text)
        baths = re.search(r'"numberOfBathrooms"\s*:\s*"([^"]+)"', r.text)
        print(f"  address={address.group(1) if address else 'N/A'}, price={price.group(1) if price else 'N/A'}, beds={beds.group(1) if beds else 'N/A'}, baths={baths.group(1) if baths else 'N/A'}")