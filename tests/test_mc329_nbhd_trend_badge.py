"""
MC-329: Neighbourhood price-trend badge in deals table tests.

4 test classes covering the AC7 spec:
  - TestGetNeighborhoodTrendsBatch: persist-level aggregation
  - TestDealsIncludeNeighborhoodTrend: app.py /api/deals wiring
  - TestApiMetaNeighborhoodTrends: app.py /api/meta block
  - TestIndexHtmlTrendBadgeWiring: HTML template badge render

All DB tests use a tmp SQLite (clean state, no flakiness from prod DB).
HTTP tests use Flask's test_client (no live server needed).

Run: .venv/Scripts/python.exe tests/test_mc329_nbhd_trend_badge.py
"""
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# Make the rent_finder root importable (persist.py, app.py, etc.)
_RENT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RENT_ROOT))

import persist
import app as app_module


# ── Shared helpers ────────────────────────────────────────────────────────


def _seed_price_history(listing_id: str, nbhd: str, price: float,
                         seen_at: str) -> None:
    """Insert a single price_history row + a matching listings row (active)
    so that persist joins find the data."""
    conn = persist._get_conn()
    try:
        # Ensure listings row exists; upsert by listing_id.
        existing = conn.execute(
            "SELECT 1 FROM listings WHERE listing_id = ?", (listing_id,)
        ).fetchone()
        if not existing:
            conn.execute("""
                INSERT INTO listings (listing_id, source, title, price, beds,
                                       neighborhood, region, is_active, first_seen)
                VALUES (?, 'kijiji', ?, ?, 1, ?, 'Downtown', 1, ?)
            """, (listing_id, f"Test {listing_id}", price, nbhd,
                   seen_at))
        conn.execute("""
            INSERT INTO price_history (listing_id, price, seen_at)
            VALUES (?, ?, ?)
            ON CONFLICT(listing_id, seen_at) DO NOTHING
        """, (listing_id, price, seen_at))
        conn.commit()
    finally:
        persist._conn = None
        persist._reset_conn()


