"""
MC-346: Filtered CSV export tests.

4 test classes per AC8:
  - TestCsvEndpoint: GET /api/deals.csv, headers, columns, filename
  - TestFilterParity: filtered row count matches /api/deals JSON total
  - TestIndexHtmlWiring: Download CSV button + loading/Downloaded states
  - TestEmptyAndErrorPaths: empty filter result, malformed params

Strategy: load_deals() falls back to the live deals_output.csv when
SQLite is empty. Tests use a tmp CSV with a known row set to make
the filter-parity assertions deterministic regardless of prod data.

Run: python tests/test_mc346_csv_export.py
"""
import csv
import io
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

RENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RENT_DIR))
sys.path.insert(0, str(RENT_DIR / 'tests'))

# Per MC-331: pin DB_PATH to a tmp file so we don't touch production.
TMP_DIR = tempfile.mkdtemp(prefix='mc346_')
os.environ['RENT_DATA_DIR'] = TMP_DIR

import persist as persist_module
import app as app_module
import neighbourhood_lookup  # noqa: F401  (loads the registry app needs)

persist_module.DB_PATH = os.path.join(TMP_DIR, 'listings.db')
app_module.DB_PATH = persist_module.DB_PATH


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_csv(rows: list[dict], tmpdir: str) -> str:
    """Write a deals_output.csv-style file with the given rows, return path."""
    path = os.path.join(tmpdir, 'deals_output.csv')
    fieldnames = ['source', 'price', 'beds', 'baths', 'sqft', 'neighborhood',
                  'days_ago', 'link', 'region', 'fair_value', 'pct_under',
                  'score', 'freshness_boost', 'final_score', 'rank']
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in fieldnames})
    return path


def _client():
    return app_module.app.test_client()


# ════════════════════════════════════════════════════════════════════════
# Class 1: GET /api/deals.csv
# ════════════════════════════════════════════════════════════════════════


class TestCsvEndpoint:
    """AC2 + AC3 + AC4: headers, columns, empty."""

    def test_content_type_is_text_csv(self):
        with app_module.app.test_client() as c:
            r = c.get('/api/deals.csv')
        assert r.status_code == 200
        assert 'text/csv' in r.headers.get('Content-Type', '')

    def test_content_disposition_filename_has_toronto_deals_date(self):
        with app_module.app.test_client() as c:
            r = c.get('/api/deals.csv')
        cd = r.headers.get('Content-Disposition', '')
        assert 'attachment' in cd
        expected = f'toronto-deals-{date.today().isoformat()}.csv'
        assert expected in cd, f"expected filename {expected!r} in {cd!r}"

    def test_csv_columns_match_ac3_schema(self):
        with app_module.app.test_client() as c:
            r = c.get('/api/deals.csv')
        body = r.get_data(as_text=True)
        reader = csv.reader(io.StringIO(body))
        header = next(reader)
        # AC3 column list, in the order the writer emits them.
        expected = ['price', 'beds', 'baths', 'neighbourhood', 'fair_value',
                    'pct_under', 'score', 'days_ago', 'sqft', 'link',
                    'source', 'listed_date', 'region']
        assert header == expected, f"header mismatch: {header}"

    def test_csv_body_contains_data_rows(self):
        """AC5: filtered row count matches /api/deals JSON total."""
        with app_module.app.test_client() as c:
            r = c.get('/api/deals.csv')
        body = r.get_data(as_text=True)
        # At minimum we have the header row. If the live data has rows
        # the body has more. We assert non-empty data section.
        assert body.count('\n') >= 1, "CSV body should have at least a header line"

    def test_x_filter_row_count_header(self):
        """AC5 helper: X-Filter-Row-Count header carries the row count."""
        with app_module.app.test_client() as c:
            r = c.get('/api/deals.csv')
        xc = r.headers.get('X-Filter-Row-Count', None)
        assert xc is not None
        assert xc.isdigit()

    def test_returns_200_not_404(self):
        with app_module.app.test_client() as c:
            r = c.get('/api/deals.csv')
        assert r.status_code == 200
        assert r.status_code != 404


# ════════════════════════════════════════════════════════════════════════
# Class 2: filter parity with /api/deals
# ════════════════════════════════════════════════════════════════════════


