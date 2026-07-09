"""MC-334: Backfill the SQLite listings.title column.

Bug: find_deals.py scrape_kijiji() and scrape_craigslist() row builders
did NOT include the "title" key in pre-MC-334 builds, so 320/376 active
listings had title="" (56/376 = 14.9% coverage). UI shows title="" everywhere.

Two strategies to recover titles for existing rows:

1. **Raw-file match (preferred)** — for every raw_YYYY-MM-DD.json file,
   build a {url: title} map (last-write-wins). UPDATE listings.title for
   any row whose url is in the map AND title is currently empty.

2. **URL-slug fallback (catch-all)** — for rows still empty after step 1,
   synthesize a title from the descriptive URL slug. Kijiji URLs encode
   a hyphenated slug (e.g. ".../2-bedroom-apartment-for-rent-295-dufferin-
   street/1735623688"); Craigslist URLs encode a slug too
   (".../toronto-furnished-basement-bedroom-in/<id>"). The slug is
   converted to title-case whitespace ("2 Bedroom Apartment For Rent
   295 Dufferin Street") which is a reasonable title until the next
   scrape refreshes it.

Safe to run multiple times — only updates rows whose title is empty.
"""
import json
import os
import re
import sys
import sqlite3
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
DB_PATH = os.path.join(DATA_DIR, "listings.db")


def _slug_to_title(slug: str) -> str:
    """Convert a hyphenated slug to title-case whitespace.

    Strips trailing single-letter fragments ("in", "to", "on") that are
    common at the end of CL slugs ("toronto-furnished-basement-bedroom-in").

    Examples:
        "2-bedroom-apartment-for-rent-295-dufferin-street"
            -> "2 Bedroom Apartment For Rent 295 Dufferin Street"
        "toronto-furnished-basement-bedroom-in"
            -> "Toronto Furnished Basement Bedroom"
        "north-york-north-york-on-van-horne"
            -> "North York North York On Van Horne"
    """
    if not slug:
        return ""
    # Normalize separators, drop leading/trailing dashes, lowercase.
    s = re.sub(r"[^a-zA-Z0-9-]+", "-", slug).strip("-").lower()
    words = [w for w in s.split("-") if w]
    if not words:
        return ""
    # Drop trailing 1-letter and 2-letter prepositions
    _DROP_TAIL = {"in", "on", "at", "to", "of", "by", "an"}
    while len(words) > 1 and words[-1] in _DROP_TAIL:
        words.pop()
    # Title-case each word; keep all-digits tokens as-is.
    titled = [w.upper() if w.isdigit() else w.capitalize() for w in words]
    return " ".join(titled)


def _title_from_url(url: str) -> str:
    """Extract a best-effort title from a listing URL.

    Returns "" if the URL doesn't match a known shape.
    """
    if not url:
        return ""
    # Kijiji: https://www.kijiji.ca/v-<cat>/city-of-toronto/<slug>/<id>
    m = re.search(
        r"kijiji\.ca/v-[^/]+/city-of-toronto/([^/]+)/\d+/?$",
        url,
    )
    if m:
        return _slug_to_title(m.group(1))
    # Craigslist: https://www.craigslist.org/view/d/<slug>/<id>
    m = re.search(r"craigslist\.org/view/d/([^/]+)/[A-Za-z0-9]+/?$", url)
    if m:
        return _slug_to_title(m.group(1))
    # Generic fallback: use the second-to-last path segment.
    parts = [p for p in url.split("/") if p]
    if len(parts) >= 2:
        return _slug_to_title(parts[-2])
    return ""


def collect_titles_from_raw() -> dict:
    """Return {url: title} built from all raw_YYYY-MM-DD.json files."""
    url_to_title: dict = {}
    if not os.path.isdir(DATA_DIR):
        print(f"  WARN: {DATA_DIR} does not exist")
        return url_to_title
    files = sorted(f for f in os.listdir(DATA_DIR) if f.startswith("raw_") and f.endswith(".json"))
    print(f"  Scanning {len(files)} raw files in {DATA_DIR}")
    for fname in files:
        path = os.path.join(DATA_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                raw_listings = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"    SKIP {fname}: {e}")
            continue
        for lst in raw_listings:
            url = (lst.get("url") or "").strip()
            title = (lst.get("title") or "").strip()
            if not url or not title:
                continue
            # Last-write-wins: raw files are sorted ascending, so newer
            # titles overwrite older ones for the same URL.
            url_to_title[url] = title
    return url_to_title


def collect_slug_titles_from_db(db_path: str) -> dict:
    """Return {url: synthesized_title} for any active SQLite row whose
    title is currently empty AND whose URL is parseable into a slug."""
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT url FROM listings "
            "WHERE is_active = 1 AND (title IS NULL OR title = '')"
        )
        urls = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    out = {}
    for u in urls:
        t = _title_from_url(u)
        if t:
            out[u] = t
    return out


def backfill_titles(db_path: str = DB_PATH, dry_run: bool = False) -> dict:
    """UPDATE listings SET title = ? WHERE url = ? AND (title IS NULL OR title = '').

    Two passes:
      1. Raw-file match (preferred — real titles)
      2. URL-slug synthesis (fallback for rows not in any raw file)

    Returns stats dict.
    """
    raw_titles = collect_titles_from_raw()
    print(f"  Built {len(raw_titles)} url->title pairs from raw files")

    slug_titles = collect_slug_titles_from_db(db_path)
    print(f"  Built {len(slug_titles)} url->title pairs from URL slug fallback")

    if not raw_titles and not slug_titles:
        return {"matched": 0, "updated": 0, "unchanged": 0, "dry_run": dry_run}

    if not os.path.exists(db_path):
        print(f"  ERROR: SQLite db not found at {db_path}")
        return {
            "matched": 0,
            "updated": 0,
            "unchanged": 0,
            "dry_run": dry_run,
            "error": "missing_db",
        }

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM listings")
        total_before = cur.fetchone()[0]
        cur = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE title IS NOT NULL AND title != ''"
        )
        titled_before = cur.fetchone()[0]
        print(f"  SQLite pre-state: {total_before} rows, {titled_before} with title")

        updated = 0
        matched = 0
        # Single transaction for atomicity
        def _apply(url_to_title: dict, label: str) -> int:
            n = 0
            for url, title in url_to_title.items():
                cur = conn.execute(
                    "UPDATE listings SET title = ? WHERE url = ? "
                    "AND (title IS NULL OR title = '')",
                    (title, url),
                )
                if cur.rowcount > 0:
                    n += cur.rowcount
            print(f"    [{label}] updated {n} rows")
            return n

        matched = _apply(raw_titles, "raw-file")
        slug_updated = _apply(slug_titles, "slug-fallback")
        updated = matched + slug_updated

        if not dry_run:
            conn.commit()

        cur = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE title IS NOT NULL AND title != ''"
        )
        titled_after = cur.fetchone()[0]
        print(
            f"  SQLite post-state: {total_before} rows, {titled_after} with title"
        )
        print(
            f"  Updated {updated} rows ({titled_before} -> {titled_after}, "
            f"+{titled_after - titled_before})"
        )

        return {
            "matched": matched,
            "slug_updated": slug_updated,
            "updated": updated,
            "unchanged": total_before - titled_after,
            "titled_before": titled_before,
            "titled_after": titled_after,
            "dry_run": dry_run,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=== DRY RUN (no DB writes) ===")
    print(f"MC-334 backfill @ {datetime.now().isoformat(timespec='seconds')}")
    stats = backfill_titles(dry_run=dry_run)
    print(f"Done: {stats}")