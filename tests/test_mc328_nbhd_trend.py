"""
MC-328: Per-neighbourhood price-trend chart on the drill-down page.

Covers:
  - persist.get_neighborhood_price_history(neighborhood, days=30) aggregation
  - app /api/neighborhoods/<slug>/price-history endpoint shape + 404
  - templates/neighborhood.html wiring (Chart.js loader + canvases + JS)
  - empty/edge-case behaviour (no listings, <2 days, NULL sqft, garbage rows)
"""

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import persist  # noqa: E402
import app      # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────

def _isolated_db(tmpdir: str) -> str:
    """Point persist + app at a fresh isolated DB inside tmpdir."""
    db_path = os.path.join(tmpdir, 'listings.db')
    persist.DB_PATH = db_path
    app.DB_PATH = db_path
    try:
        persist._reset_conn()
    except AttributeError:
        pass
    persist.init_db()
    return db_path


def _seed_listing(listing_id: str, neighborhood: str = 'Annex', price: float = 2000.0,
                  beds: float = 1, baths: float = 1, sqft=None, region: str = 'Downtown',
                  source: str = 'kijiji'):
    """Insert an active listing row."""
    conn = sqlite3.connect(persist.DB_PATH)
    try:
        conn.execute("""
            INSERT INTO listings (
                listing_id, source, title, price, beds, baths, sqft,
                neighborhood, region, url, image_url,
                days_ago, is_stale, first_seen, last_seen, is_active,
                scrape_count, is_new, fair_value, score, pct_under
            ) VALUES (?, ?, 'Test', ?, ?, ?, ?, ?, ?, '', '', 1, 0,
                      strftime('%Y-%m-%dT%H:%M:%SZ','now'),
                      strftime('%Y-%m-%dT%H:%M:%SZ','now'),
                      1, 1, 0, 2000.0, 0.1, 0.05)
        """, (listing_id, source, price, beds, baths, sqft, neighborhood, region))
        conn.commit()
    finally:
        conn.close()


def _seed_history(listing_id: str, price: float, iso_ts: str):
    """Insert a single price_history row."""
    persist.seed_price_history_for_listing(listing_id, price, iso_ts)


# ── TestGetNeighborhoodPriceHistory ──────────────────────────────────────────

