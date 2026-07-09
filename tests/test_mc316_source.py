"""
Tests for MC-316: Surface listing source (Kijiji / Craigslist) in /api/deals
and add a source filter to the UI.

Coverage:
  - app._normalize_row() emits a lowercase 'source' field on every row
  - /api/deals response includes 'source' on all rows
  - GET /api/deals?source=kijiji returns only kijiji rows
  - GET /api/deals?source=craigslist returns only craigslist rows
  - GET /api/deals?source=all returns both
  - GET /api/deals?source=<missing> returns both (fallback)
  - Case-insensitive matching: ?source=KIJIJI works the same as ?source=kijiji
  - /api/meta response includes 'sources' list
  - templates/index.html has source filter wiring (dropdown + param plumbing)
"""

import os
import sys
import tempfile
import csv
import json

import pytest

# Ensure rent_finder is importable
RENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RENT_DIR)

import app as app_module  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ROWS = [
    {
        'source': 'Kijiji',
        'price': '1500', 'beds': '1', 'baths': '1', 'sqft': '',
        'neighborhood': 'Downtown', 'days_ago': '3', 'is_stale': 'False',
        'link': 'https://kijiji.ca/x1', 'image_url': 'https://img.kijiji/x1.jpg',
        'image_urls': '["https://img.kijiji/x1.jpg"]',
        'fair_value': '2200', 'pct_under': '31.8', 'score': '0.95',
        'freshness_boost': '0.15', 'final_score': '1.10', 'rank': '1', 'region': 'Downtown',
    },
    {
        'source': 'Craigslist',
        'price': '1100', 'beds': '1', 'baths': '1', 'sqft': '',
        'neighborhood': 'Queen West', 'days_ago': '5', 'is_stale': 'False',
        'link': 'https://craigslist.org/y1', 'image_url': '',
        'image_urls': '[]',
        'fair_value': '2000', 'pct_under': '45.0', 'score': '0.85',
        'freshness_boost': '0.15', 'final_score': '1.00', 'rank': '2', 'region': 'Downtown',
    },
    {
        'source': 'Craigslist',
        'price': '2200', 'beds': '2', 'baths': '1', 'sqft': '750',
        'neighborhood': 'King West', 'days_ago': '2', 'is_stale': 'False',
        'link': 'https://craigslist.org/y2', 'image_url': '',
        'image_urls': '[]',
        'fair_value': '3200', 'pct_under': '31.2', 'score': '0.80',
        'freshness_boost': '0.15', 'final_score': '0.95', 'rank': '3', 'region': 'Downtown',
    },
    {
        'source': 'Kijiji',
        'price': '900', 'beds': '0', 'baths': '1', 'sqft': '',
        'neighborhood': 'Entertainment District', 'days_ago': '7', 'is_stale': 'False',
        'link': 'https://kijiji.ca/x2', 'image_url': 'https://img.kijiji/x2.jpg',
        'image_urls': '["https://img.kijiji/x2.jpg"]',
        'fair_value': '1700', 'pct_under': '47.0', 'score': '0.75',
        'freshness_boost': '0.15', 'final_score': '0.90', 'rank': '4', 'region': 'Downtown',
    },
]


@pytest.fixture
def csv_deals_file(monkeypatch, tmp_path):
    """Write sample rows to a temp CSV and point app.DEALS_CSV at it."""
    p = tmp_path / 'deals_output.csv'
    with open(p, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=SAMPLE_ROWS[0].keys())
        writer.writeheader()
        writer.writerows(SAMPLE_ROWS)
    monkeypatch.setattr(app_module, 'DEALS_CSV', str(p))
    # Force DB path to a non-existent file so load_deals() hits CSV fallback
    monkeypatch.setattr(app_module, 'DB_PATH', str(tmp_path / 'no-such-db.sqlite'))
    return p


@pytest.fixture
def client(csv_deals_file):
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# _normalize_row tests
# ---------------------------------------------------------------------------

