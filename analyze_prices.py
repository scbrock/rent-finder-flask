import json

with open('rent_finder/output/raw_2026-04-16.json') as f:
    data = json.load(f)

item = data[0]
print("Full price field:", repr(item.get('price')))
print("Full item keys:", list(item.keys()))

# Check listings with price < 50000
low_price = [i for i in data if i['price'] < 50000]
print("Listings with price < 50000:", len(low_price))
for i in low_price[:5]:
    print(f"  price={i['price']} title={i['title'][:50]}")

prices = sorted(set(i['price'] for i in data))
print("Lowest prices:", prices[:15])
print("Highest prices:", prices[-10:])