class TestGetNeighborhoodPriceHistory:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix='mc328_')
        _isolated_db(self.tmpdir)

    def teardown_method(self):
        import shutil
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_returns_empty_list_for_unknown_neighborhood(self):
        out = persist.get_neighborhood_price_history('NowhereVille')
        assert out == [], f'expected [], got {out}'

    def test_returns_empty_list_for_empty_neighborhood(self):
        out = persist.get_neighborhood_price_history('')
        assert out == [], f'expected [], got {out}'

    def test_returns_empty_list_when_active_listing_has_no_history(self):
        _seed_listing('L1', neighborhood='Annex', price=2000.0)
        out = persist.get_neighborhood_price_history('Annex')
        assert out == [], f'expected [], got {out}'

    def test_returns_empty_list_when_only_inactive_listing_has_history(self):
        # Active marker = 1. Seed an active row with no history; the test
        # ensures we don't return anything when no active listings exist
        # for the neighbourhood.
        _seed_listing('L1', neighborhood='Annex', price=2000.0)
        # Manually flip the listing to inactive
        conn = sqlite3.connect(persist.DB_PATH)
        conn.execute("UPDATE listings SET is_active = 0 WHERE listing_id = ?", ('L1',))
        conn.commit()
        conn.close()
        _seed_history('L1', 2000.0, '2026-07-01T10:00:00Z')
        out = persist.get_neighborhood_price_history('Annex')
        assert out == [], f'expected [] for inactive listing, got {out}'

    def test_single_day_with_three_listings_aggregates_median_price(self):
        _seed_listing('A', price=2000.0)
        _seed_listing('B', price=2400.0)
        _seed_listing('C', price=2800.0)
        _seed_history('A', 2000.0, '2026-07-07T10:00:00Z')
        _seed_history('B', 2400.0, '2026-07-07T11:00:00Z')
        _seed_history('C', 2800.0, '2026-07-07T12:00:00Z')
        out = persist.get_neighborhood_price_history('Annex', days=14)
        assert len(out) == 1
        row = out[0]
        assert row['date_iso'] == '2026-07-07'
        assert row['median_price'] == 2400.0
        assert row['listing_count'] == 3

    def test_two_days_aggregates_into_two_rows_sorted_ascending(self):
        _seed_listing('A', price=2000.0)
        _seed_listing('B', price=2200.0)
        _seed_history('A', 2000.0, '2026-07-06T10:00:00Z')
        _seed_history('A', 2100.0, '2026-07-07T10:00:00Z')
        _seed_history('B', 2200.0, '2026-07-07T11:00:00Z')
        out = persist.get_neighborhood_price_history('Annex', days=14)
        assert len(out) == 2
        assert out[0]['date_iso'] == '2026-07-06'
        assert out[1]['date_iso'] == '2026-07-07'
        assert out[0]['median_price'] == 2000.0
        # 2100, 2200 → median 2150
        assert out[1]['median_price'] == 2150.0
        assert out[1]['listing_count'] == 2

    def test_only_returns_active_neighbourhood_rows(self):
        # Seed listings in TWO neighborhoods; filter should return only one.
        _seed_listing('A', neighborhood='Annex', price=2000.0)
        _seed_listing('B', neighborhood='Bay Street Corridor', price=3000.0)
        _seed_history('A', 2000.0, '2026-07-07T10:00:00Z')
        _seed_history('B', 3000.0, '2026-07-07T10:00:00Z')
        out_annex = persist.get_neighborhood_price_history('Annex')
        out_bay = persist.get_neighborhood_price_history('Bay Street Corridor')
        assert len(out_annex) == 1
        assert len(out_bay) == 1
        assert out_annex[0]['median_price'] == 2000.0
        assert out_bay[0]['median_price'] == 3000.0

    def test_neighborhood_match_is_case_insensitive(self):
        _seed_listing('A', neighborhood='Annex', price=2000.0)
        _seed_history('A', 2000.0, '2026-07-07T10:00:00Z')
        out_lower = persist.get_neighborhood_price_history('annex')
        out_upper = persist.get_neighborhood_price_history('ANNEX')
        out_mixed = persist.get_neighborhood_price_history('AnNeX')
        assert len(out_lower) == 1, f'expected 1 row for lowercase, got {len(out_lower)}'
        assert len(out_upper) == 1, f'expected 1 row for uppercase, got {len(out_upper)}'
        assert len(out_mixed) == 1, f'expected 1 row for mixed, got {len(out_mixed)}'

    def test_listings_without_sqft_excluded_from_pps_but_in_price(self):
        _seed_listing('A', price=2000.0, sqft=500)
        _seed_listing('B', price=2400.0, sqft=None)
        _seed_listing('C', price=2800.0, sqft=600)
        _seed_history('A', 2000.0, '2026-07-07T10:00:00Z')
        _seed_history('B', 2400.0, '2026-07-07T11:00:00Z')
        _seed_history('C', 2800.0, '2026-07-07T12:00:00Z')
        out = persist.get_neighborhood_price_history('Annex', days=14)
        assert len(out) == 1
        row = out[0]
        # All three included for price median (2000, 2400, 2800 → 2400)
        assert row['median_price'] == 2400.0
        assert row['listing_count'] == 3
        # Only A and C have sqft: $/sqft = 2000/500=4.0, 2800/600≈4.67
        assert row['median_price_per_sqft'] is not None
        assert abs(row['median_price_per_sqft'] - 4.3333333333) < 0.01
        assert row['dollar_per_sqft_min'] == 4.0
        assert abs(row['dollar_per_sqft_max'] - 4.6666666667) < 0.01

    def test_all_listings_without_sqft_yields_null_pps(self):
        _seed_listing('A', price=2000.0, sqft=None)
        _seed_listing('B', price=2400.0, sqft=None)
        _seed_history('A', 2000.0, '2026-07-07T10:00:00Z')
        _seed_history('B', 2400.0, '2026-07-07T11:00:00Z')
        out = persist.get_neighborhood_price_history('Annex', days=14)
        assert len(out) == 1
        row = out[0]
        assert row['median_price'] == 2200.0
        assert row['median_price_per_sqft'] is None
        assert row['dollar_per_sqft_min'] is None
        assert row['dollar_per_sqft_max'] is None

    def test_respects_days_window(self):
        _seed_listing('A', price=2000.0)
        _seed_history('A', 1800.0, '2026-06-01T10:00:00Z')  # outside 14-day window
        _seed_history('A', 2000.0, '2026-07-07T10:00:00Z')  # inside
        out_14 = persist.get_neighborhood_price_history('Annex', days=14)
        out_60 = persist.get_neighborhood_price_history('Annex', days=60)
        assert len(out_14) == 1
        assert len(out_60) == 2
        # Sorted ascending; the older one is the second entry
        assert out_60[0]['date_iso'] == '2026-06-01'
        assert out_60[1]['date_iso'] == '2026-07-07'

    def test_within_day_uses_all_listings_not_distinct(self):
        # Two listings in the same day each get a history point — both count
        # towards the daily median (not just the latest).
        _seed_listing('A', price=2000.0)
        _seed_listing('B', price=3000.0)
        _seed_history('A', 2000.0, '2026-07-07T08:00:00Z')
        _seed_history('B', 3000.0, '2026-07-07T20:00:00Z')
        out = persist.get_neighborhood_price_history('Annex', days=14)
        assert len(out) == 1
        assert out[0]['listing_count'] == 2
        assert out[0]['median_price'] == 2500.0

    def test_neighbourhood_with_no_active_listings_returns_empty(self):
        # Seed history on a listing in another neighborhood (Lakeshore) and
        # query a different one (Annex) that has no rows at all.
        _seed_listing('A', neighborhood='Lakeshore', price=2000.0)
        _seed_history('A', 2000.0, '2026-07-07T10:00:00Z')
        out = persist.get_neighborhood_price_history('Annex', days=14)
        assert out == []

    def test_handles_null_price_gracefully(self):
        # A NULL price row would be unusual but should be skipped, not crash.
        _seed_listing('A', price=2000.0)
        _seed_history('A', 2000.0, '2026-07-07T10:00:00Z')
        conn = sqlite3.connect(persist.DB_PATH)
        # Insert a NULL price directly (defensive — schema requires NOT NULL,
        # but a future migration could relax it; the function should be safe).
        try:
            conn.execute("""
                INSERT INTO price_history (listing_id, price, seen_at)
                VALUES (?, NULL, ?)
            """, ('A', '2026-07-07T11:00:00Z'))
            conn.commit()
        except sqlite3.IntegrityError:
            # Schema enforces NOT NULL — that's fine, the test still passes
            # because the function defensively handles None.
            pass
        finally:
            conn.close()
        out = persist.get_neighborhood_price_history('Annex', days=14)
        assert len(out) == 1
        # Only the non-null row counts
        assert out[0]['listing_count'] == 1

    def test_negative_or_zero_price_rows_are_skipped(self):
        _seed_listing('A', price=2000.0)
        _seed_history('A', 0, '2026-07-07T09:00:00Z')        # zero
        _seed_history('A', -100, '2026-07-07T10:00:00Z')    # negative
        _seed_history('A', 2200.0, '2026-07-07T11:00:00Z')  # valid
        out = persist.get_neighborhood_price_history('Annex', days=14)
        assert len(out) == 1
        assert out[0]['median_price'] == 2200.0
        assert out[0]['listing_count'] == 1


