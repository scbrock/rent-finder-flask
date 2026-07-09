"""
MC-320 / MC-324 — Backfill standardized neighbourhood + region for SQLite listings.

Reads active listings from data/listings.db, applies standardize() with
title AND URL-slug fallback, and writes back the standardized values.

This is a one-time data fix that complements the live pipeline change.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sqlite3
from neighbourhood_lookup import standardize, extract_url_slug
from region_map import neighbourhood_to_region

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'listings.db')

GENERIC_VALUES = {'toronto', 'city of toronto', 'gt', 'gta', 'ontario', '',
                  'toronto, on', 'toronto, ontario'}


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    rows = c.execute("SELECT rowid, neighborhood, title, url FROM listings WHERE is_active = 1").fetchall()
    print(f"Active listings to process: {len(rows)}")

    standardized = 0
    region_filled = 0
    already_specific = 0
    title_resolved = 0
    slug_resolved = 0

    updates = []
    for row in rows:
        nbhd = (row['neighborhood'] or '').strip()
        title = (row['title'] or '').strip()
        url = (row['url'] or '').strip()
        url_slug = extract_url_slug(url)
        new_nbhd = nbhd

        # If generic, try title + url_slug
        if nbhd.lower().strip() in GENERIC_VALUES:
            result = standardize(nbhd, title, url_slug)
            if result is None:
                pass  # keep original
            elif result == '':
                pass  # non-Toronto — keep original
            else:
                # Detect which fallback resolved it
                title_result = standardize(nbhd, title) if title else None
                if title_result == result:
                    title_resolved += 1
                elif url_slug:
                    slug_resolved += 1
                new_nbhd = result
                standardized += 1
        else:
            # Already specific — still try to upgrade via slug
            result = standardize(nbhd, '', url_slug)
            if result:
                new_nbhd = result
                standardized += 1

        new_region = neighbourhood_to_region(new_nbhd)
        if new_region and (not row['neighborhood'] or row['neighborhood'].lower().strip() in GENERIC_VALUES):
            region_filled += 1
        if nbhd and nbhd.lower().strip() not in GENERIC_VALUES:
            already_specific += 1
        updates.append((new_nbhd, new_region, row['rowid']))

    # Apply updates in one transaction
    c.executemany("UPDATE listings SET neighborhood = ?, region = ? WHERE rowid = ?", updates)
    conn.commit()

    # Report
    print(f"\nUpdated {len(updates)} listings.")
    print(f"  Standardized (generic -> specific): {standardized}")
    print(f"    via title fallback: {title_resolved}")
    print(f"    via URL slug fallback: {slug_resolved}")
    print(f"  Region newly filled: {region_filled}")
    print(f"  Already specific (no change needed): {already_specific}")

    # Verify
    print(f"\nRegion distribution after backfill:")
    for region, cnt in c.execute("SELECT region, COUNT(*) FROM listings WHERE is_active = 1 GROUP BY region ORDER BY 2 DESC").fetchall():
        print(f"  {region or '(empty)':20s} {cnt}")

    print(f"\nGeneric neighborhood rows remaining:")
    for nb, cnt in c.execute("SELECT neighborhood, COUNT(*) FROM listings WHERE is_active = 1 AND (LOWER(neighborhood) IN ('toronto', 'city of toronto', '') OR neighborhood IS NULL) GROUP BY neighborhood").fetchall():
        print(f"  {repr(nb):30s} {cnt}")

    print()
    print("=== Coverage metrics ===")
    total = c.execute("SELECT COUNT(*) FROM listings WHERE is_active = 1").fetchone()[0]
    generic = c.execute(
        "SELECT COUNT(*) FROM listings WHERE is_active = 1 "
        "AND (LOWER(TRIM(COALESCE(neighborhood,''))) IN ("
        "'toronto', 'city of toronto', 'gt', 'gta', 'ontario', '', "
        "'toronto, on', 'toronto, ontario') OR neighborhood IS NULL)"
    ).fetchone()[0]
    with_region = c.execute(
        "SELECT COUNT(*) FROM listings WHERE is_active = 1 "
        "AND region IS NOT NULL AND region != ''"
    ).fetchone()[0]
    print(f"  Total active: {total}")
    print(f"  Generic neighbourhood: {generic} ({100*generic/total:.1f}%)")
    print(f"  With region: {with_region} ({100*with_region/total:.1f}%)")

    conn.close()
    print("\nDone.")


if __name__ == '__main__':
    main()