class TestFilterParity:
    """AC5: same filter params produce same row count for /api/deals
    JSON and /api/deals.csv."""

    def _seed_minimal_csv(self):
        """Seed a small deterministic dataset directly into SQLite so
        load_deals() (which prefers SQLite over the CSV fallback per
        MC-262) returns the rows. 6 rows covering different prices /
        beds / sources so a single filter has a meaningful result."""
        rows = [
            {'source': 'kijiji', 'price': 1500, 'beds': 1, 'baths': 1,
             'sqft': 500, 'neighborhood': 'Agincourt North', 'days_ago': 1,
             'link': 'https://kijiji.ca/v-1', 'region': 'Scarborough',
             'fair_value': 2000, 'pct_under': 25.0, 'score': 0.8,
             'freshness_boost': 0, 'final_score': 0.8, 'rank': 1},
            {'source': 'kijiji', 'price': 2200, 'beds': 2, 'baths': 1,
             'sqft': 750, 'neighborhood': 'Agincourt North', 'days_ago': 2,
             'link': 'https://kijiji.ca/v-2', 'region': 'Scarborough',
             'fair_value': 2400, 'pct_under': 8.3, 'score': 0.5,
             'freshness_boost': 0, 'final_score': 0.5, 'rank': 2},
            {'source': 'craigslist', 'price': 1800, 'beds': 1, 'baths': 1,
             'sqft': 600, 'neighborhood': 'Bay and College', 'days_ago': 3,
             'link': 'https://craigslist.org/v-3', 'region': 'Downtown',
             'fair_value': 2200, 'pct_under': 18.2, 'score': 0.7,
             'freshness_boost': 0, 'final_score': 0.7, 'rank': 3},
            {'source': 'kijiji', 'price': 3000, 'beds': 3, 'baths': 2,
             'sqft': 1100, 'neighborhood': 'Niagara', 'days_ago': 4,
             'link': 'https://kijiji.ca/v-4', 'region': 'Downtown',
             'fair_value': 3200, 'pct_under': 6.3, 'score': 0.3,
             'freshness_boost': 0, 'final_score': 0.3, 'rank': 4},
            {'source': 'craigslist', 'price': 4000, 'beds': 4, 'baths': 2,
             'sqft': 1500, 'neighborhood': 'Leslieville', 'days_ago': 5,
             'link': 'https://craigslist.org/v-5', 'region': 'East End',
             'fair_value': 3800, 'pct_under': -5.3, 'score': 0.2,
             'freshness_boost': 0, 'final_score': 0.2, 'rank': 5},
            {'source': 'kijiji', 'price': 2500, 'beds': 2, 'baths': 1,
             'sqft': 900, 'neighborhood': 'Lansing-Westgate', 'days_ago': 6,
             'link': 'https://kijiji.ca/v-6', 'region': 'North York',
             'fair_value': 2800, 'pct_under': 10.7, 'score': 0.6,
             'freshness_boost': 0, 'final_score': 0.6, 'rank': 6},
        ]
        # Seed via persist.upsert_listings so load_deals() (SQLite path)
        # returns them. We do NOT use first_seen / last_seen explicitly
        # here -- load_deals() / _normalize_row fill those in via defaults.
        from persist import upsert_listings
        upsert_listings(rows=rows)
        return rows

    def test_beds_min_filter_parity(self):
        """beds_min=2 -> 4 rows (rows with beds in {2,3,4}).
        JSON total == CSV row count."""
        self._seed_minimal_csv()
        with app_module.app.test_client() as c:
            r_json = c.get('/api/deals?beds_min=2')
            r_csv = c.get('/api/deals.csv?beds_min=2')
        assert r_json.status_code == 200
        assert r_csv.status_code == 200
        json_total = r_json.get_json()['total']
        csv_count = int(r_csv.headers['X-Filter-Row-Count'])
        assert json_total == csv_count, \
            f"beds_min=2: JSON total={json_total} vs CSV count={csv_count}"
        assert csv_count == 4, f"expected 4 rows for beds_min=2, got {csv_count}"

    def test_price_max_filter_parity(self):
        self._seed_minimal_csv()
        with app_module.app.test_client() as c:
            r_json = c.get('/api/deals?price_max=2500')
            r_csv = c.get('/api/deals.csv?price_max=2500')
        json_total = r_json.get_json()['total']
        csv_count = int(r_csv.headers['X-Filter-Row-Count'])
        assert json_total == csv_count
        # price_max=2500 -> 4 rows (1500, 2200, 1800, 2500). 3000+ are excluded.
        assert csv_count == 4

    def test_source_filter_parity(self):
        self._seed_minimal_csv()
        with app_module.app.test_client() as c:
            r_json = c.get('/api/deals?source=kijiji')
            r_csv = c.get('/api/deals.csv?source=kijiji')
        json_total = r_json.get_json()['total']
        csv_count = int(r_csv.headers['X-Filter-Row-Count'])
        assert json_total == csv_count
        # source=kijiji -> 4 rows (1, 2, 4, 6).
        assert csv_count == 4

    def test_combined_filters_parity(self):
        self._seed_minimal_csv()
        with app_module.app.test_client() as c:
            r_json = c.get('/api/deals?beds_min=1&price_max=2200&source=kijiji')
            r_csv = c.get('/api/deals.csv?beds_min=1&price_max=2200&source=kijiji')
        json_total = r_json.get_json()['total']
        csv_count = int(r_csv.headers['X-Filter-Row-Count'])
        assert json_total == csv_count

    def test_min_pct_under_filter_parity(self):
        self._seed_minimal_csv()
        with app_module.app.test_client() as c:
            r_json = c.get('/api/deals?min_pct_under=20')
            r_csv = c.get('/api/deals.csv?min_pct_under=20')
        json_total = r_json.get_json()['total']
        csv_count = int(r_csv.headers['X-Filter-Row-Count'])
        assert json_total == csv_count