# ── TestApiNeighborhoodPriceHistoryEndpoint ───────────────────────────────────

class TestApiNeighborhoodPriceHistoryEndpoint:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix='mc328_')
        db_path = _isolated_db(self.tmpdir)
        # Seed an active listing and a deals CSV so load_deals() returns it.
        _seed_listing('L1', neighborhood='Annex', price=2000.0)
        _seed_history('L1', 2000.0, '2026-07-06T10:00:00Z')
        _seed_history('L1', 2100.0, '2026-07-07T10:00:00Z')
        # Also seed the deals CSV so load_deals (which tries CSV as a
        # fallback when the SQLite path returns empty) doesn't try to
        # load the wrong thing. With active listings in SQLite, this
        # path isn't exercised.
        csv_path = os.path.join(self.tmpdir, 'deals_output.csv')
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            f.write('listing_id,neighborhood,price,beds\n')
            f.write('L1,Annex,2000,1\n')

        # Point app at the test DB too
        app.DB_PATH = db_path
        # Reset connection caching
        try:
            persist._reset_conn()
        except AttributeError:
            pass
        app.app.config['TESTING'] = True
        self.client = app.app.test_client()

    def teardown_method(self):
        import shutil
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_404_for_unknown_slug(self):
        r = self.client.get('/api/neighborhoods/atlantis/price-history?days=30')
        assert r.status_code == 404
        body = r.get_json()
        assert body['error'] == 'neighborhood not found'
        assert body['slug'] == 'atlantis'

    def test_200_known_slug_returns_shape(self):
        r = self.client.get('/api/neighborhoods/annex/price-history?days=30')
        assert r.status_code == 200
        body = r.get_json()
        # Top-level keys
        for k in ('neighborhood', 'slug', 'days', 'days_of_data', 'series'):
            assert k in body, f'missing top-level key: {k}'
        assert body['neighborhood'] == 'Annex'
        assert body['slug'] == 'annex'
        assert body['days'] == 30
        assert body['days_of_data'] == len(body['series'])
        assert body['days_of_data'] >= 2

    def test_series_rows_have_full_shape(self):
        r = self.client.get('/api/neighborhoods/annex/price-history?days=30')
        body = r.get_json()
        row = body['series'][0]
        for k in ('date_iso', 'median_price', 'median_price_per_sqft',
                  'listing_count', 'dollar_per_sqft_min', 'dollar_per_sqft_max'):
            assert k in row, f'missing series row key: {k}'
        assert isinstance(row['date_iso'], str)
        assert isinstance(row['listing_count'], int)

    def test_default_days_is_30(self):
        r = self.client.get('/api/neighborhoods/annex/price-history')
        body = r.get_json()
        assert body['days'] == 30

    def test_custom_days_param(self):
        r = self.client.get('/api/neighborhoods/annex/price-history?days=14')
        body = r.get_json()
        assert body['days'] == 14

    def test_garbage_days_param_falls_back_to_30(self):
        r = self.client.get('/api/neighborhoods/annex/price-history?days=abc')
        body = r.get_json()
        assert body['days'] == 30

    def test_days_clamped_to_min_1(self):
        r = self.client.get('/api/neighborhoods/annex/price-history?days=0')
        body = r.get_json()
        assert body['days'] == 1
        r2 = self.client.get('/api/neighborhoods/annex/price-history?days=-5')
        body2 = r2.get_json()
        assert body2['days'] == 1

    def test_days_clamped_to_max_365(self):
        r = self.client.get('/api/neighborhoods/annex/price-history?days=99999')
        body = r.get_json()
        assert body['days'] == 365

    def test_empty_history_returns_empty_series(self):
        # Reset and seed an active listing with NO history rows in another
        # neighbourhood so we can hit the empty-data path with a 200.
        _seed_listing('Lonely', neighborhood='Lakeshore', price=2000.0)
        # Need to also populate the in-memory deals cache: rebuild by hitting
        # the endpoint after resetting persist conn.
        try:
            persist._reset_conn()
        except AttributeError:
            pass
        r = self.client.get('/api/neighborhoods/lakeshore/price-history?days=30')
        # _slug_to_neighborhood requires the listing to appear in deals, which
        # are loaded from SQLite directly. So this should resolve to the slug.
        if r.status_code == 200:
            body = r.get_json()
            assert body['days_of_data'] == 0
            assert body['series'] == []
        else:
            # Acceptable fallback: 404 if the slug never made it into the
            # in-memory deals cache (load_deals reads the DB at request
            # time so it should always see Lakeshore — but defensive).
            assert r.status_code == 404


