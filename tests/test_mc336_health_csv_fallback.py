"""
MC-336: CSV fallback for /api/health (data-freshness pill).

Root cause: on Render, `data/listings.db` is gitignored and ephemeral — a
cold boot wipes it, leaving the deployed SQLite empty even though the CSV
(`deals_output.csv`, which IS shipped to Render on every deploy) is intact.
`load_deals()` already falls back to CSV, but `_compute_health_snapshot()`
only queries SQLite, so the health pill showed `status='unknown'`,
`active_listings=0` even when `/api/deals` was returning 200+ rows.

Fix: `_compute_health_snapshot_from_csv()` derives the same contract shape
from the CSV (file mtime as last_scrape_ts, row count as active_listings,
pct_under>0 row count as deal_count). Wired into the main function for two
cases:
  1. SQLite missing (`os.path.exists(DB_PATH) == False`)
  2. SQLite present but has zero active rows (cold-boot wipe)

Covers:
  - _compute_health_snapshot_from_csv derives correct shape from a real CSV
  - file mtime drives last_scrape_ts and minutes_since_scrape
  - per-source breakdown respects CSV `source` column
  - deal_count = rows where pct_under > 0
  - missing CSV → snapshot returns zeros (no 500)
  - SQLite path still preferred when populated
  - SQLite-empty-but-present also triggers CSV fallback (cold-boot)
  - Both a /api/health probe + a live Flask test_client exercise the path
  - Regression guard: a smoke test that asserts either SQLite or CSV path
    populates the snapshot within 4hrs of "data age"
"""
import os
import sys
import csv
import sqlite3
import re
from datetime import datetime, timezone, timedelta

import pytest

RENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RENT_DIR)

