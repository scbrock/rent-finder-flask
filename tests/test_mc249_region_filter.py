"""Test MC-249: Toronto region filter for find_deals.py"""
import subprocess, sys, os, csv

SCRIPT = r"C:\Users\steph\.openclaw\workspace-coding\rent_finder\find_deals.py"
DEALS_CSV = r"C:\Users\steph\.openclaw\workspace-coding\rent_finder\deals_output.csv"
WORKING_DIR = r"C:\Users\steph\.openclaw\workspace-coding\rent_finder"


def run_find_deals(args):
    cmd = [sys.executable, SCRIPT] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=WORKING_DIR)
    return result


def test_help():
    r = run_find_deals(["--help"])
    assert r.returncode == 0, f"--help failed: {r.stderr}"
    assert "--region" in r.stdout, f"--region not in help output"
    print("  --help: PASS")


def test_no_filter():
    r = run_find_deals([])
    assert r.returncode == 0, f"no filter failed: {r.stderr}"
    assert "Region filter:" not in r.stdout, "Region label shouldn't appear without --region"
    print("  (no filter): PASS")


def test_region_filter(region):
    r = run_find_deals(["--region", region])
    assert r.returncode == 0, f"--region {region} failed: {r.stderr}"
    assert any(f"Region filter: {region}" in l for l in r.stdout.splitlines()), \
        f"Region filter not printed for {region}"
    with open(DEALS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    non_empty = [row for row in rows if row.get("region", "").strip()]
    assert all(row["region"] == region for row in non_empty), \
        f"Some rows aren't {region}: {[r['region'] for r in non_empty]}"
    print(f"  --region {region}: PASS ({len(non_empty)} deals)")


def test_region_column_in_csv():
    r = run_find_deals(["--region", "Downtown"])
    assert r.returncode == 0
    with open(DEALS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert "region" in rows[0], "region column missing in deals_output.csv"
    print("  region column in CSV: PASS")


if __name__ == "__main__":
    print("Testing MC-249: Toronto region filter")
    test_help()
    test_no_filter()
    for region in ["Downtown", "East End", "West End", "North York", "Etobicoke", "Scarborough"]:
        test_region_filter(region)
    test_region_column_in_csv()
    print("\nAll tests passed.")