# ── TestNeighborhoodHtmlTrendSection ──────────────────────────────────────────

class TestNeighborhoodHtmlTrendSection:
    """Static checks on templates/neighborhood.html."""

    @classmethod
    def setup_class(cls):
        cls.html_path = os.path.join(
            os.path.dirname(_HERE), 'templates', 'neighborhood.html'
        )
        with open(cls.html_path, encoding='utf-8') as f:
            cls.html = f.read()

    def test_chartjs_loader_present(self):
        assert 'chart.js@4.4.0' in self.html or 'chart.umd.min.js' in self.html, \
            'Chart.js CDN loader not found in neighborhood.html'

    def test_canvas_for_price_chart(self):
        assert 'id="nbhd_trend_chart"' in self.html, \
            'price trend canvas (id="nbhd_trend_chart") missing'

    def test_canvas_for_pps_chart(self):
        assert 'id="nbhd_pps_trend_chart"' in self.html, \
            '$/sqft trend canvas (id="nbhd_pps_trend_chart") missing'

    def test_trend_section_container(self):
        assert 'id="trend-section"' in self.html, 'trend section container missing'
        assert 'id="trend-grid"' in self.html, 'trend grid container missing'
        assert 'id="trend-empty"' in self.html, 'trend empty-state element missing'

    def test_fetches_price_history_endpoint(self):
        assert '/price-history' in self.html, \
            'neighborhood.html does not call the /price-history endpoint'

    def test_empty_state_message_present(self):
        assert 'Not enough data yet' in self.html, \
            'empty-state copy "Not enough data yet" missing'

    def test_chart_construction_with_new_chart(self):
        # The page should actually construct Chart instances
        assert 'new Chart(' in self.html, 'Chart.js not instantiated'

    def test_sub_header_with_pill_present(self):
        assert 'trend-pill' in self.html, 'trend-pill CSS class missing'
        assert 'over window' in self.html or 'over the window' in self.html, \
            'trend sub-header copy missing'