import app as app_module  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_csv(path: str, rows: list[dict], source_col_value: str | None = None,
               mtime: float | None = None) -> None:
    """Write a deals_output.csv-compatible file and optionally set its mtime.

    `source_col_value` overrides the `source` column for every row (lets us
    test per-source breakdown). When None, rows use their own `source` key.
    """
    cols = [
        "listing_id", "source", "price", "beds", "pct_under",
        "neighborhood", "url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for r in rows:
            row = {c: r.get(c, "") for c in cols}
            if source_col_value is not None:
                row["source"] = source_col_value
            writer.writerow(row)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


@pytest.fixture
def csv_finder(monkeypatch, tmp_path):
    """Point app_module.DEALS_CSV at a temp CSV file we control."""
    csv_path = str(tmp_path / "deals_output.csv")
    monkeypatch.setattr(app_module, "DEALS_CSV", csv_path)
    return csv_path


@pytest.fixture
def empty_sqlite_db(monkeypatch, tmp_path):
    """Point app_module.DB_PATH at a fresh empty SQLite (no rows seeded)."""
    db = str(tmp_path / "empty_listings.db")
    monkeypatch.setattr(app_module, "DB_PATH", db)
    # Wipe the persist module's cached DB_PATH too so init_db() uses ours
    try:
        import persist
        monkeypatch.setattr(persist, "DB_PATH", db)
    except Exception:
        pass
    try:
        from persist import init_db
        init_db()
    except Exception:
        pass
    yield db


# ---------------------------------------------------------------------------
# _compute_health_snapshot_from_csv() — direct unit tests
# ---------------------------------------------------------------------------

class TestComputeHealthSnapshotFromCsv:
    def test_returns_snapshot_shape_unchanged(self, csv_finder):
        mtime = datetime.now(timezone.utc).timestamp()
        _write_csv(csv_finder, [
            {"listing_id": "L1", "source": "kijiji", "price": 1500, "beds": 1,
             "pct_under": 10.0, "neighborhood": "Bay St Corridor",
             "url": "https://k/1"},
        ], mtime=mtime)
        snap = app_module._compute_health_snapshot_from_csv({"k": 1})  # carry dummy key
        # The function mutates and returns the snapshot — every AC contract
        # key MUST be present, even ones we never set from CSV.
        for key in ("last_scrape_ts", "last_scrape_per_source",
                    "minutes_since_scrape", "status",
                    "active_listings", "active_per_source",
                    "deal_count", "deal_rate_pct", "has_data"):
            assert key in snap, f"missing key: {key}"
        # Dummy key still present (function does not strip unrecognised fields)
        assert snap["k"] == 1

    def test_file_mtime_drives_last_scrape_ts(self, csv_finder):
        mtime_dt = datetime.now(timezone.utc) - timedelta(minutes=42)
        _write_csv(csv_finder, [
            {"listing_id": "L1", "source": "kijiji", "price": 1500, "beds": 1,
             "pct_under": 10.0, "neighborhood": "X", "url": "https://k/1"},
        ], mtime=mtime_dt.timestamp())
        snap = app_module._compute_health_snapshot_from_csv({})
        expected_ts = mtime_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert snap["last_scrape_ts"] == expected_ts
        # minutes_since should be ~42 (within rounding)
        assert 40 <= snap["minutes_since_scrape"] <= 44
        # 42 minutes is in the "fresh" bucket (<90)
        assert snap["status"] == "fresh"

    def test_per_source_breakdown(self, csv_finder):
        mtime = datetime.now(timezone.utc).timestamp()
        _write_csv(csv_finder, [
            {"listing_id": "K1", "source": "kijiji", "price": 1500, "beds": 1,
             "pct_under": 5.0, "neighborhood": "X", "url": "https://k/1"},
            {"listing_id": "K2", "source": "kijiji", "price": 1500, "beds": 1,
             "pct_under": -5.0, "neighborhood": "X", "url": "https://k/2"},
            {"listing_id": "C1", "source": "craigslist", "price": 1500,
             "beds": 1, "pct_under": 20.0, "neighborhood": "Y",
             "url": "https://c/1"},
            {"listing_id": "F1", "source": "facebook", "price": 1500,
             "beds": 1, "pct_under": 50.0, "neighborhood": "Z",
             "url": "https://f/1"},  # unknown source -> excluded
        ], mtime=mtime)
        snap = app_module._compute_health_snapshot_from_csv({})
        assert snap["active_per_source"] == {"kijiji": 2, "craigslist": 1}
        assert snap["active_listings"] == 3  # facebook row excluded

    def test_deal_count_uses_pct_under_threshold(self, csv_finder):
        mtime = datetime.now(timezone.utc).timestamp()
        _write_csv(csv_finder, [
            # 2 deals (pct > 0)
            {"listing_id": "D1", "source": "kijiji", "price": 1500,
             "pct_under": 5.0, "neighborhood": "X", "url": ""},
            {"listing_id": "D2", "source": "kijiji", "price": 1500,
             "pct_under": 25.0, "neighborhood": "X", "url": ""},
            # 3 at-or-above market (not deals)
            {"listing_id": "N1", "source": "kijiji", "price": 1500,
             "pct_under": 0.0, "neighborhood": "X", "url": ""},
            {"listing_id": "N2", "source": "kijiji", "price": 1500,
             "pct_under": -10.0, "neighborhood": "X", "url": ""},
            # Blank pct_under (malformed) — should be tolerated as 0, not deals
            {"listing_id": "N3", "source": "kijiji", "price": 1500,
             "pct_under": "", "neighborhood": "X", "url": ""},
        ], mtime=mtime)
        snap = app_module._compute_health_snapshot_from_csv({})
        assert snap["active_listings"] == 5
        assert snap["deal_count"] == 2
        assert snap["deal_rate_pct"] == 40.0  # 2/5 = 40%

    def test_missing_csv_returns_zero_snapshot(self, monkeypatch, tmp_path):
        """No DB, no CSV → return snapshot at zeros (no exception)."""
        monkeypatch.setattr(app_module, "DEALS_CSV",
                            str(tmp_path / "no-such.csv"))
        monkeypatch.setattr(app_module, "DB_PATH",
                            str(tmp_path / "no-such.db"))
        snap = app_module._compute_health_snapshot_from_csv({})
        assert snap["has_data"] is False
        assert snap["active_listings"] == 0
        assert snap["deal_count"] == 0
        assert snap["status"] == "unknown"

    def test_zero_rows_csv_returns_zero_snapshot(self, csv_finder):
        """Empty-but-existent CSV: schema is there, no rows → has_data=False."""
        cols = ["listing_id", "source", "price", "beds", "pct_under",
                "neighborhood", "url"]
        with open(csv_finder, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=cols).writeheader()
        snap = app_module._compute_health_snapshot_from_csv({})
        assert snap["active_listings"] == 0
        assert snap["has_data"] is False
        # mtime IS set (file exists) so last_scrape_ts is populated
        assert snap["last_scrape_ts"] is not None

    def test_freshness_thresholds_applied(self, csv_finder):
        # mtime 5 hours ago → 'stale'
        old_mtime = datetime.now(timezone.utc).timestamp() - 5 * 3600
        _write_csv(csv_finder, [
            {"listing_id": "L1", "source": "kijiji", "price": 1500,
             "pct_under": 10.0, "neighborhood": "X", "url": ""},
        ], mtime=old_mtime)
        snap = app_module._compute_health_snapshot_from_csv({})
        assert snap["status"] == "stale"

    def test_pct_under_with_alternate_column_name(self, csv_finder):
        """find_deals.py emits 'pct_under_market' in some versions; both
        must be accepted."""
        mtime = datetime.now(timezone.utc).timestamp()
        # Manually write a CSV with the alternate column to confirm fallback
        path = csv_finder
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "listing_id", "source", "price", "beds",
                "pct_under_market",  # <-- alternate name
                "neighborhood", "url"])
            writer.writeheader()
            writer.writerow({
                "listing_id": "D1", "source": "kijiji", "price": 1500,
                "beds": 1, "pct_under_market": 12.0,
                "neighborhood": "X", "url": "https://k/1",
            })
        snap = app_module._compute_health_snapshot_from_csv({})
        assert snap["deal_count"] == 1