class TestNormalizeSourceField:
    """_normalize_row() must emit lowercase 'source' on every row."""

    def test_normalize_kijiji_lowercase(self):
        out = app_module._normalize_row(dict(SAMPLE_ROWS[0]))
        assert out['source'] == 'kijiji', f"expected 'kijiji', got {out['source']!r}"

    def test_normalize_craigslist_lowercase(self):
        out = app_module._normalize_row(dict(SAMPLE_ROWS[1]))
        assert out['source'] == 'craigslist', f"expected 'craigslist', got {out['source']!r}"

    def test_normalize_missing_source_empty_string(self):
        row = dict(SAMPLE_ROWS[0])
        del row['source']
        out = app_module._normalize_row(row)
        assert out['source'] == ''

    def test_normalize_empty_source_string(self):
        row = dict(SAMPLE_ROWS[0])
        row['source'] = ''
        out = app_module._normalize_row(row)
        assert out['source'] == ''

    def test_normalize_strips_whitespace(self):
        row = dict(SAMPLE_ROWS[0])
        row['source'] = '  Kijiji  '
        out = app_module._normalize_row(row)
        assert out['source'] == 'kijiji'

    def test_normalize_handles_already_lowercase(self):
        row = dict(SAMPLE_ROWS[0])
        row['source'] = 'craigslist'
        out = app_module._normalize_row(row)
        assert out['source'] == 'craigslist'


# ---------------------------------------------------------------------------
# /api/deals endpoint tests
# ---------------------------------------------------------------------------

class TestApiDealsSourceField:
    """/api/deals must include 'source' on every row."""

    def test_deals_all_have_source_field(self, client):
        rv = client.get('/api/deals')
        assert rv.status_code == 200
        data = rv.get_json()['deals']  # MC-319: /api/deals now returns {deals, total, ...}
        assert len(data) > 0
        for row in data:
            assert 'source' in row, f"row missing 'source': {list(row.keys())}"

    def test_deals_source_values_are_valid(self, client):
        rv = client.get('/api/deals')
        data = rv.get_json()['deals']
        sources = {row['source'] for row in data}
        assert sources <= {'kijiji', 'craigslist'}, f"unexpected sources: {sources}"


class TestApiDealsSourceFilter:
    """/api/deals?source=... filters by listing platform."""

    def test_filter_kijiji_returns_only_kijiji(self, client):
        rv = client.get('/api/deals?source=kijiji')
        data = rv.get_json()['deals']
        assert len(data) == 2
        for row in data:
            assert row['source'] == 'kijiji'

    def test_filter_craigslist_returns_only_craigslist(self, client):
        rv = client.get('/api/deals?source=craigslist')
        data = rv.get_json()['deals']
        assert len(data) == 2
        for row in data:
            assert row['source'] == 'craigslist'

    def test_filter_all_returns_both(self, client):
        rv = client.get('/api/deals?source=all')
        data = rv.get_json()['deals']
        assert len(data) == 4
        sources = {row['source'] for row in data}
        assert sources == {'kijiji', 'craigslist'}

    def test_no_filter_returns_both(self, client):
        rv = client.get('/api/deals')
        data = rv.get_json()['deals']
        assert len(data) == 4

    def test_filter_empty_string_returns_both(self, client):
        rv = client.get('/api/deals?source=')
        data = rv.get_json()['deals']
        assert len(data) == 4

    def test_filter_case_insensitive_uppercase(self, client):
        rv = client.get('/api/deals?source=KIJIJI')
        data = rv.get_json()['deals']
        assert len(data) == 2
        for row in data:
            assert row['source'] == 'kijiji'

    def test_filter_case_insensitive_mixed(self, client):
        rv = client.get('/api/deals?source=CraigsList')
        data = rv.get_json()['deals']
        assert len(data) == 2
        for row in data:
            assert row['source'] == 'craigslist'

    def test_filter_unknown_value_returns_empty_or_fallback(self, client):
        # Unknown source → empty list (no rows match)
        rv = client.get('/api/deals?source=facebook')
        data = rv.get_json()['deals']
        assert data == []

    def test_filter_combined_with_other_filters(self, client):
        # kijiji + 1 BR → 1 row
        rv = client.get('/api/deals?source=kijiji&beds_min=1&beds_max=1')
        data = rv.get_json()['deals']
        assert len(data) == 1
        assert data[0]['source'] == 'kijiji'
        assert data[0]['beds'] == 1


