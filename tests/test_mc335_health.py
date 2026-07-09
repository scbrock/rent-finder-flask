"""
MC-335: Live data-freshness pill in web app header.

Covers:
  - _parse_iso_utc() handles both timestamp formats we emit
  - _classify_freshness() buckets minutes-since into the right status
  - _compute_health_snapshot() returns the contract shape:
      {last_scrape_ts, last_scrape_per_source, minutes_since_scrape, status,
       active_listings, active_per_source, deal_count, deal_rate_pct, has_data}
  - /api/health endpoint returns 200 + the same shape
  - Empty / missing DB gracefully returns zeros + status='unknown' (no 500)
  - Status classification uses the AC's thresholds (90/180 min)
  - active_per_source counts both kijiji and craigslist separately
  - deal_rate_pct is rounded to 1 decimal place
  - index.html wiring:
      - #health_pill element present with data-freshness attribute
      - /api/health referenced in JS
      - loadHealthPill() exists and is called at init
      - color-coded CSS states for fresh/aging/stale/unknown
      - 60s refresh interval present
"""
import os
import sys
import sqlite3
import re
from datetime import datetime, timezone, timedelta

import pytest

# Ensure rent_finder is importable
RENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RENT_DIR)

import app as app_module  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_scrape_runs(db_path: str, rows: list[tuple[str, str]]) -> None:
    """Insert raw scrape_runs rows. Args: (source, run_ts)."""
    conn = sqlite3.connect(db_path)
    try:
        for source, run_ts in rows:
            conn.execute(
                "INSERT INTO scrape_runs (source, run_ts, listings_seen, "
                "listings_new, listings_inactive, errors, duration_secs) "
                "VALUES (?, ?, 0, 0, 0, 0, 0)",
                (source, run_ts),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_listings(db_path: str, rows: list[dict]) -> None:
    """Insert raw listings rows."""
    conn = sqlite3.connect(db_path)
    try:
        for row in rows:
            cols = sorted(row.keys())
            placeholders = ",".join("?" * len(cols))
            sql = f"INSERT OR REPLACE INTO listings ({','.join(cols)}) VALUES ({placeholders})"
            conn.execute(sql, [row[c] for c in cols])
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def sqlite_db(monkeypatch, tmp_path):
    """Point app_module.DB_PATH at a fresh temp DB and init the schema.

    Also points DEALS_CSV at a non-existent path so the MC-336 CSV fallback
    (added in MC-336) doesn't accidentally read the real deals_output.csv
    and mask the "empty SQLite → unknown" assertion.
    """
    db = str(tmp_path / "test_listings.db")
    monkeypatch.setattr(app_module, "DB_PATH", db)
    monkeypatch.setattr(app_module, "DEALS_CSV", str(tmp_path / "no-csv.csv"))
    # Also clear any cached persist module DB path so init_db() uses ours
    try:
        import persist
        monkeypatch.setattr(persist, "DB_PATH", db)
    except Exception:
        pass
    # Bootstrap schema via persist.init_db() — _get_conn() caches the path
    try:
        from persist import init_db
        init_db()
    except Exception:
        pass
    yield db


# ---------------------------------------------------------------------------
# _parse_iso_utc tests
# ---------------------------------------------------------------------------

class TestParseIsoUtc:
    def test_parses_seconds_format(self):
        out = app_module._parse_iso_utc("2026-07-09T14:30:00Z")
        assert out.year == 2026 and out.month == 7 and out.day == 9
        assert out.hour == 14 and out.minute == 30 and out.second == 0
        assert out.tzinfo is not None

    def test_parses_microseconds_format(self):
        out = app_module._parse_iso_utc("2026-07-09T14:30:00.123456Z")
        assert out.year == 2026 and out.hour == 14

    def test_empty_string_returns_far_future(self):
        out = app_module._parse_iso_utc("")
        assert out == datetime.max.replace(tzinfo=timezone.utc)

    def test_none_returns_far_future(self):
        out = app_module._parse_iso_utc(None)
        assert out == datetime.max.replace(tzinfo=timezone.utc)

    def test_malformed_returns_far_future(self):
        out = app_module._parse_iso_utc("not a timestamp")
        assert out == datetime.max.replace(tzinfo=timezone.utc)

    def test_compares_correctly(self):
        a = app_module._parse_iso_utc("2026-07-09T14:30:00Z")
        b = app_module._parse_iso_utc("2026-07-09T15:30:00Z")
        assert a < b


# ---------------------------------------------------------------------------
# _classify_freshness tests
# ---------------------------------------------------------------------------

class TestClassifyFreshness:
    def test_fresh_under_90(self):
        assert app_module._classify_freshness(0) == "fresh"
        assert app_module._classify_freshness(45) == "fresh"
        assert app_module._classify_freshness(89.9) == "fresh"

    def test_aging_90_to_180(self):
        assert app_module._classify_freshness(90) == "aging"
        assert app_module._classify_freshness(120) == "aging"
        assert app_module._classify_freshness(180) == "aging"

    def test_stale_over_180(self):
        assert app_module._classify_freshness(180.1) == "stale"
        assert app_module._classify_freshness(500) == "stale"
        assert app_module._classify_freshness(10000) == "stale"

    def test_unknown_for_none_or_negative(self):
        assert app_module._classify_freshness(None) == "unknown"
        assert app_module._classify_freshness(-1) == "unknown"


# ---------------------------------------------------------------------------
# _compute_health_snapshot tests
# ---------------------------------------------------------------------------

class TestComputeHealthSnapshot:
    """_compute_health_snapshot reads from SQLite + computes aggregate stats."""

    def test_returns_expected_keys(self, sqlite_db):
        snap = app_module._compute_health_snapshot()
        expected = {
            "last_scrape_ts", "last_scrape_per_source", "minutes_since_scrape",
            "status", "active_listings", "active_per_source",
            "deal_count", "deal_rate_pct", "has_data",
        }
        assert set(snap.keys()) == expected, f"missing keys: {expected - set(snap.keys())}"

    def test_empty_db_returns_zeros_and_unknown(self, sqlite_db):
        snap = app_module._compute_health_snapshot()
        assert snap["last_scrape_ts"] is None
        assert snap["minutes_since_scrape"] is None
        assert snap["status"] == "unknown"
        assert snap["active_listings"] == 0
        assert snap["deal_count"] == 0
        assert snap["deal_rate_pct"] == 0.0
        assert snap["has_data"] is False
        # Per-source maps still present
        assert snap["last_scrape_per_source"] == {"kijiji": None, "craigslist": None}
        assert snap["active_per_source"] == {"kijiji": 0, "craigslist": 0}

    def test_missing_db_file_returns_zeros(self, monkeypatch, tmp_path):
        """If the DB doesn't exist (cold boot), return the zero shape (not 500).

        Also stub DEALS_CSV so the MC-336 CSV fallback doesn't accidentally
        read the real deals_output.csv and report has_data=True.
        """
        monkeypatch.setattr(app_module, "DB_PATH",
                            str(tmp_path / "no-such-db.sqlite"))
        monkeypatch.setattr(app_module, "DEALS_CSV",
                            str(tmp_path / "no-such-csv.csv"))
        snap = app_module._compute_health_snapshot()
        assert snap["has_data"] is False
        assert snap["active_listings"] == 0
        assert snap["deal_count"] == 0

    def test_recent_scrape_is_fresh(self, sqlite_db):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed_scrape_runs(sqlite_db, [("kijiji", recent)])
        snap = app_module._compute_health_snapshot()
        assert snap["last_scrape_ts"] == recent
        assert snap["last_scrape_per_source"]["kijiji"] == recent
        assert snap["status"] == "fresh"
        # 10 min → 9.7-10.3 range
        assert snap["minutes_since_scrape"] is not None
        assert 8 <= snap["minutes_since_scrape"] <= 12

    def test_old_scrape_is_stale(self, sqlite_db):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed_scrape_runs(sqlite_db, [("kijiji", old)])
        snap = app_module._compute_health_snapshot()
        assert snap["status"] == "stale"
        assert snap["minutes_since_scrape"] >= 295

    def test_per_source_breakdown(self, sqlite_db):
        now = datetime.now(timezone.utc)
        ki = (now - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cl = (now - timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed_scrape_runs(sqlite_db, [("kijiji", ki), ("craigslist", cl)])
        snap = app_module._compute_health_snapshot()
        assert snap["last_scrape_per_source"]["kijiji"] == ki
        assert snap["last_scrape_per_source"]["craigslist"] == cl
        # Overall = max(ki, cl) = ki (15 min ago < 90 min ago)
        assert snap["last_scrape_ts"] == ki

    def test_active_listings_count(self, sqlite_db):
        rows = [
            {"listing_id": f"L{i}", "source": "Kijiji", "price": 1500, "beds": 1,
             "is_active": 1, "first_seen": "2026-07-09T10:00:00Z",
             "last_seen": "2026-07-09T10:00:00Z", "score": 0.0,
             "neighborhood": "X", "url": f"https://k/{i}"}
            for i in range(3)
        ] + [
            {"listing_id": f"C{i}", "source": "Craigslist", "price": 1500, "beds": 1,
             "is_active": 1, "first_seen": "2026-07-09T10:00:00Z",
             "last_seen": "2026-07-09T10:00:00Z", "score": 0.0,
             "neighborhood": "Y", "url": f"https://c/{i}"}
            for i in range(2)
        ] + [
            # Inactive — should NOT be counted
            {"listing_id": "INACTIVE1", "source": "Kijiji", "price": 1500, "beds": 1,
             "is_active": 0, "first_seen": "2026-06-01T10:00:00Z",
             "last_seen": "2026-06-01T10:00:00Z", "score": 0.0,
             "neighborhood": "Z", "url": "https://k/old"}
        ]
        _seed_listings(sqlite_db, rows)
        snap = app_module._compute_health_snapshot()
        assert snap["active_listings"] == 5
        assert snap["active_per_source"] == {"kijiji": 3, "craigslist": 2}
        assert snap["has_data"] is True

    def test_deal_rate_calculation(self, sqlite_db):
        rows = []
        # 3 deals (score > 0) + 7 non-deals (score 0) = 30% deal rate
        for i in range(3):
            rows.append({"listing_id": f"D{i}", "source": "Kijiji", "price": 1500,
                         "beds": 1, "is_active": 1,
                         "first_seen": "2026-07-09T10:00:00Z",
                         "last_seen": "2026-07-09T10:00:00Z", "score": 0.5,
                         "neighborhood": "X", "url": f"https://k/{i}"})
        for i in range(7):
            rows.append({"listing_id": f"N{i}", "source": "Kijiji", "price": 1500,
                         "beds": 1, "is_active": 1,
                         "first_seen": "2026-07-09T10:00:00Z",
                         "last_seen": "2026-07-09T10:00:00Z", "score": 0.0,
                         "neighborhood": "X", "url": f"https://k/n{i}"})
        _seed_listings(sqlite_db, rows)
        snap = app_module._compute_health_snapshot()
        assert snap["deal_count"] == 3
        assert snap["deal_rate_pct"] == 30.0

    def test_deal_count_excludes_zero_scores(self, sqlite_db):
        """Listings with score=0 (at-market) should not count as deals."""
        rows = [
            {"listing_id": "D1", "source": "Kijiji", "price": 1500, "beds": 1,
             "is_active": 1, "first_seen": "2026-07-09T10:00:00Z",
             "last_seen": "2026-07-09T10:00:00Z", "score": 0.5,
             "neighborhood": "X", "url": "https://k/d1"},
            {"listing_id": "N1", "source": "Kijiji", "price": 1500, "beds": 1,
             "is_active": 1, "first_seen": "2026-07-09T10:00:00Z",
             "last_seen": "2026-07-09T10:00:00Z", "score": 0.0,
             "neighborhood": "X", "url": "https://k/n1"},
        ]
        _seed_listings(sqlite_db, rows)
        snap = app_module._compute_health_snapshot()
        assert snap["deal_count"] == 1
        assert snap["active_listings"] == 2
        assert snap["deal_rate_pct"] == 50.0

    def test_deal_rate_rounded_to_1dp(self, sqlite_db):
        """1 deal out of 3 active = 33.333...% should round to 33.3."""
        rows = []
        for i in range(1):
            rows.append({"listing_id": f"D{i}", "source": "Kijiji", "price": 1500,
                         "beds": 1, "is_active": 1,
                         "first_seen": "2026-07-09T10:00:00Z",
                         "last_seen": "2026-07-09T10:00:00Z", "score": 0.5,
                         "neighborhood": "X", "url": f"https://k/d{i}"})
        for i in range(2):
            rows.append({"listing_id": f"N{i}", "source": "Kijiji", "price": 1500,
                         "beds": 1, "is_active": 1,
                         "first_seen": "2026-07-09T10:00:00Z",
                         "last_seen": "2026-07-09T10:00:00Z", "score": 0.0,
                         "neighborhood": "X", "url": f"https://k/n{i}"})
        _seed_listings(sqlite_db, rows)
        snap = app_module._compute_health_snapshot()
        assert snap["deal_rate_pct"] == 33.3  # rounded to 1dp


# ---------------------------------------------------------------------------
# /api/health endpoint tests
# ---------------------------------------------------------------------------

class TestApiHealthEndpoint:
    @pytest.fixture
    def client(self, sqlite_db):
        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as c:
            yield c

    def test_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_returns_json_object(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_shape_matches_contract(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        for key in ("last_scrape_ts", "last_scrape_per_source",
                    "minutes_since_scrape", "status", "active_listings",
                    "active_per_source", "deal_count", "deal_rate_pct",
                    "has_data"):
            assert key in data, f"missing key: {key}"

    def test_empty_db_responds_cleanly(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["status"] in ("unknown", "fresh", "aging", "stale")
        assert data["active_listings"] == 0
        assert data["deal_count"] == 0


# ---------------------------------------------------------------------------
# HTML wiring tests
# ---------------------------------------------------------------------------

INDEX_HTML_PATH = os.path.join(RENT_DIR, "templates", "index.html")


class TestIndexHtmlWiring:
    @pytest.fixture
    def html(self):
        with open(INDEX_HTML_PATH, encoding="utf-8") as f:
            return f.read()

    def test_health_pill_element_present(self, html):
        assert 'id="health_pill"' in html
        assert "data-freshness" in html

    def test_health_pill_dot_present(self, html):
        assert 'id="health_dot"' in html
        assert 'id="health_text"' in html
        assert 'id="health_meta"' in html

    def test_api_health_referenced_in_js(self, html):
        assert "/api/health" in html

    def test_loadHealthPill_function_exists(self, html):
        assert "function loadHealthPill()" in html
        assert "loadHealthPill();" in html

    def test_renderHealthPill_function_exists(self, html):
        assert "function renderHealthPill(" in html

    def test_refresh_interval_present(self, html):
        # 60-second polling (setInterval's second arg is milliseconds)
        m = re.search(r"setInterval\(loadHealthPill,\s*(\d+)\)", html)
        assert m is not None, "setInterval(loadHealthPill, N) not found"
        ms = int(m.group(1))
        # 60s = 60000ms; assert at least 10s and at most 120s in millis
        assert 10_000 <= ms <= 120_000, (
            f"refresh interval out of range: {ms}ms "
            f"(expected 10s-120s)")
        secs = ms / 1000.0
        assert 10 <= secs <= 120, f"refresh interval out of range: {secs}s"

    def test_color_states_in_css(self, html):
        for status in ("fresh", "aging", "stale", "unknown"):
            assert f'data-freshness="{status}"' in html

    def test_fmtMinutesAgo_helper_present(self, html):
        assert "function fmtMinutesAgo(" in html

    def test_click_to_scroll_handler(self, html):
        # Clicking the pill should scroll to top
        assert 'window.scrollTo' in html
        assert 'onclick=' in html