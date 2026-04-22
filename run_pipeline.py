import os, sys, warnings, time
warnings.filterwarnings('ignore')
os.chdir(r'C:\Users\steph\.openclaw\workspace-coding\rent_finder')
import find_deals
import persist
import health_monitor
import post_discord

ALERT_THRESHOLD = 100


def run_pipeline() -> dict:
    results = {
        "kijiji": {"listings": 0, "errors": 0, "duration_secs": 0},
        "craigslist": {"listings": 0, "errors": 0, "duration_secs": 0},
        "total": 0,
        "deals": 0,
        "best": None,
        "alert_fired": False,
    }

    t0 = time.time()
    kijiji_errors = 0
    try:
        df_kijiji = find_deals.scrape_kijiji(pages=3)
    except Exception as e:
        print(f"  Kijiji exception: {e}")
        df_kijiji = find_deals.pd.DataFrame()
        kijiji_errors = 1
    kijiji_duration = time.time() - t0
    results["kijiji"] = {"listings": len(df_kijiji), "errors": kijiji_errors, "duration_secs": round(kijiji_duration, 1)}

    t0 = time.time()
    cl_errors = 0
    try:
        df_craigslist = find_deals.scrape_craigslist(pages=2)
    except Exception as e:
        print(f"  Craigslist exception: {e}")
        df_craigslist = find_deals.pd.DataFrame()
        cl_errors = 1
    cl_duration = time.time() - t0
    results["craigslist"] = {"listings": len(df_craigslist), "errors": cl_errors, "duration_secs": round(cl_duration, 1)}

    df = find_deals.concat_and_dedup([df_kijiji, df_craigslist])
    print(f"  Total raw after dedup: {len(df)}")
    results["total"] = len(df)

    if len(df) == 0:
        results["alert_fired"] = True
        return results

    df["district"] = df["neighborhood"].apply(find_deals._classify_district)
    scored = find_deals.score_deals_with_districts(df, district_col="district")
    print(f"  After scoring: {len(scored)}")

    source_errors = {"Kijiji": results["kijiji"]["errors"], "Craigslist": results["craigslist"]["errors"]}
    source_durations = {"Kijiji": results["kijiji"]["duration_secs"], "Craigslist": results["craigslist"]["duration_secs"]}
    persist.upsert_listings(scored.to_dict('records'), scored_df=scored,
                             source_errors=source_errors, source_durations=source_durations)

    if not scored.empty:
        best = scored.sort_values("pct_under", ascending=False).iloc[0]
        pct = best.get('pct_under', 0)
        fv = best.get('fair_value', 0)
        results["best"] = {
            "neighborhood": best.get("neighborhood", "?"),
            "beds": int(best.get("beds", 0)),
            "price": int(best.get("price", 0)),
            "fv": int(fv),
            "pct": round(float(pct), 1),
            "score": round(float(best.get("score", 0)), 3),
        }
        print(f"  BEST: {results['best']['neighborhood']} {results['best']['beds']}BR "
              f"${results['best']['price']} (FV=${results['best']['fv']}, +{results['best']['pct']}%, score={results['best']['score']:.3f})")
        underpriced = scored[scored['pct_under'] > 0]
        results["deals"] = len(underpriced)
        print(f"  Under market: {len(underpriced)}/{len(scored)}")
        scored.to_csv('deals_output.csv', index=False)
        print(f"  Saved to deals_output.csv")
    else:
        results["deals"] = 0

    # Alert check
    if results["total"] < ALERT_THRESHOLD:
        print(f"  ⚠️  ALERT: Total listings ({results['total']}) below threshold ({ALERT_THRESHOLD})")
        results["alert_fired"] = True

    return results


if __name__ == "__main__":
    print("=== Pipeline run starting ===")
    t_start = time.time()
    results = run_pipeline()
    elapsed = time.time() - t_start

    print(f"\n=== Pipeline done in {elapsed:.1f}s ===")
    print(f"  Total: {results['total']} listings | {results['deals']} deals | "
          f"Kijiji: {results['kijiji']['listings']} | Craigslist: {results['craigslist']['listings']}")

    if results.get("best"):
        b = results["best"]
        print(f"  Best: {b['neighborhood']} {b['beds']}BR ${b['price']} (+{b['pct']}% under FV ${b['fv']}, score={b['score']})")

    if results["alert_fired"]:
        print(f"  ⚠️  Health alert fired — check source status with: python health_monitor.py --check-health")

    # Post to Discord
    try:
        import pandas as pd
        df = pd.read_csv('deals_output.csv')
        # Only rank non-null pct_under
        df_out = df.dropna(subset=['pct_under']).copy()
        df_out['rank'] = df_out['pct_under'].rank(ascending=False, method='min').astype(int)
        post_discord.post_deals_to_discord(df_out, limit=5)
        print("  Discord posted.")
    except Exception as e:
        print(f"  Discord post failed: {e}")

    print("=== Done ===")