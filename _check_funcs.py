with open('find_deals.py', 'r', encoding='utf-8') as f:
    content = f.read()
for kw in ['concat_and_dedup', 'score_deals_with_districts', '_classify_district']:
    print(kw, ':', kw in content)