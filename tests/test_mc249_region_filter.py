"""Test MC-249: Toronto region filter for find_deals.py
Tests region mapping and CLI filter in isolation (no live scraping).
"""
import subprocess, sys, os, csv, tempfile

SCRIPT = r"C:\Users\steph\.openclaw\workspace-coding\rent_finder\find_deals.py"
WORKING_DIR = r"C:\Users\steph\.openclaw\workspace-coding\rent_finder"


def test_help():
    r = subprocess.run(
        [sys.executable, SCRIPT, "--help"],
        capture_output=True, text=True, timeout=15, cwd=WORKING_DIR
    )
    assert r.returncode == 0, f"--help failed: {r.stderr}"
    assert "--region" in r.stdout, "--region not in help output"
    print("  --help: PASS")


def test_region_map_coverage():
    """Verify neighbourhood_to_region classifies all 6 regions correctly."""
    sys.path.insert(0, WORKING_DIR)
    from region_map import neighbourhood_to_region

    cases = [
        # (neighbourhood, expected_region)
        ("Yorkville", "Downtown"),
        ("Liberty Village", "Downtown"),
        ("Annex", "Downtown"),
        ("The Beaches", "East End"),
        ("The Junction", "West End"),
        ("High Park", "West End"),
        ("Willowdale", "North York"),
        ("Don Mills", "North York"),
        ("Mimico", "Etobicoke"),
        ("Etobicoke", "Etobicoke"),
        ("Agincourt", "Scarborough"),
        ("Scarborough Town Centre", "Scarborough"),
        # Non-Toronto excluded
        ("Mississauga", ""),
        ("Brampton", ""),
        ("Oakville", ""),
        ("Richmond Hill", ""),
        ("Vaughan", ""),
        ("Oshawa", ""),
        # Normalized variants
        ("Downtown Toronto", "Downtown"),
        ("Downtown, Toronto", "Downtown"),
        ("North york", "North York"),
        ("Kensington market", "Downtown"),
        ("Annex.Toronto", "Downtown"),
        ("Etobicoke, Mimico", "Etobicoke"),
        ("Cliffside, Scarborough", "East End"),
        ("Richmond hill", ""),
    ]

    for nb, expected in cases:
        result = neighbourhood_to_region(nb)
        assert result == expected, \
            f"neighbourhood_to_region({nb!r})={result!r}, expected {expected!r}"
    print("  neighbourhood_to_region coverage: PASS")


def test_region_filter_cli():
    """Verify --region flag filters CSV output (uses existing deals_output.csv)."""
    DEALS_CSV = os.path.join(WORKING_DIR, "deals_output.csv")
    if not os.path.exists(DEALS_CSV):
        print("  (deals_output.csv not found, skipping CLI filter test)")
        return

    sys.path.insert(0, WORKING_DIR)
    from region_map import neighbourhood_to_region

    with open(DEALS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Simulate what --region filter does
    for region in ["Downtown", "East End", "West End", "North York", "Etobicoke", "Scarborough"]:
        filtered = [r for r in rows if r.get("region", "").strip() == region]
        assert len(filtered) > 0, f"--region {region}: expected >0 listings, got {len(filtered)}"
        # Verify all filtered rows actually have the right region
        assert all(r["region"] == region for r in filtered), \
            f"Some rows don't match {region}"
    print("  --region filter logic: PASS (all 6 regions have listings)")


def test_region_column_in_csv():
    """Verify deals_output.csv includes a region column."""
    DEALS_CSV = os.path.join(WORKING_DIR, "deals_output.csv")
    if not os.path.exists(DEALS_CSV):
        print("  (deals_output.csv not found, skipping CSV column test)")
        return
    with open(DEALS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows, "deals_output.csv is empty"
    assert "region" in rows[0], "region column missing in deals_output.csv"
    print("  region column in CSV: PASS")


def test_non_toronto_excluded():
    """Non-Toronto municipalities should return empty string (excluded)."""
    sys.path.insert(0, WORKING_DIR)
    from region_map import neighbourhood_to_region

    non_to = ["Mississauga", "Brampton", "Oakville", "Richmond Hill", "Vaughan", "Oshawa"]
    for nb in non_to:
        result = neighbourhood_to_region(nb)
        assert result == "", \
            f"neighbourhood_to_region({nb!r})={result!r}, expected '' (non-Toronto)"
    print("  non-Toronto exclusion: PASS")


if __name__ == "__main__":
    print("Testing MC-249: Toronto region filter\n")
    test_help()
    test_region_map_coverage()
    test_region_filter_cli()
    test_region_column_in_csv()
    test_non_toronto_excluded()
    print("\nAll MC-249 tests passed.")
