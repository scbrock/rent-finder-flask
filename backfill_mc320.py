"""
MC-320 — Backfill standardized neighbourhood + region for existing SQLite listings.

Reads active listings from data/listings.db, applies standardize(), and
writes back the standardized values. This is a one-time data fix that
complements the live pipeline change.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sqlite3
from neighbourhood_lookup import standardize
from region_map import neighbourhood_to_region

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'listings.db')

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    rows = c.execute("SELECT rowid, neighborhood, title FROM listings WHERE is_active = 1").fetchall()
    print(f"Active listings to process: {len(rows)}")

    standardized = 0
    region_filled = 0
    already_specific = 0

    updates = []
    for row in rows:
        nbhd = (row['neighborhood'] or '').strip()
        title = (row['title'] or '').strip()
        new_nbhd = nbhd
        result = standardize(nbhd, title)
        if result is None:
            # No change — keep original
            pass
        elif result == '':
            # Non-Toronto — keep as-is but mark as such
            pass
        else:
            new_nbhd = result
            standardized += 1
        new_region = neighbourhood_to_region(new_nbhd)
        if new_region and (not row['neighborhood'] or row['neighborhood'].lower().strip() in ('toronto', 'city of toronto')):
            region_filled += 1
        if nbhd and nbhd.lower().strip() not in ('toronto', 'city of toronto', ''):
            already_specific += 1
        updates.append((new_nbhd, new_region, row['rowid']))

    # Apply updates in one transaction
    c.executemany("UPDATE listings SET neighborhood = ?, region = ? WHERE rowid = ?", updates)
    conn.commit()

    # Report
    print(f"\nUpdated {len(updates)} listings.")
    print(f"  Standardized (generic -> specific): {standardized}")
    print(f"  Region newly filled: {region_filled}")
    print(f"  Already specific (no change needed): {already_specific}")

    # Verify
    c.execute("SELECT region, COUNT(*) FROM listings WHERE is_active = 1 GROUP BY region ORDER BY 2 DESC")
    print(f"\nRegion distribution after backfill:")
    for region, cnt in c.fetchall():
        print(f"  {region or '(empty)':20s} {cnt}")

    c.execute("SELECT neighborhood, COUNT(*) FROM listings WHERE is_active = 1 AND (LOWER(neighborhood) IN ('toronto', 'city of toronto', '') OR neighborhood IS NULL) GROUP BY neighborhood")
    print(f"\nGeneric neighborhood rows remaining:")
    for nb, cnt in c.fetchall():
        print(f"  {repr(nb):30s} {cnt}")

    conn.close()
    print("\nDone.")


if __name__ == '__main__':
    main()