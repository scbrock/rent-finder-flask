"""
Toronto Rental Deal Finder — Neighborhood Segmentation Fix

Problem: Raw neighbourhood names (e.g. "Church-Yonge Corridor", "Entertainment-Financial District")
are too granular. When <3 listings share a (neighborhood, beds) group, no fair value is computed,
and those listings score 0 or negative.

Fix: Map raw neighbourhood names to broader Toronto districts BEFORE fair value calculation.
Larger groups = more listings get fair values = more deal detections.

MC-285
"""

import os, sys, json, re, warnings
warnings.filterwarnings('ignore')
os.chdir(r'C:\Users\steph\.openclaw\workspace-coding\rent_finder')

import numpy as np
import pandas as pd
from datetime import datetime

# ── Neighborhood Mapping ────────────────────────────────────────────────────────
# Maps raw neighbourhood names to broader Toronto districts used for fair value grouping.
# Broader districts have enough listings to form valid groups (>=3 per segment).

TORONTO_DISTRICTS = {
    # Downtown Core
    "downtown": "Downtown",
    "financial district": "Downtown",
    "entertainment-financial district": "Downtown",
    "theatre district": "Downtown",
    "university/dundas": "Downtown",
    "bay street": "Downtown",
    "king-adelaide": "Downtown",
    "church-yonge corridor": "Downtown",
    "yonge-street": "Downtown",
    "st. james town": "Downtown",
    "st james town": "Downtown",
    "regent park": "Downtown",
    "harbourfront": "Downtown",
    "king west": "Downtown",
    "queen west": "Downtown",
    # Midtown / Inner
    "liberty village": "Midtown",
    "queen west": "Midtown",
    "parkdale": "Midtown",
    "roncesvalles": "Midtown",
    "high park": "Midtown",
    "high park-swansea": "Midtown",
    "the beaches": "Midtown",
    "beaches": "Midtown",
    "riverdale": "Midtown",
    "leslieville": "Midtown",
    "corktown": "Midtown",
    "east harbour": "Midtown",
    "distillery district": "Midtown",
    "st. lawrence": "Midtown",
    "town of york": "Midtown",
    "little italy": "Midtown",
    "annex": "Midtown",
    "kensington market": "Midtown",
    "ossington": "Midtown",
    "dufferin grove": "Midtown",
    # North York
    "north york": "North York",
    "willowdale": "North York",
    "bayview village": "North York",
    "don mills": "North York",
    "flemingdon park": "North York",
    "flemington": "North York",
    "victoria village": "North York",
    "parkwoods": "North York",
    "york mills": "North York",
    "wilshire": "North York",
    "bayview": "North York",
    "empire": "North York",
    # Scarborough
    "scarborough": "Scarborough",
    "scarborough town centre": "Scarborough",
    "agincourt": "Scarborough",
    "milliken": "Scarborough",
    "steeles": "Scarborough",
    "woodbine": "Scarborough",
    "eglinton east": "Scarborough",
    "markham road": "Scarborough",
    "birchmount": "Scarborough",
    "kennedy": "Scarborough",
    "lawrence east": "Scarborough",
    # Etobicoke
    "etobicoke": "Etobicoke",
    "etobicoke centre": "Etobicoke",
    "the kingsway": "Etobicoke",
    "mimico": "Etobicoke",
    "long branch": "Etobicoke",
    "new Toronto": "Etobicoke",
    "islington": "Etobicoke",
    "centennial": "Etobicoke",
    "west Mall": "Etobicoke",
    # East York
    "east york": "East York",
    "leaside": "East York",
    "playter estates": "East York",
    "danforth": "East York",
    "toothberry": "East York",
}

# Fallback: if raw neighbourhood isn't in the map, classify by keyword matching
DISTRICT_KEYWORDS = {
    "Downtown": ["downtown", "financial", "entertainment", "harbourfront", "king west", "queen west", "yonge", "church", "bay", "university", "st. james", "st james", "regent", "theatre", "liberty"],
    "Midtown": ["midtown", "liberty village", "queen west", "parkdale", "roncesvalles", "high park", "beaches", "riverdale", "leslieville", "corktown", "distillery", "little italy", "annex", "kensington", "ossington", "dufferin"],
    "North York": ["north york", "willowdale", "bayview village", "don mills", "flemingdon", "flemington", "victoria village", "parkwoods", "york mills", "wilshire", "empire"],
    "Scarborough": ["scarborough", "agincourt", "milliken", "steeles", "woodbine", "eglinton", "markham", "birchmount", "kennedy", "lawrence"],
    "Etobicoke": ["etobicoke", "kingsway", "mimico", "long branch", "new toronto", "islington", "centennial", "west mall"],
    "East York": ["east york", "leaside", "playter", "danforth", "toothberry"],
}