# ---------------------------------------------------------------------------
# /api/meta tests
# ---------------------------------------------------------------------------

class TestApiMetaSourceField:
    """/api/meta must expose available sources for UI dropdown population."""

    def test_meta_includes_sources(self, client):
        rv = client.get('/api/meta')
        assert rv.status_code == 200
        data = rv.get_json()
        assert 'sources' in data, f"sources key missing: {list(data.keys())}"

    def test_meta_sources_are_sorted_and_complete(self, client):
        rv = client.get('/api/meta')
        data = rv.get_json()
        assert data['sources'] == ['craigslist', 'kijiji']


# ---------------------------------------------------------------------------
# /api/deals/geo and other endpoints stay backward-compatible
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Existing endpoints must still work with source field added."""

    def test_index_still_renders(self, client):
        rv = client.get('/')
        assert rv.status_code == 200

    def test_geo_endpoint_still_works(self, client):
        rv = client.get('/api/deals/geo')
        # 200 or 404 is fine — we just need to confirm no crash
        assert rv.status_code in (200, 404)


# ---------------------------------------------------------------------------
# HTML wiring tests
# ---------------------------------------------------------------------------

class TestIndexHtmlWiring:
    """index.html must have the source dropdown and JS wiring."""

    def test_index_has_source_dropdown(self):
        idx_path = os.path.join(RENT_DIR, 'templates', 'index.html')
        with open(idx_path, encoding='utf-8') as f:
            html = f.read()
        assert 'id="source"' in html, "missing #source dropdown"
        assert '<option value="kijiji">' in html, "missing kijiji option"
        assert '<option value="craigslist">' in html, "missing craigslist option"

    def test_index_buildparams_includes_source(self):
        idx_path = os.path.join(RENT_DIR, 'templates', 'index.html')
        with open(idx_path, encoding='utf-8') as f:
            html = f.read()
        # buildParams() must set 'source' on the URLSearchParams when non-empty
        assert "params.set('source', source)" in html

    def test_index_parseparams_includes_source(self):
        idx_path = os.path.join(RENT_DIR, 'templates', 'index.html')
        with open(idx_path, encoding='utf-8') as f:
            html = f.read()
        # parseQueryParams() must read source from URL
        assert "params.get('source')" in html

    def test_index_resetfilters_includes_source(self):
        idx_path = os.path.join(RENT_DIR, 'templates', 'index.html')
        with open(idx_path, encoding='utf-8') as f:
            html = f.read()
        # resetFilters() must reset the source dropdown
        assert "document.getElementById('source').selectedIndex = 0" in html

    def test_index_source_badge_styling(self):
        idx_path = os.path.join(RENT_DIR, 'templates', 'index.html')
        with open(idx_path, encoding='utf-8') as f:
            html = f.read()
        assert '.source-badge' in html, "missing source-badge CSS class"
        assert '.source-kijiji' in html, "missing source-kijiji CSS class"
        assert '.source-cl' in html, "missing source-cl CSS class"

    def test_index_renders_source_badge_in_row(self):
        idx_path = os.path.join(RENT_DIR, 'templates', 'index.html')
        with open(idx_path, encoding='utf-8') as f:
            html = f.read()
        # srcTag is appended to neighbourhood cell
        assert 'srcTag' in html
        assert "srcRaw === 'kijiji'" in html
        assert "srcRaw === 'craigslist'" in html