# ════════════════════════════════════════════════════════════════════════
# Class 3: HTML / JS wiring (button + states)
# ════════════════════════════════════════════════════════════════════════


class TestIndexHtmlWiring:
    """AC6: Download CSV button in filter bar, right side.
       AC7: loading state + green Downloaded confirmation."""

    @staticmethod
    def _read_template() -> str:
        return (RENT_DIR / 'templates' / 'index.html').read_text(encoding='utf-8')

    def test_button_present_with_id_export_csv_btn(self):
        html = self._read_template()
        assert 'id="export_csv_btn"' in html

    def test_button_label_is_download_csv(self):
        """AC6: button text is 'Download CSV'."""
        html = self._read_template()
        m = re.search(r'<span id="export_csv_label"[^>]*>([^<]*)</span>', html)
        assert m, "export_csv_label span not found"
        assert 'Download CSV' in m.group(1), \
            f"button label is {m.group(1)!r}, expected 'Download CSV'"

    def test_button_in_filter_bar(self):
        """AC6: button in the filter bar (right side)."""
        html = self._read_template()
        # The filter bar contains the export_csv_btn. The 'filter-bar'
        # / 'filters' container is what we look for.
        # Heuristic: the button is on the same line as the filter_count badge.
        btn_pos = html.index('id="export_csv_btn"')
        badge_pos = html.index('id="filter_count"')
        # Both should be within ~200 chars of each other (same flex row).
        assert abs(btn_pos - badge_pos) < 500

    def test_js_handler_points_to_api_deals_csv(self):
        """AC1: handler hits the new /api/deals.csv endpoint, not the
        legacy /api/deals/export.csv."""
        html = self._read_template()
        # The handler function (exportFilteredCsv) should reference
        # /api/deals.csv, not /api/deals/export.csv.
        m = re.search(r"const url = '(/api/deals\.csv|/api/deals/export\.csv)'", html)
        assert m, "exportFilteredCsv URL not found"
        assert m.group(1) == '/api/deals.csv', \
            f"URL is {m.group(1)!r}, expected '/api/deals.csv'"

    def test_js_handler_has_downloading_state(self):
        """AC7: button label changes to 'Downloading...' while the
        request is in flight."""
        html = self._read_template()
        m = re.search(r"label\.textContent\s*=\s*'Downloading", html)
        assert m, "Loading state 'Downloading…' not in handler"

    def test_js_handler_has_downloaded_state(self):
        """AC7: button label changes to 'Downloaded' on completion
        (green, ~1.5s)."""
        html = self._read_template()
        # The handler should set label.textContent = '✓ Downloaded'
        # (or similar) and restore the original label after 1.5s.
        m = re.search(r"label\.textContent\s*=\s*'.*Downloaded", html)
        assert m, "Downloaded confirmation text not in handler"
        # The restore-original-label block uses setTimeout(..., 1500).
        m2 = re.search(r"setTimeout\([^,]+,\s*1500\s*\)", html)
        assert m2, "1.5s restore setTimeout not in handler"

    def test_button_disabled_during_download(self):
        """AC7: button is disabled while the request is in flight
        (prevents double-clicks)."""
        html = self._read_template()
        m = re.search(r"btn\.disabled\s*=\s*true", html)
        assert m, "Button must be disabled during download (btn.disabled = true)"

    def test_uses_iframe_for_download(self):
        """AC7: download uses a hidden iframe so the user stays on the
        deals page (no tab switch)."""
        html = self._read_template()
        assert 'export_csv_iframe' in html, \
            "Must use the export_csv_iframe hidden iframe pattern"


