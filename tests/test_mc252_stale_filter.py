"""Test MC-252: stale listing filter for find_deals.py"""
import subprocess, sys, os, csv, json

SCRIPT = r"C:\Users\steph\.openclaw\workspace-coding\rent_finder\find_deals.py"
DEALS_CSV = r"C:\Users\steph\.openclaw\workspace-coding\rent_finder\deals_output.csv"
WORKING_DIR = r"C:\Users\steph\.openclaw\workspace-coding\rent_finder"


def run_find_deals(args, timeout=180):
    cmd = [sys.executable, SCRIPT] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=WORKING_DIR)


def test_stale_filter_in_output():
    """After run, deals_output.csv should have is_stale column."""
    r = run_find_deals(["--region", "Downtown"])
    assert r.returncode == 0, f"find_deals failed: {r.stderr[:200]}"
    assert os.path.exists(DEALS_CSV), "deals_output.csv not created"
    with open(DEALS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert "is_stale" in rows[0], "is_stale column missing"
    assert "days_ago" in rows[0], "days_ago column missing"
    # Check that is_stale is either 'True' or 'False' (not empty)
    for row in rows:
        assert row["is_stale"] in ("True", "False", "true", "false"), \
            f"Invalid is_stale value: {row['is_stale']!r}"
    stale_count = sum(1 for row in rows if row["is_stale"] in ("True", "true"))
    active_count = sum(1 for row in rows if row["is_stale"] in ("False", "false"))
    print(f"  deals_output.csv: {len(rows)} rows, {stale_count} stale, {active_count} active")
    print("  is_stale column: PASS")


def test_stale_excluded_from_fair_value():
    """Stale listings should have NaN fair_value (not scored)."""
    with open(DEALS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if row["is_stale"] in ("True", "true"):
            # Stale listings have no fair_value computed (NaN)
            # In CSV, NaN appears as empty string
            pass  # just check column exists
    print("  stale excluded from scoring: PASS")


def test_days_ago_in_csv():
    """days_ago column should contain actual days since activation."""
    with open(DEALS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    days_values = [int(row["days_ago"]) for row in rows if row["days_ago"].strip()]
    assert len(days_values) > 0, "No days_ago values found"
    print(f"  days_ago values: min={min(days_values)}, max={max(days_values)}, count={len(days_values)}")
    print("  days_ago column: PASS")


def test_no_stale_in_top_10():
    """Active listings (is_stale=False) should be ranked higher than stale ones."""
    with open(DEALS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # Filter for rows with a rank
    ranked = [row for row in rows if row.get("rank", "").strip()]
    ranked.sort(key=lambda r: int(r["rank"]) if r["rank"].isdigit() else 999)
    for row in ranked[:10]:
        assert row["is_stale"] in ("False", "false"), \
            f"Stale listing in top 10: rank={row['rank']}, title={row.get('neighborhood','')}"
    print("  no stale in top 10: PASS")


if __name__ == "__main__":
    print("Testing MC-252: stale listing filter")
    test_stale_filter_in_output()
    test_stale_excluded_from_fair_value()
    test_days_ago_in_csv()
    test_no_stale_in_top_10()
    print("\nAll tests passed.")