# ---------------------------------------------------------------------------
# _compute_health_snapshot() — orchestration tests
# ---------------------------------------------------------------------------

class TestComputeHealthSnapshotCsvFallback:
    """The top-level function should pick the right data source depending on
    what's actually available on disk."""

    def test_sqlite_missing_uses_csv(self, monkeypatch, tmp_path, csv_finder):
        """Cold-boot scenario: DB gone, CSV present → CSV fills the snapshot."""
        monkeypatch.setattr(app_module, "DB_PATH",
                            str(tmp_path / "no-such-db.sqlite"))
        mtime = (datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp()
        _write_csv(csv_finder, [
            {"listing_id": f"K{i}", "source": "kijiji", "price": 1500,
             "pct_under": 5.0, "neighborhood": "X",
             "url": f"https://k/{i}"}
            for i in range(5)
        ] + [
            {"listing_id": f"C{i}", "source": "craigslist", "price": 1500,
             "pct_under": 15.0, "neighborhood": "Y",
             "url": f"https://c/{i}"}
            for i in range(10)
        ], mtime=mtime)
        snap = app_module._compute_health_snapshot()
        assert snap["active_listings"] == 15
        assert snap["active_per_source"] == {"kijiji": 5, "craigslist": 10}
        assert snap["deal_count"] == 15  # all are deals in this fixture
        # status=fresh because mtime is 10 min ago
        assert snap["status"] == "fresh"
        assert snap["has_data"] is True

    def test_sqlite_empty_uses_csv(self, empty_sqlite_db, csv_finder):
        """Schema exists but listings/scrape_runs are empty → fall through
        to CSV path so the pill shows fresh data, not 'unknown'."""
        mtime = (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
        _write_csv(csv_finder, [
            {"listing_id": f"K{i}", "source": "kijiji", "price": 1500,
             "pct_under": 5.0, "neighborhood": "X",
             "url": f"https://k/{i}"}
            for i in range(3)
        ], mtime=mtime)
        snap = app_module._compute_health_snapshot()
        # SQLite path produced all zeros → CSV path took over
        assert snap["active_listings"] == 3
        assert snap["status"] == "fresh"

    def test_sqlite_populated_prefers_sqlite(self, monkeypatch, tmp_path, csv_finder):
        """When SQLite has data, it wins — CSV is a fallback, not a replacement."""
        db = str(tmp_path / "populated.db")
        monkeypatch.setattr(app_module, "DB_PATH", db)
        try:
            import persist
            monkeypatch.setattr(persist, "DB_PATH", db)
        except Exception:
            pass
        from persist import init_db
        init_db()
        # Seed SQLite with a scrape_runs row + a few listings
        conn = sqlite3.connect(db)
        try:
            conn.execute("INSERT INTO scrape_runs (source, run_ts, "
                         "listings_seen, listings_new, listings_inactive, "
                         "errors, duration_secs) VALUES (?, ?, 0, 0, 0, 0, 0)",
                         ("kijiji", "2026-07-09T14:00:00Z"))
            for i in range(7):
                conn.execute(
                    "INSERT INTO listings (listing_id, source, price, beds, "
                    "is_active, first_seen, last_seen, score, neighborhood, "
                    "url) VALUES (?, 'Kijiji', 1500, 1, 1, "
                    "'2026-07-09T10:00:00Z', '2026-07-09T10:00:00Z', 0.5, "
                    "?, ?)",
                    (f"L{i}", "X", f"https://k/{i}"))
            conn.commit()
        finally:
            conn.close()
        # CSV path data is also there but should NOT take over
        _write_csv(csv_finder, [
            {"listing_id": "C1", "source": "kijiji", "price": 1500,
             "pct_under": 5.0, "neighborhood": "X", "url": "https://k/c1"},
        ])
        snap = app_module._compute_health_snapshot()
        assert snap["active_listings"] == 7  # SQLite value, not 1
        assert snap["last_scrape_ts"] == "2026-07-09T14:00:00Z"


# ---------------------------------------------------------------------------
# Live Flask /api/health tests — exercise the wiring end-to-end
# ---------------------------------------------------------------------------

class TestApiHealthCsvFallback:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path, csv_finder):
        # No SQLite at all — pure cold-boot case
        monkeypatch.setattr(app_module, "DB_PATH",
                            str(tmp_path / "no-db.sqlite"))
        # Warm the app with a fresh dataset
        mtime = (datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp()
        _write_csv(csv_finder, [
            {"listing_id": f"L{i}", "source": "kijiji" if i % 2 == 0 else "craigslist",
             "price": 1500 + i * 100, "pct_under": 5.0 if i < 5 else -2.0,
             "neighborhood": "X", "url": f"https://x/{i}"}
            for i in range(8)
        ], mtime=mtime)
        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as c:
            yield c

    def test_endpoint_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_endpoint_payload_shape(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        for key in ("last_scrape_ts", "last_scrape_per_source",
                    "minutes_since_scrape", "status", "active_listings",
                    "active_per_source", "deal_count", "deal_rate_pct",
                    "has_data"):
            assert key in data, f"missing key: {key}"

    def test_endpoint_populates_from_csv_when_no_db(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        # 4 kijiji + 4 craigslist in fixture
        assert data["active_per_source"]["kijiji"] == 4
        assert data["active_per_source"]["craigslist"] == 4
        assert data["active_listings"] == 8
        # 5 with pct_under > 0 → 5 deals
        assert data["deal_count"] == 5
        assert data["deal_rate_pct"] == 62.5  # 5/8
        # status=fresh (10 min mtime)
        assert data["status"] == "fresh"
        assert data["has_data"] is True


# ---------------------------------------------------------------------------
# Regression guard — AC7: smoke test that catches "scrape_runs empty forever"
# ---------------------------------------------------------------------------

class TestRegressionGuard:
    """Defends against AC #7: a smoke test that asserts the pill won't show
    'unknown' indefinitely when `deals_output.csv` is present.

    If both SQLite and CSV paths fail (e.g. someone deletes deals_output.csv
    AND wipes SQLite), the snapshot should still return a clean dict (no 500).
    """

    def test_no_data_no_500(self, monkeypatch, tmp_path):
        """The snapshot endpoint must NEVER 500 — gracefully degrade."""
        monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "nope.db"))
        monkeypatch.setattr(app_module, "DEALS_CSV",
                            str(tmp_path / "nope.csv"))
        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as c:
            resp = c.get("/api/health")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["has_data"] is False
            assert data["status"] == "unknown"
            assert data["active_listings"] == 0

    def test_csv_only_within_4_hours_is_fresh_or_aging(self, monkeypatch,
                                                       tmp_path, csv_finder):
        """AC7 spirit: if the only data source is the CSV, mtime older
        than 4 hours should not be classified 'fresh' — surface staleness.
        """
        # Force SQLite-empty path so CSV fallback drives the snapshot.
        monkeypatch.setattr(app_module, "DB_PATH",
                            str(tmp_path / "no-db.sqlite"))
        # mtime = 60 min ago → 'fresh'
        mtime = (datetime.now(timezone.utc) -
                 timedelta(minutes=60)).timestamp()
        _write_csv(csv_finder, [
            {"listing_id": "L1", "source": "kijiji", "price": 1500,
             "pct_under": 5.0, "neighborhood": "X", "url": ""},
        ], mtime=mtime)
        snap = app_module._compute_health_snapshot()
        assert snap["status"] in ("fresh", "aging")
        assert snap["minutes_since_scrape"] >= 55
        assert snap["minutes_since_scrape"] <= 75  # allow 15s runtime drift

    def test_csv_old_is_stale_not_silent(self, monkeypatch, tmp_path,
                                         csv_finder):
        """mtime 5 hours ago → 'stale'. UI pill turns red. No silent 'fresh'."""
        monkeypatch.setattr(app_module, "DB_PATH",
                            str(tmp_path / "no-db.sqlite"))
        # Backdate the CSV file to 5 hours ago
        old_mtime = (datetime.now(timezone.utc) -
                     timedelta(hours=5)).timestamp()
        _write_csv(csv_finder, [
            {"listing_id": "L1", "source": "kijiji", "price": 1500,
             "pct_under": 5.0, "neighborhood": "X", "url": ""},
        ], mtime=old_mtime)
        snap = app_module._compute_health_snapshot()
        assert snap["status"] == "stale"
        assert snap["last_scrape_ts"] is not None