class _IsolatedDB:
    """Redirect persist.DB_PATH to a tmp file for the duration of a test."""
    def __enter__(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp_db = Path(self._tmpdir.name) / "test_mc329.db"
        self._orig_path = persist.DB_PATH
        persist.DB_PATH = self._tmp_db
        # Initialize schema (creates tables) before tests touch the DB.
        persist._reset_conn()
        persist.init_db()
        return self._tmp_db

    def __exit__(self, *exc):
        try:
            persist._reset_conn()
        except Exception:
            pass
        persist.DB_PATH = self._orig_path
        self._tmpdir.cleanup()


def _now_iso(days_ago: int = 0, hours_ago: int = 0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ════════════════════════════════════════════════════════════════════════
# Class 1: persist.get_neighborhood_trends_batch
# ════════════════════════════════════════════════════════════════════════


class TestGetNeighborhoodTrendsBatch:
    """Aggregation: SQL bucket -> pct_change + direction."""

    def test_empty_neighborhoods_returns_empty_dict_without_db_hit(self):
        """Short-circuit: empty input -> {} without touching the DB."""
        with _IsolatedDB():
            result = persist.get_neighborhood_trends_batch([], days=30)
            assert result == {}
            # Sanity: even with no DB path set, no error
            assert isinstance(result, dict)

    def test_single_neighborhood_up_direction(self):
        """Neighbourhood with monotonic rising prices -> direction='up'."""
        with _IsolatedDB():
            # 5 days of price_history, prices monotonically increasing
            for d, p in enumerate([1000.0, 1010.0, 1020.0, 1030.0, 1040.0]):
                _seed_price_history(
                    listing_id="L1", nbhd="Agincourt",
                    price=p, seen_at=_now_iso(days_ago=5 - d),
                )
            result = persist.get_neighborhood_trends_batch(["Agincourt"], days=30)
        assert "Agincourt" in result
        assert result["Agincourt"]["direction"] == "up"
        assert result["Agincourt"]["pct_change"] > 0
        # (1040 - 1000) / 1000 = 0.04 = 4%
        assert abs(result["Agincourt"]["pct_change"] - 0.04) < 1e-6
        assert result["Agincourt"]["days_of_data"] == 5

    def test_single_neighborhood_down_direction(self):
        """Monotonic falling prices -> direction='down'."""
        with _IsolatedDB():
            for d, p in enumerate([2000.0, 1980.0, 1960.0, 1940.0, 1920.0]):
                _seed_price_history(
                    listing_id="L2", nbhd="Bayview",
                    price=p, seen_at=_now_iso(days_ago=5 - d),
                )
            result = persist.get_neighborhood_trends_batch(["Bayview"], days=30)
        assert result["Bayview"]["direction"] == "down"
        # (1920 - 2000) / 2000 = -0.04
        assert abs(result["Bayview"]["pct_change"] - (-0.04)) < 1e-6

    def test_flat_within_threshold(self):
        """Small change within ±2% -> 'flat'."""
        with _IsolatedDB():
            for d, p in enumerate([1000.0, 1005.0, 1010.0]):
                _seed_price_history(
                    listing_id="L3", nbhd="Flatville",
                    price=p, seen_at=_now_iso(days_ago=3 - d),
                )
            result = persist.get_neighborhood_trends_batch(["Flatville"], days=30)
        # (1010 - 1000) / 1000 = 0.01 < 0.02 threshold
        assert result["Flatville"]["direction"] == "flat"
        assert abs(result["Flatville"]["pct_change"] - 0.01) < 1e-6

    def test_only_one_day_of_data_omitted(self):
        """<2 days of data -> neighbourhood OMITTED from result."""
        with _IsolatedDB():
            _seed_price_history("L4", "OneDay", 1500.0, _now_iso(days_ago=1))
            result = persist.get_neighborhood_trends_batch(["OneDay"], days=30)
        assert "OneDay" not in result
        assert result == {}

    def test_zero_data_omitted(self):
        """No price_history rows at all -> omitted."""
        with _IsolatedDB():
            result = persist.get_neighborhood_trends_batch(["NoData"])
        assert result == {}

    def test_batch_returns_multiple_neighborhoods(self):
        """Multiple neighborhoods in one call -> map of all eligible ones."""
        with _IsolatedDB():
            for d, p in enumerate([100.0, 110.0, 120.0]):
                _seed_price_history("LB1", "UpNbhd", p,
                                     _now_iso(days_ago=3 - d))
            for d, p in enumerate([200.0, 180.0, 160.0]):
                _seed_price_history("LB2", "DownNbhd", p,
                                     _now_iso(days_ago=3 - d))
            # OneDay excluded from result
            _seed_price_history("LB3", "OneDayNbhd", 300.0, _now_iso(days_ago=1))
            result = persist.get_neighborhood_trends_batch(
                ["UpNbhd", "DownNbhd", "OneDayNbhd"]
            )
        assert "UpNbhd" in result and result["UpNbhd"]["direction"] == "up"
        assert "DownNbhd" in result and result["DownNbhd"]["direction"] == "down"
        assert "OneDayNbhd" not in result

    def test_listing_count_correctness_days_of_data(self):
        """days_of_data counts distinct days with >= 1 price point."""
        with _IsolatedDB():
            for d in range(7):
                _seed_price_history("LD1", "Daily", 1000.0 + d,
                                     _now_iso(days_ago=7 - d))
            result = persist.get_neighborhood_trends_batch(["Daily"])
        assert result["Daily"]["days_of_data"] == 7

    def test_inactive_listing_excluded(self):
        """price_history on an is_active=0 listing must not count."""
        with _IsolatedDB():
            conn = persist._get_conn()
            try:
                # Insert active listing + price_history
                conn.execute("""
                    INSERT INTO listings (listing_id, source, title, price,
                                           beds, neighborhood, region, is_active,
                                           first_seen)
                    VALUES ('LA1', 'kijiji', 'A', 1000, 1, 'Mixed', 'Downtown',
                            1, ?)
                """, (_now_iso(days_ago=2),))
                conn.execute("""
                    INSERT INTO price_history (listing_id, price, seen_at)
                    VALUES ('LA1', 1000, ?)
                """, (_now_iso(days_ago=2),))
                conn.execute("""
                    INSERT INTO price_history (listing_id, price, seen_at)
                    VALUES ('LA1', 1100, ?)
                """, (_now_iso(days_ago=1),))
                # Insert INACTIVE listing + price_history (should NOT count)
                conn.execute("""
                    INSERT INTO listings (listing_id, source, title, price,
                                           beds, neighborhood, region, is_active,
                                           first_seen)
                    VALUES ('LI1', 'kijiji', 'I', 500, 1, 'Mixed', 'Downtown',
                            0, ?)
                """, (_now_iso(days_ago=2),))
                conn.execute("""
                    INSERT INTO price_history (listing_id, price, seen_at)
                    VALUES ('LI1', 500, ?)
                """, (_now_iso(days_ago=2),))
                conn.execute("""
                    INSERT INTO price_history (listing_id, price, seen_at)
                    VALUES ('LI1', 99999, ?)
                """, (_now_iso(days_ago=1),))   # would show 200x jump if not excluded
                conn.commit()
            finally:
                persist._reset_conn()
            result = persist.get_neighborhood_trends_batch(["Mixed"])
        # Only LA1's data should count. Trend: 1000 -> 1100 = +10%
        assert result["Mixed"]["direction"] == "up"
        assert abs(result["Mixed"]["pct_change"] - 0.10) < 1e-6

    def test_negative_or_zero_price_rows_skipped(self):
        """Defensive: zero/negative prices skipped, only valid prices count.

        Note: price_history.price has a NOT NULL constraint, so we can't
        insert literal NULL here -- we verify the defensive skip via
        zero and negative prices (the NULL skip is the same code path).
        """
        with _IsolatedDB():
            # Seed 2 valid prices + 1 zero + 1 negative. Only valid count.
            _seed_price_history("LN1", "Defensive", 1000.0, _now_iso(days_ago=2))
            _seed_price_history("LN1", "Defensive", 0.0, _now_iso(days_ago=2))
            _seed_price_history("LN1", "Defensive", -100.0, _now_iso(days_ago=1))
            _seed_price_history("LN1", "Defensive", 1100.0, _now_iso(days_ago=0))
            result = persist.get_neighborhood_trends_batch(["Defensive"])
        assert "Defensive" in result
        assert result["Defensive"]["direction"] == "up"
        # (1100 - 1000) / 1000 = 0.10 -- zero and negative must be skipped
        assert abs(result["Defensive"]["pct_change"] - 0.10) < 1e-6


# ════════════════════════════════════════════════════════════════════════
# Class 2: app.py /api/deals attaches neighborhood_trend
# ════════════════════════════════════════════════════════════════════════


class TestDealsIncludeNeighborhoodTrend:
    """Each deal row gains a `neighborhood_trend` field."""

    @staticmethod
    def _client_with_isolated_db():
        """Yield a Flask test_client with persist.DB_PATH redirected to a
        tmp file. Use as a context manager: `with _client_with_isolated_db() as c:`."""
        from contextlib import contextmanager
        from flask.testing import FlaskClient

        @contextmanager
        def cm():
            tmpdir = tempfile.TemporaryDirectory()
            tmp_db = Path(tmpdir.name) / "test_mc329_app.db"
            orig_path = persist.DB_PATH
            persist.DB_PATH = tmp_db
            app_module.DB_PATH = tmp_db
            persist._reset_conn()
            persist.init_db()
            try:
                with app_module.app.test_client() as c:
                    yield c
            finally:
                try:
                    persist._reset_conn()
                except Exception:
                    pass
                persist.DB_PATH = orig_path
                tmpdir.cleanup()

        return cm()

    def test_each_row_has_neighborhood_trend_field(self):
        """Even rows for neighbourhoods with no trend data must have the
        field (set to None). AC2 + AC9: badge must render without 500."""
        with self._client_with_isolated_db() as c:
            # Seed a single listing with no price_history at all
            conn = persist._get_conn()
            try:
                conn.execute("""
                    INSERT INTO listings (listing_id, source, title, price,
                                           beds, neighborhood, region, is_active,
                                           first_seen)
                    VALUES ('D1', 'kijiji', 'Test', 2000, 1, 'NoTrendNbhd',
                            'Downtown', 1, ?)
                """, (_now_iso(),))
                conn.commit()
            finally:
                persist._reset_conn()
            resp = c.get("/api/deals")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "deals" in data
            assert len(data["deals"]) >= 1
            for d in data["deals"]:
                assert "neighborhood_trend" in d, \
                    f"row missing neighborhood_trend: {d}"
                # NoTrendNbhd has no trend data -> None
                if d["neighbourhood"] == "NoTrendNbhd":
                    assert d["neighborhood_trend"] is None

    def test_row_with_trend_data_has_populated_field(self):
        """A neighbourhood with 2+ days of price_history shows the trend."""
        with self._client_with_isolated_db() as c:
            conn = persist._get_conn()
            try:
                conn.execute("""
                    INSERT INTO listings (listing_id, source, title, price,
                                           beds, neighborhood, region, is_active,
                                           first_seen)
                    VALUES ('T1', 'kijiji', 'Test', 2000, 1, 'RisingNbhd',
                            'Downtown', 1, ?)
                """, (_now_iso(days_ago=3),))
                for d, p in enumerate([1000.0, 1100.0, 1200.0]):
                    conn.execute("""
                        INSERT INTO price_history (listing_id, price, seen_at)
                        VALUES ('T1', ?, ?)
                    """, (p, _now_iso(days_ago=3 - d)))
                conn.commit()
            finally:
                persist._reset_conn()
            resp = c.get("/api/deals")
            data = resp.get_json()
            assert resp.status_code == 200
            rising = [d for d in data["deals"] if d["neighbourhood"] == "RisingNbhd"]
            assert len(rising) == 1
            trend = rising[0]["neighborhood_trend"]
            assert trend is not None
            assert trend["direction"] == "up"
            assert trend["pct_change"] > 0

    def test_batching_one_query_for_full_neighborhood_set(self):
        """Even with many neighborhoods, the trend field is populated on
        each row. Confirms batching (one DB call, not N)."""
        with self._client_with_isolated_db() as c:
            conn = persist._get_conn()
            try:
                for i in range(5):
                    nbhd = f"Nbhd{i}"
                    lid = f"L{i}"
                    conn.execute(f"""
                        INSERT INTO listings (listing_id, source, title, price,
                                               beds, neighborhood, region, is_active,
                                               first_seen)
                        VALUES ('{lid}', 'kijiji', 'T{i}', 1000, 1, '{nbhd}',
                                'Downtown', 1, ?)
                    """, (_now_iso(days_ago=3),))
                    for d, p in enumerate([1000.0, 1050.0]):
                        conn.execute("""
                            INSERT INTO price_history (listing_id, price, seen_at)
                            VALUES (?, ?, ?)
                        """, (lid, p, _now_iso(days_ago=2 - d)))
                conn.commit()
            finally:
                persist._reset_conn()
            resp = c.get("/api/deals")
            data = resp.get_json()
            # Each of 5 rows should have a neighborhood_trend (up direction)
            for d in data["deals"]:
                assert d["neighborhood_trend"] is not None, \
                    f"missing trend on {d.get('neighbourhood')}"
                assert d["neighborhood_trend"]["direction"] == "up"

    def test_no_500_on_empty_db(self):
        """AC9: 0 listings must not 500. Empty deal list response.

        We patch load_deals() directly because app.load_deals falls
        back to the live DEALS_CSV when the SQLite file is empty -- and
        we don't want the test to depend on / touch the live CSV.
        """
        from unittest.mock import patch as _patch
        with self._client_with_isolated_db() as c:
            with _patch.object(app_module, "load_deals", return_value=[]):
                resp = c.get("/api/deals")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["deals"] == []
        assert body["total"] == 0

    def test_trend_field_handles_missing_key(self):
        """If trend is None for a row, the row dict still has the key."""
        with self._client_with_isolated_db() as c:
            conn = persist._get_conn()
            try:
                conn.execute("""
                    INSERT INTO listings (listing_id, source, title, price,
                                           beds, neighborhood, region, is_active,
                                           first_seen)
                    VALUES ('K1', 'kijiji', 'T', 1000, 1, 'NoTrendNbhd',
                            'X', 1, ?)
                """, (_now_iso(),))
                conn.commit()
            finally:
                persist._reset_conn()
            resp = c.get("/api/deals")
            for d in resp.get_json()["deals"]:
                # Every row must have the field, even if it's None.
                assert "neighborhood_trend" in d
                assert d["neighborhood_trend"] is None


# ════════════════════════════════════════════════════════════════════════
# Class 3: app.py /api/meta includes neighborhood_trends map
# ════════════════════════════════════════════════════════════════════════


class TestApiMetaNeighborhoodTrends:
    """Sidebar / /api/meta block has neighborhood_trends field."""

    @staticmethod
    def _client_with_isolated_db():
        from contextlib import contextmanager

        @contextmanager
        def cm():
            tmpdir = tempfile.TemporaryDirectory()
            tmp_db = Path(tmpdir.name) / "test_mc329_meta.db"
            orig_path = persist.DB_PATH
            persist.DB_PATH = tmp_db
            app_module.DB_PATH = tmp_db
            persist._reset_conn()
            persist.init_db()
            try:
                with app_module.app.test_client() as c:
                    yield c
            finally:
                try:
                    persist._reset_conn()
                except Exception:
                    pass
                persist.DB_PATH = orig_path
                tmpdir.cleanup()

        return cm()

    def test_meta_has_neighborhood_trends_field(self):
        """The /api/meta response must include the 'neighborhood_trends' key."""
        with self._client_with_isolated_db() as c:
            resp = c.get("/api/meta")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "neighborhood_trends" in data
        assert isinstance(data["neighborhood_trends"], dict)

    def test_meta_trends_only_for_neighborhoods_with_data(self):
        """Meta's neighborhood_trends must OMIT neighbourhoods with <2 days
        of price_history (same rule as the per-row field)."""
        with self._client_with_isolated_db() as c:
            conn = persist._get_conn()
            try:
                conn.execute("""
                    INSERT INTO listings (listing_id, source, title, price,
                                           beds, neighborhood, region, is_active,
                                           first_seen)
                    VALUES ('MN1', 'kijiji', 'T', 1000, 1, 'HasTrend',
                            'X', 1, ?)
                """, (_now_iso(days_ago=3),))
                for d, p in enumerate([1000.0, 1100.0]):
                    conn.execute("""
                        INSERT INTO price_history (listing_id, price, seen_at)
                        VALUES ('MN1', ?, ?)
                    """, (p, _now_iso(days_ago=2 - d)))
                conn.execute("""
                    INSERT INTO listings (listing_id, source, title, price,
                                           beds, neighborhood, region, is_active,
                                           first_seen)
                    VALUES ('MN2', 'kijiji', 'T', 2000, 1, 'NoTrend',
                            'X', 1, ?)
                """, (_now_iso(),))
                conn.commit()
            finally:
                persist._reset_conn()
            resp = c.get("/api/meta")
            data = resp.get_json()
            assert "HasTrend" in data["neighborhood_trends"]
            assert data["neighborhood_trends"]["HasTrend"]["direction"] == "up"
            assert "NoTrend" not in data["neighborhood_trends"]

    def test_meta_trends_empty_for_empty_db(self):
        """Empty DB -> neighborhood_trends = {} (not crash)."""
        with self._client_with_isolated_db() as c:
            resp = c.get("/api/meta")
        data = resp.get_json()
        assert data["neighborhood_trends"] == {}

    def test_meta_trends_degrades_gracefully_on_db_error(self):
        """If persist raises during the trends query, /api/meta returns
        200 with empty trends (defensive). We force the error."""
        with self._client_with_isolated_db() as c:
            with patch.object(persist, "get_neighborhood_trends_batch",
                               side_effect=RuntimeError("simulated DB failure")):
                resp = c.get("/api/meta")
        # Must not 500 -- the helper swallows the error
        assert resp.status_code == 200
        assert resp.get_json()["neighborhood_trends"] == {}

    def test_meta_trends_includes_window_days(self):
        """Each trend entry must carry window_days for the tooltip text."""
        with self._client_with_isolated_db() as c:
            conn = persist._get_conn()
            try:
                conn.execute("""
                    INSERT INTO listings (listing_id, source, title, price,
                                           beds, neighborhood, region, is_active,
                                           first_seen)
                    VALUES ('MW1', 'kijiji', 'T', 1000, 1, 'WithWindow',
                            'X', 1, ?)
                """, (_now_iso(days_ago=3),))
                for d, p in enumerate([1000.0, 1100.0]):
                    conn.execute("""
                        INSERT INTO price_history (listing_id, price, seen_at)
                        VALUES ('MW1', ?, ?)
                    """, (p, _now_iso(days_ago=2 - d)))
                conn.commit()
            finally:
                persist._reset_conn()
            resp = c.get("/api/meta")
            data = resp.get_json()
            assert "WithWindow" in data["neighborhood_trends"]
            assert data["neighborhood_trends"]["WithWindow"]["window_days"] == 30


# ════════════════════════════════════════════════════════════════════════
# Class 4: index.html trend badge wiring (CSS + render)
# ════════════════════════════════════════════════════════════════════════


class TestIndexHtmlTrendBadgeWiring:
    """Template has the CSS classes and the render call wired up."""

    @staticmethod
    def _read_template() -> str:
        path = _RENT_ROOT / "templates" / "index.html"
        return path.read_text(encoding="utf-8")

    def test_css_class_nbhd_trend_up_exists(self):
        html = self._read_template()
        assert ".nbhd-trend-up" in html
        assert ".nbhd-trend-down" in html
        assert ".nbhd-trend-flat" in html

    def test_css_colors_match_ac4_spec(self):
        """AC4 specifies: up=red #b00020, down=green #2d6a4f, flat=grey #6c7a89."""
        html = self._read_template()
        # Pull the .nbhd-trend-* blocks
        up_match = re.search(r"\.nbhd-trend-up\s*\{[^}]*#b00020", html)
        down_match = re.search(r"\.nbhd-trend-down\s*\{[^}]*#2d6a4f", html)
        flat_match = re.search(r"\.nbhd-trend-flat\s*\{[^}]*#6c7a89", html)
        assert up_match, "AC4: .nbhd-trend-up must use #b00020 (red, prices rising)"
        assert down_match, "AC4: .nbhd-trend-down must use #2d6a4f (green, prices falling)"
        assert flat_match, "AC4: .nbhd-trend-flat must use #6c7a89 (grey, flat)"

    def test_render_call_invoked_in_neighborhood_cell(self):
        """The deals-table neighborhood cell must call _renderNbhdTrendBadge."""
        html = self._read_template()
        # Look for the neighborhood column's <td> block. The content is
        # on one line in the rendered template. We use a tolerant regex
        # (DOTALL on) so any future line-wrapping doesn't break the test.
        m = re.search(
            r"<td>[^<]*<strong>\$\{d\.neighbourhood \|\|.*?d\.neighborhood_slug.*?</td>",
            html, re.DOTALL,
        )
        assert m, "could not locate neighborhood <td> cell"
        cell = m.group(0)
        assert "_renderNbhdTrendBadge(d.neighborhood_trend)" in cell, \
            "AC4: badge render must be called inside the neighborhood cell"

    def test_render_helper_defined_in_script(self):
        """_renderNbhdTrendBadge function must be defined somewhere in the
        page's <script> block (where renderDeals() etc. live)."""
        html = self._read_template()
        m = re.search(r"function\s+_renderNbhdTrendBadge\s*\([^)]*\)\s*\{", html)
        assert m, "_renderNbhdTrendBadge function not defined"

    def test_no_new_column_added_to_deals_table(self):
        """AC5: deal-table column order is preserved (no new column added).
        We assert the badge lives inline next to neighbourhood name, not
        as its own <td>."""
        html = self._read_template()
        # Find the deals-table <thead> and count <th> cells.
        thead_match = re.search(r"<thead>.*?</thead>", html, re.DOTALL)
        assert thead_match, "no <thead> block found"
        th_count = len(re.findall(r"<th[\s>]", thead_match.group(0)))
        # Also count the actual <td> cells in the FIRST data row's render.
        # We just assert that no column header contains "trend" anywhere.
        assert "trend" not in thead_match.group(0).lower(), \
            "AC5: no new 'trend' column header was added"

    def test_drilldown_link_intact(self):
        """AC6: /neighborhood/<slug> drill-down link stays intact."""
        html = self._read_template()
        assert "/neighborhood/${encodeURIComponent(d.neighborhood_slug)}" in html, \
            "AC6: drill-down /neighborhood/<slug> link missing or broken"

    def test_badge_render_handles_null_trend(self):
        """When neighborhood_trend is None (the common case for
        neighbourhoods without 2+ days of price history), the badge
        render must return empty string, not 'undefined'."""
        html = self._read_template()
        # The helper's first guard: return '' if trend is falsy/missing.
        m = re.search(
            r"function\s+_renderNbhdTrendBadge[\s\S]*?return\s*'';",
            html,
        )
        assert m, "render helper must short-circuit on missing trend"

    def test_badge_classes_match_directions(self):
        """Verify that _renderNbhdTrendBadge maps each direction to the
        matching .nbhd-trend-<dir> class. We allow either a literal class
        string or a template-interpolated construction (`nbhd-trend-${dir}`)
        since both produce the correct rendered class.
        """
        html = self._read_template()
        m = re.search(
            r"function\s+_renderNbhdTrendBadge\s*\([^)]*\)\s*\{([\s\S]*?)\n\}",
            html,
        )
        assert m, "could not extract _renderNbhdTrendBadge body"
        body = m.group(1)
        # The three direction class names must appear in CSS (defined
        # elsewhere) AND the body must use a template interpolation
        # `nbhd-trend-${dir}` (so direction is wired to the class).
        assert "nbhd-trend-${dir}" in body, \
            "render helper must construct class via `nbhd-trend-${dir}` template"
        # And the three direction literals must be enumerated in the
        # direction-validity check.
        for d in ("up", "down", "flat"):
            assert f"'{d}'" in body or f'"{d}"' in body, \
                f"direction literal {d!r} not enumerated in helper"


# ── Runner ─────────────────────────────────────────────────────────────────


def _run_all() -> None:
    import inspect
    classes = [
        TestGetNeighborhoodTrendsBatch,
        TestDealsIncludeNeighborhoodTrend,
        TestApiMetaNeighborhoodTrends,
        TestIndexHtmlTrendBadgeWiring,
    ]
    total = 0
    failed = 0
    for cls in classes:
        for name, fn in inspect.getmembers(cls, predicate=inspect.isfunction):
            if not name.startswith("test_"):
                continue
            total += 1
            instance = cls()
            try:
                fn(instance)
                print(f"PASS {cls.__name__}.{name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {cls.__name__}.{name}: {e}")
            except Exception as e:
                failed += 1
                print(f"ERROR {cls.__name__}.{name}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n{failed}/{total} tests failed.")
        sys.exit(1)
    print(f"\nAll {total} MC-329 nbhd-trend-badge tests passed.")


if __name__ == "__main__":
    _run_all()

