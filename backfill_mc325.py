"""
MC-325: Backfill price_history table from raw_YYYY-MM-DD.json files.

The price_history table is empty on live data because upsert_price_history()
was never wired into the live pipeline. To give the price-drop filter real
data immediately after MC-325 ships, this script reads the raw scrape JSON
files (raw_2026-07-05.json, raw_2026-07-06.json, raw_2026-07-07.json) and
inserts a price_history row per (listing_id, scrape_date) pair.

This means:
  - Listings seen on 2026-07-05 only -> 1 row (insufficient for drop detection)
  - Listings seen on 2026-07-05 + 2026-07-07 with different prices -> 2 rows,
    enables drop detection
  - Listings seen on 2026-07-06 + 2026-07-07 with different prices -> 2 rows

The seen_at timestamp is set to the SCRAPE DATE at 12:00 UTC (mid-day) so
all rows from the same scrape day share a timestamp. The existing
price_history UNIQUE(listing_id, seen_at) constraint makes this idempotent:
re-running this script does NOT create duplicate rows.

Usage:
    python backfill_mc325.py [--data-dir DIR] [--dry-run]

The script writes a small report to stdout: total rows attempted, total
inserted, per-file counts, and a sample of detected price drops (oldest
price > newest price).
"""

import argparse
import datetime as _dt
import json
import os
import sys
from typing import Iterable

# Ensure rent_finder/ is on sys.path when run as a script
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from persist import init_db, seed_price_history_for_listing, get_listing_price_drop


# Files we know contain historical scrape data (oldest -> newest)
DEFAULT_FILES = [
    ("raw_2026-07-05.json", "2026-07-05T12:00:00Z"),
    ("raw_2026-07-06.json", "2026-07-06T12:00:00Z"),
    ("raw_2026-07-07.json", "2026-07-07T12:00:00Z"),
]


def _build_id_set(rows: Iterable[dict]) -> dict:
    """Return {listing_id: price} from a list of raw listing dicts."""
    out = {}
    for r in rows:
        lid = r.get("listing_id") or r.get("url") or r.get("link", "")
        if not lid:
            continue
        try:
            price = float(r.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out[lid] = price
    return out


def _load_raw_file(path: str) -> list:
    """Load a raw scrape JSON file. Returns [] if missing or malformed."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  WARN: failed to load {path}: {e}")
        return []


def backfill(data_dir: str, files=DEFAULT_FILES, dry_run: bool = False) -> dict:
    """
    Insert price_history rows for each (file, listing_id) pair. Returns a
    summary dict with per-file counts and a sample of detected price drops.
    """
    init_db()  # ensure schema exists

    summary = {
        "files": [],
        "total_attempted": 0,
        "total_inserted": 0,
        "dropped_listings_sample": [],
        "all_dropped_count": 0,
    }

    # Step 1: seed price_history rows
    for fname, seen_at in files:
        path = os.path.join(data_dir, fname)
        rows = _load_raw_file(path)
        id_to_price = _build_id_set(rows)
        attempted = 0
        inserted = 0
        for lid, price in id_to_price.items():
            attempted += 1
            if dry_run:
                # Skip writes in dry-run mode but count attempted
                continue
            if seed_price_history_for_listing(lid, price, seen_at):
                inserted += 1
        summary["files"].append({
            "file": fname,
            "seen_at": seen_at,
            "rows_in_file": len(rows),
            "attempted": attempted,
            "inserted": inserted,
        })
        summary["total_attempted"] += attempted
        summary["total_inserted"] += inserted
        print(f"  {fname}: {attempted} listings, {inserted} inserted (seen_at={seen_at})")

    # Step 2: report detected price drops after backfill
    if not dry_run:
        from persist import get_all_listing_price_drops
        all_drops = get_all_listing_price_drops(days=14, min_drop_pct=1.0)
        summary["all_dropped_count"] = len(all_drops)
        # Sort by drop_pct descending, take top 5 for the sample
        sorted_drops = sorted(all_drops.values(), key=lambda d: d["drop_pct"], reverse=True)
        summary["dropped_listings_sample"] = sorted_drops[:5]
        print(f"\n  Detected {len(all_drops)} listings with a price drop (>=1% in 14d window)")
        for d in sorted_drops[:5]:
            print(
                f"    {d['listing_id']}: ${d['from_price']:.0f} -> ${d['to_price']:.0f} "
                f"({d['drop_pct']:.1f}% drop, {d['days_ago_from']}d ago)"
            )

    return summary


def main():
    ap = argparse.ArgumentParser(description="MC-325 price_history backfill")
    ap.add_argument("--data-dir", default=os.path.join(_HERE, "data"),
                    help="Directory containing raw_YYYY-MM-DD.json files")
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute counts without writing to the database")
    args = ap.parse_args()

    print(f"MC-325 backfill starting (data_dir={args.data_dir}, dry_run={args.dry_run})")
    summary = backfill(args.data_dir, dry_run=args.dry_run)
    print(f"\nDone: {summary['total_inserted']}/{summary['total_attempted']} rows inserted")
    print(f"Detected {summary['all_dropped_count']} listings with a price drop")
    return 0


if __name__ == "__main__":
    sys.exit(main())