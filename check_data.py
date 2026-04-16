import json

with open('rent_finder/output/raw_2026-04-16.json') as f:
    data = json.load(f)

print(f"Total listings: {len(data)}")

# Show first 5 with price and description
for item in data[:5]:
    print(f"  price={item['price']} beds={item['beds']} neighborhood={item['neighborhood']}")
    print(f"  title={item['title'][:60]}")
    desc = str(item.get('description',''))
    print(f"  desc={desc[:120]}")
    print()

# Check the price distribution
prices = [item['price'] for item in data]
print(f"Price stats: min={min(prices)}, max={max(prices)}, median={sorted(prices)[len(prices)//2]}")

# Count listings with price < 200000 (these might be monthly rents vs sale prices)
under_200k = [item for item in data if item['price'] < 200000]
print(f"Listings with price < 200k: {len(under_200k)}")
for item in under_200k[:5]:
    print(f"  {item['price']} | {item['title'][:60]}")
    print(f"  desc={str(item.get('description',''))[:100]}")