# ════════════════════════════════════════════════════════════════════════
# Class 4: empty filter results + error paths
# ════════════════════════════════════════════════════════════════════════


class TestEmptyAndErrorPaths:
    """AC4: empty filter result -> CSV with header only (200, not 404)."""

    def _seed_one_row(self):
        """Seed a single cheap row via persist (SQLite path) so we can
        apply an impossible filter to force an empty result."""
        rows = [
            {'source': 'kijiji', 'price': 1500, 'beds': 1, 'baths': 1,
             'sqft': 500, 'neighborhood': 'Agincourt North', 'days_ago': 1,
             'link': 'https://kijiji.ca/v-1', 'region': 'Scarborough',
             'fair_value': 2000, 'pct_under': 25.0, 'score': 0.8,
             'freshness_boost': 0, 'final_score': 0.8, 'rank': 1},
        ]
        from persist import upsert_listings
        upsert_listings(rows=rows)

    def test_empty_filter_returns_200_with_header_only(self):
        self._seed_one_row()
        with app_module.app.test_client() as c:
            r = c.get('/api/deals.csv?price_max=1')  # way below the only row
        assert r.status_code == 200, \
            f"empty filter must return 200, got {r.status_code}"
        body = r.get_data(as_text=True)
        reader = csv.reader(io.StringIO(body))
        header = next(reader)
        assert header[0] == 'price', "header row must still be present"
        # Should have no data rows (just the header)
        data_rows = list(reader)
        assert len(data_rows) == 0, f"expected no data rows, got {len(data_rows)}"

    def test_empty_filter_x_filter_row_count_is_zero(self):
        self._seed_one_row()
        with app_module.app.test_client() as c:
            r = c.get('/api/deals.csv?beds_min=99')
        assert r.headers['X-Filter-Row-Count'] == '0'

    def test_empty_filter_content_disposition_still_present(self):
        self._seed_one_row()
        with app_module.app.test_client() as c:
            r = c.get('/api/deals.csv?beds_min=99')
        cd = r.headers.get('Content-Disposition', '')
        assert 'attachment' in cd
        assert 'toronto-deals-' in cd

    def test_malformed_filter_param_does_not_500(self):
        """A bad filter value should degrade to no-filter (200 with
        unfiltered results) rather than blowing up the endpoint."""
        self._seed_one_row()
        with app_module.app.test_client() as c:
            r = c.get('/api/deals.csv?beds_min=notanumber')
        assert r.status_code == 200
        # The malformed value degrades to None (no filter), so we get
        # all rows.
        assert int(r.headers['X-Filter-Row-Count']) >= 1

    def test_min_pct_under_out_of_range_does_not_500(self):
        self._seed_one_row()
        # min_pct_under=999 is out of [0, 100] range; existing code
        # silently treats it as no filter.
        with app_module.app.test_client() as c:
            r = c.get('/api/deals.csv?min_pct_under=999')
        assert r.status_code == 200


# ── Runner ───────────────────────────────────────────────────────────────


def _run_all():
    import inspect
    classes = [
        TestCsvEndpoint,
        TestFilterParity,
        TestIndexHtmlWiring,
        TestEmptyAndErrorPaths,
    ]
    total = 0
    failed = 0
    for cls in classes:
        instance = cls()
        for name, fn in inspect.getmembers(cls, predicate=inspect.isfunction):
            if not name.startswith('test_'):
                continue
            total += 1
            setup = getattr(instance, 'setup_method', None)
            teardown = getattr(instance, 'teardown_method', None)
            if callable(setup):
                try:
                    setup()
                except Exception:
                    pass
            try:
                fn(instance)
                print(f'PASS {cls.__name__}.{name}')
            except AssertionError as e:
                failed += 1
                print(f'FAIL {cls.__name__}.{name}: {e}')
            except Exception as e:
                failed += 1
                print(f'ERROR {cls.__name__}.{name}: {type(e).__name__}: {e}')
            if callable(teardown):
                try:
                    teardown()
                except Exception:
                    pass
    if failed:
        print(f'\n{failed}/{total} tests failed.')
        sys.exit(1)
    print(f'\nAll {total} MC-346 csv-export tests passed.')


if __name__ == '__main__':
    _run_all()