def _classify_district(raw_neighborhood: str) -> str:
    """Classify a raw neighbourhood name into a broader Toronto district."""
    if not raw_neighborhood:
        return "Toronto"

    neigh_lower = raw_neighborhood.lower().strip()

    # Direct lookup
    for key, district in TORONTO_DISTRICTS.items():
        if key in neigh_lower or neigh_lower in key:
            return district

    # Keyword fallback
    for district, keywords in DISTRICT_KEYWORDS.items():
        for kw in keywords:
            if kw in neigh_lower:
                return district

    return "Toronto"


def run_pipeline():
    """Run the full scrape + score pipeline with neighbourhood segmentation."""
    import find_deals

    print("=" * 80)
    print("  TORONTO RENTAL DEAL FINDER -- MC-285 Neighbourhood Segmentation Fix")
    print("=" * 80)

    # Step 1: Collect
    print("\n[1] Collecting listings...")
    sources_tried = []
    df_kijiji = None

    try:
        sources_tried.append("Kijiji")
        df_kijiji = find_deals.scrape_kijiji(pages=5)
        print(f"  Kijiji: {len(df_kijiji)} listings")
    except Exception as e:
        print(f"  Kijiji failed: {e}")
        df_kijiji = pd.DataFrame()

    df_cl = pd.DataFrame()
    try:
        sources_tried.append("Craigslist")
        df_cl = find_deals.scrape_craigslist(pages=5)
        print(f"  Craigslist: {len(df_cl)} listings")
    except Exception as e:
        print(f"  Craigslist failed: {e}")

    # Fallback
    if len(df_kijiji) < 30:
        print(f"  Kijiji returned {len(df_kijiji)} < 30 — using sample data")
        df = find_deals.sample_data()
    else:
        frames = [df_kijiji, df_cl]
        frames = [f for f in frames if not f.empty]
        df = find_deals.concat_and_dedup(frames) if frames else pd.DataFrame()

    print(f"  Total after dedup: {len(df)}")
    if df.empty:
        print("ERROR: No listings collected")
        return

    # Step 2: Add district column
    print("\n[2] Mapping neighbourhoods to districts...")
    df["district"] = df["neighborhood"].apply(_classify_district)
    district_counts = df["district"].value_counts()
    for d, cnt in district_counts.items():
        print(f"  {d}: {cnt} listings")

    # Step 3: Score with district-level fair values
    print("\n[3] Computing fair values (by district + beds)...")
    scored = find_deals.score_deals_with_districts(df, district_col="district")

    # Step 4: Report
    print("\n[4] Results:")
    active = scored[scored.get("is_stale", False) == False]
    total_active = len(active)
    total_scored = active["score"].notna().sum()
    deals = active[active["pct_under"] > 0]
    print(f"  Active listings: {total_active}")
    print(f"  Scored (has fair value): {total_scored}")
    print(f"  Under market: {len(deals)}/{total_scored}")

    if not deals.empty:
        best = deals.sort_values("pct_under", ascending=False).iloc[0]
        print(f"\n  BEST DEAL: {best['neighborhood']} {best['beds']}BR ${best['price']}")
        print(f"    Fair value: ${best['fair_value']:.0f} | {best['pct_under']:.1f}% under market")
        print(f"    URL: {best.get('link', 'N/A')}")

        print("\n  Top 10 deals:")
        top10 = deals.sort_values("pct_under", ascending=False).head(10)
        for i, (_, row) in enumerate(top10.iterrows(), 1):
            print(f"    {i}. {row['neighborhood']} {row['beds']}BR ${row['price']} | "
                  f"FV=${row['fair_value']:.0f} | {row['pct_under']:.1f}% under")

    # Step 5: Persist
    print("\n[5] Persisting to SQLite...")
    try:
        from persist import upsert_listings
        records = scored.to_dict("records")
        upsert_listings(records)
        print(f"  Persisted {len(scored)} listings to SQLite")
    except Exception as e:
        print(f"  Persist error: {e}")

    # Step 6: Save CSV
    scored.to_csv("deals_output.csv", index=False)
    print(f"  Saved to deals_output.csv")

    # Step 7: Discord notification
    try:
        from post_discord import post_deals_to_discord
        if not deals.empty:
            post_deals_to_discord(deals.head(5))
            print("  Posted to Discord")
    except Exception as e:
        print(f"  Discord post error: {e}")

    print("\nDone.")
    return scored


if __name__ == "__main__":
    run_pipeline()