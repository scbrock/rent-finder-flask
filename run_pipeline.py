import os, sys, warnings
warnings.filterwarnings('ignore')
os.chdir(r'C:\Users\steph\.openclaw\workspace-coding\rent_finder')
import find_deals

print('=== Running full pipeline ===')

# 1. Scrape
df_zumper = find_deals.scrape_zumper(pages=2)
df_kijiji = find_deals.scrape_kijiji(pages=3)
df_craigslist = find_deals.scrape_craigslist(pages=2)

df = find_deals.concat_and_dedup([df_zumper, df_kijiji, df_craigslist])
print(f'Total raw after dedup: {len(df)}')

# 2. Score
scored = find_deals.score_deals(df)
print(f'After scoring: {len(scored)}')

# 3. Output
if not scored.empty:
    best = scored.iloc[0]
    print(f'BEST: {best["neighborhood"]} {best["beds"]}BR ${best["price"]} | score={best["final_score"]:.3f} pct={best["pct_under"]:.1f}%')
    underpriced = scored[scored['pct_under'] > 0]
    print(f'Under market: {len(underpriced)}/{len(scored)}')
    
    # Save CSV
    scored.to_csv('deals_output.csv', index=False)
    print(f'Saved to deals_output.csv')
else:
    print('No deals found')