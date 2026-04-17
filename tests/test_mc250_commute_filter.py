"""Test MC-250: commute time filter for find_deals.py"""
import subprocess, sys, os, csv

SCRIPT = r"C:\Users\steph\.openclaw\workspace-coding\rent_finder\find_deals.py"
DEALS_CSV = r"C:\Users\steph\.openclaw\workspace-coding\rent_finder\deals_output.csv"
WORKING_DIR = r"C:\Users\steph\.openclaw\workspace-coding\rent_finder"


def run_find_deals(args, timeout=180):
    cmd = [sys.executable, SCRIPT] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=WORKING_DIR)
    return result


def test_help_shows_commute_args():
    r = run_find_deals(["--help"])
    assert r.returncode == 0
    assert "--max-commute" in r.stdout
    assert "--destination" in r.stdout
    print("  --help with commute args: PASS")


def test_no_crash_no_destination():
    """Without --destination, no API calls, should run clean."""
    r = run_find_deals(["--region", "Downtown"])
    assert r.returncode == 0, f"failed without destination: {r.stderr[:200]}"
    print("  no-destination run: PASS")


def test_destination_provided():
    """With --destination 'Union Station' but no max_commute: geocode + compute."""
    r = run_find_deals(["--destination", "Union Station, Toronto"], timeout=60)
    # Should not crash even if geocode fails
    assert r.returncode == 0, f"failed with destination: {r.stderr[:200]}"
    print("  --destination Union Station: PASS")


def test_commute_filter_full():
    """Full filter: --destination + --max-commute 30."""
    r = run_find_deals([
        "--destination", "Union Station, Toronto",
        "--max-commute", "30",
    ], timeout=120)
    assert r.returncode == 0, f"commute filter failed: {r.stderr[:200]}"
    # Should see commute filter message
    assert any("Commute filter" in l or "commute" in l.lower() for l in r.stdout.splitlines()), \
        f"No commute filter confirmation in output"
    # Check CSV has commute_minutes column
    with open(DEALS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert "commute_minutes" in rows[0], "commute_minutes column missing"
    print(f"  --destination + --max-commute 30: PASS ({len(rows)} rows)")


def test_commute_combined_with_region():
    """Region + destination + max-commute all together."""
    r = run_find_deals([
        "--region", "Downtown",
        "--destination", "St. Michael's Hospital, Toronto",
        "--max-commute", "45",
    ], timeout=120)
    assert r.returncode == 0, f"combined filter failed: {r.stderr[:200]}"
    with open(DEALS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert all(row["region"] == "Downtown" for row in rows if row.get("region", "").strip())
    assert "commute_minutes" in rows[0]
    print(f"  combined region+commute filter: PASS ({len(rows)} rows)")


if __name__ == "__main__":
    print("Testing MC-250: commute time filter")
    test_help_shows_commute_args()
    test_no_crash_no_destination()
    test_destination_provided()
    test_commute_filter_full()
    test_commute_combined_with_region()
    print("\nAll tests passed.")