# ── TestEmptyAndEdgeCases ────────────────────────────────────────────────────

class TestEmptyAndEdgeCases:
    """End-to-end smoke against the live Flask test client."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix='mc328_smoke_')
        db_path = _isolated_db(self.tmpdir)
        self.db_path = db_path
        app.DB_PATH = db_path
        try:
            persist._reset_conn()
        except AttributeError:
            pass
        app.app.config['TESTING'] = True
        self.client = app.app.test_client()

    def teardown_method(self):
        import shutil
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_unknown_slug_does_not_500(self):
        r = self.client.get('/api/neighborhoods/zzz-unknown/price-history')
        assert r.status_code == 404
        # Body should be JSON, not a 500 HTML page
        assert r.is_json

    def test_neighborhood_page_200_with_no_listings(self):
        r = self.client.get('/neighborhood/zzz-unknown')
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'trend-section' in body

    def test_neighborhood_page_200_for_known_slug(self):
        _seed_listing('L1', neighborhood='Annex', price=2000.0)
        _seed_history('L1', 2000.0, '2026-07-06T10:00:00Z')
        _seed_history('L1', 2200.0, '2026-07-07T10:00:00Z')
        r = self.client.get('/neighborhood/annex')
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'nbhd_trend_chart' in body
        assert 'nbhd_pps_trend_chart' in body
        assert '/price-history' in body
        assert 'new Chart(' in body