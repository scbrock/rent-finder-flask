with open('find_deals.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    if 'def scrape_kijiji' in line or 'def scrape_craigslist' in line:
        print(f"{i}: {line.rstrip()}")