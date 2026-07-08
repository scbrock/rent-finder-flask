"""
MC-332: With-photos filter on /api/deals + count in /api/meta + UI toggle.

Covers:
  - app._normalize_row() emits a 'has_image' boolean on every row
    (True iff image_url is non-empty OR image_urls has at least one http URL).
  - /api/deals?has_image=true filters rows that have at least one usable photo.
  - /api/deals?has_image=false / empty / missing returns all rows unchanged.
  - /api/meta includes with_photos_count driving the UI badge.
  - Edge cases:
      - image_url '' / None / whitespace-only -> has_image False (CL no-photo)
      - image_url present, image_urls empty -> has_image True (Kijiji w/ photo)
      - image_url empty, image_urls has http URL -> has_image True
      - image_urls with non-http (e.g. 'javascript:...') -> has_image False
      - mixed case (both populated) -> has_image True
  - Combination with other filters (source, only_new, price_dropped) works.
  - templates/index.html wiring:
      - checkbox element with id=has_image
      - buildParams includes has_image
      - parseQueryParams reads has_image
      - resetFilters clears has_image
      - updateFilterCount counts has_image
      - applySavedFilters loads has_image
      - listener wiring array includes 'has_image'
      - loadHasImageCountBadge exists and sets the badge text
"""

import os
import sys
import csv
import json
import tempfile

import pytest

# Ensure rent_finder is importable
RENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RENT_DIR)

import app as app_module  # noqa: E402


# ---------------------------------------------------------------------------
# Sample data — same pattern as test_mc316_source.py
# ---------------------------------------------------------------------------

SAMPLE_ROWS = [
    {
        # Kijiji with image_url + image_urls (typical MC-307 row)
        'source': 'Kijiji', 'price': '1500', 'beds': '1', 'baths': '1', 'sqft': '',
        'neighborhood': 'Downtown', 'days_ago': '3', 'is_stale': 'False',
        'link': 'https://kijiji.ca/x1',
        'image_url': 'https://img.kijiji/x1.jpg',
        'image_urls': '["https://img.kijiji/x1.jpg"]',
        'fair_value': '2200', 'pct_under': '31.8', 'score': '0.95',
        'freshness_boost': '0.15', 'final_score': '1.10', 'rank': '1', 'region': 'Downtown',
        'title': 'Beautiful 1BR apartment',
    },
    {
        # Craigslist with no images (typical MC-308 cold-cache row)
        'source': 'Craigslist', 'price': '1100', 'beds': '1', 'baths': '1', 'sqft': '',
        'neighborhood': 'Queen West', 'days_ago': '5', 'is_stale': 'False',
        'link': 'https://craigslist.org/y1',
        'image_url': '',
        'image_urls': '[]',
        'fair_value': '2000', 'pct_under': '45.0', 'score': '0.85',
        'freshness_boost': '0.15', 'final_score': '1.00', 'rank': '2', 'region': 'Downtown',
        'title': '1BR basement Queen West',
    },
    {
        # Craigslist with image_urls only (no image_url scalar)
        'source': 'Craigslist', 'price': '2200', 'beds': '2', 'baths': '1', 'sqft': '750',
        'neighborhood': 'King West', 'days_ago': '2', 'is_stale': 'False',
        'link': 'https://craigslist.org/y2',
        'image_url': '',
        'image_urls': '["https://images.craigslist/y2-a.jpg", "https://images.craigslist/y2-b.jpg"]',
        'fair_value': '3200', 'pct_under': '31.2', 'score': '0.80',
        'freshness_boost': '0.15', 'final_score': '0.95', 'rank': '3', 'region': 'Downtown',
        'title': 'Bright 2BR King West',
    },
    {
        # Kijiji with no images (rare — could be seller who didn't upload)
        'source': 'Kijiji', 'price': '900', 'beds': '0', 'baths': '1', 'sqft': '',
        'neighborhood': 'Entertainment District', 'days_ago': '7', 'is_stale': 'False',
        'link': 'https://kijiji.ca/x2',
        'image_url': '',
        'image_urls': '[]',
        'fair_value': '1700', 'pct_under': '47.0', 'score': '0.75',
        'freshness_boost': '0.15', 'final_score': '0.90', 'rank': '4', 'region': 'Downtown',
        'title': 'Studio downtown',
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def csv_deals_file(monkeypatch, tmp_path):
    """Write sample rows to a temp CSV and point app.DEALS_CSV at it.

    Forces SQLite path to a non-existent file so load_deals() falls through
    to the CSV fallback (matches the MC-316 fixture pattern).
    """
    p = tmp_path / 'deals_output.csv'
    with open(p, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=SAMPLE_ROWS[0].keys())
        writer.writeheader()
        writer.writerows(SAMPLE_ROWS)
    monkeypatch.setattr(app_module, 'DEALS_CSV', str(p))
    monkeypatch.setattr(app_module, 'DB_PATH', str(tmp_path / 'no-such-db.sqlite'))
    return p


@pytest.fixture
def client(csv_deals_file):
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# _normalize_row tests — has_image field
# ---------------------------------------------------------------------------

class TestNormalizeHasImage:
    """_normalize_row() must emit a 'has_image' boolean on every row."""

    def test_image_url_set_image_urls_set_true(self):
        out = app_module._normalize_row(dict(SAMPLE_ROWS[0]))
        assert out['has_image'] is True, "Kijiji with image_url should be has_image=True"

    def test_image_url_empty_image_urls_empty_false(self):
        row = dict(SAMPLE_ROWS[1])  # CL no images
        row['image_url'] = ''
        row['image_urls'] = '[]'
        out = app_module._normalize_row(row)
        assert out['has_image'] is False, "CL no-photo should be has_image=False"

    def test_image_url_missing_image_urls_only_true(self):
        row = dict(SAMPLE_ROWS[2])  # CL with image_urls but no image_url
        out = app_module._normalize_row(row)
        assert out['has_image'] is True, "any image_urls http URL should be has_image=True"

    def test_image_url_empty_list_image_urls_only_true(self):
        row = dict(SAMPLE_ROWS[2])
        row['image_url'] = ''
        out = app_module._normalize_row(row)
        assert out['has_image'] is True

    def test_no_images_at_all_false(self):
        row = dict(SAMPLE_ROWS[3])  # no images
        out = app_module._normalize_row(row)
        assert out['has_image'] is False

    def test_image_url_whitespace_only_and_no_urls_false(self):
        row = dict(SAMPLE_ROWS[0])
        row['image_url'] = '   '
        row['image_urls'] = '[]'
        out = app_module._normalize_row(row)
        assert out['has_image'] is False, \
            "whitespace-only image_url + empty image_urls should be False"

    def test_image_urls_contains_non_http_only_false(self):
        row = dict(SAMPLE_ROWS[0])
        row['image_url'] = ''
        row['image_urls'] = '["javascript:alert(1)", "data:image/png;base64,abc"]'
        out = app_module._normalize_row(row)
        assert out['has_image'] is False, "non-http image_urls should be False"

    def test_image_urls_with_one_http_and_others_true(self):
        row = dict(SAMPLE_ROWS[0])
        row['image_url'] = ''
        row['image_urls'] = '["javascript:x", "https://valid.example.com/x.jpg"]'
        out = app_module._normalize_row(row)
        assert out['has_image'] is True, "one http URL in image_urls is enough"

    def test_image_url_and_image_urls_both_populated_true(self):
        out = app_module._normalize_row(dict(SAMPLE_ROWS[0]))
        # Kijiji row has both - should be True
        assert out['has_image'] is True

    def test_image_url_present_image_urls_empty_true(self):
        row = dict(SAMPLE_ROWS[0])
        row['image_urls'] = '[]'
        out = app_module._normalize_row(row)
        assert out['has_image'] is True, "image_url alone is enough"

    def test_image_urls_present_as_list_type_true(self):
        row = dict(SAMPLE_ROWS[0])
        row['image_url'] = ''
        row['image_urls'] = ['https://example.com/photo.jpg']  # not a string
        out = app_module._normalize_row(row)
        assert out['has_image'] is True

    def test_image_urls_with_extra_non_string_entries_skipped(self):
        row = dict(SAMPLE_ROWS[0])
        row['image_url'] = ''
        row['image_urls'] = '["https://valid.com/x.jpg", 123, null, "https://also.valid/y.jpg"]'
        out = app_module._normalize_row(row)
        assert out['has_image'] is True


# ---------------------------------------------------------------------------
# /api/deals endpoint tests — has_image filter
# ---------------------------------------------------------------------------

class TestApiDealsHasImageField:
    """/api/deals returns has_image on every row."""

    def test_all_rows_have_has_image_field(self, client):
        rv = client.get('/api/deals')
        assert rv.status_code == 200
        data = rv.get_json()['deals']
        assert len(data) > 0
        for row in data:
            assert 'has_image' in row, f"row missing 'has_image': {list(row.keys())}"

    def test_has_image_is_bool_on_every_row(self, client):
        rv = client.get('/api/deals')
        data = rv.get_json()['deals']
        for row in data:
            assert isinstance(row['has_image'], bool), \
                f"has_image must be bool, got {type(row['has_image']).__name__}"


class TestApiDealsHasImageFilter:
    """/api/deals?has_image=true filters to only listings with photos."""

    def test_filter_true_excludes_no_photo_rows(self, client):
        rv = client.get('/api/deals?has_image=true')
        data = rv.get_json()['deals']
        # Sample data: row 0 (KJ +url), row 2 (CL +urls), row 1 (CL nothing), row 3 (KJ nothing)
        # So filtered = 2 rows
        assert len(data) == 2
        for row in data:
            assert row['has_image'] is True

    def test_no_filter_returns_all_rows(self, client):
        rv = client.get('/api/deals')
        data = rv.get_json()['deals']
        assert len(data) == 4

    def test_empty_string_returns_all_rows(self, client):
        rv = client.get('/api/deals?has_image=')
        data = rv.get_json()['deals']
        assert len(data) == 4

    def test_false_returns_all_rows(self, client):
        rv = client.get('/api/deals?has_image=false')
        data = rv.get_json()['deals']
        assert len(data) == 4

    def test_zero_returns_all_rows(self, client):
        rv = client.get('/api/deals?has_image=0')
        data = rv.get_json()['deals']
        assert len(data) == 4

    def test_invalid_value_falls_through(self, client):
        # Anything not in true/1/yes = no filter
        rv = client.get('/api/deals?has_image=maybe')
        data = rv.get_json()['deals']
        assert len(data) == 4

    def test_filter_combined_with_source_kijiji(self, client):
        # Kijiji with photos: only row 0
        rv = client.get('/api/deals?has_image=true&source=kijiji')
        data = rv.get_json()['deals']
        assert len(data) == 1
        assert data[0]['source'] == 'kijiji'
        assert data[0]['has_image'] is True

    def test_filter_combined_with_source_craigslist(self, client):
        # CL with photos: only row 2
        rv = client.get('/api/deals?has_image=true&source=craigslist')
        data = rv.get_json()['deals']
        assert len(data) == 1
        assert data[0]['source'] == 'craigslist'
        assert data[0]['has_image'] is True

    def test_filter_combined_with_beds(self, client):
        # 1BR with photos: row 0 only (row 1 has no photo and is 1BR)
        rv = client.get('/api/deals?has_image=true&beds_min=1&beds_max=1')
        data = rv.get_json()['deals']
        assert len(data) == 1
        assert data[0]['beds'] == 1
        assert data[0]['has_image'] is True

    def test_filter_combined_with_price(self, client):
        # Photos + price <= 2000: row 0 ($1500) only
        rv = client.get('/api/deals?has_image=true&price_max=2000')
        data = rv.get_json()['deals']
        assert len(data) == 1
        assert data[0]['price'] == 1500


class TestNoRegressions:
    """Existing endpoints behaviour preserved after has_image addition."""

    def test_index_still_renders(self, client):
        rv = client.get('/')
        assert rv.status_code == 200

    def test_meta_endpoint_still_works(self, client):
        rv = client.get('/api/meta')
        assert rv.status_code == 200

    def test_deals_export_csv_still_works(self, client):
        rv = client.get('/api/deals/export.csv')
        assert rv.status_code == 200


# ---------------------------------------------------------------------------
# /api/meta tests — with_photos_count
# ---------------------------------------------------------------------------

class TestApiMetaWithPhotosCount:
    """/api/meta must expose with_photos_count for the UI badge."""

    def test_meta_includes_with_photos_count_key(self, client):
        rv = client.get('/api/meta')
        data = rv.get_json()
        assert 'with_photos_count' in data, f"missing key. keys={list(data.keys())}"

    def test_meta_with_photos_count_matches_data(self, client):
        # Sample has 2 rows with photos
        rv = client.get('/api/meta')
        data = rv.get_json()
        assert data['with_photos_count'] == 2

    def test_meta_with_photos_count_is_int(self, client):
        rv = client.get('/api/meta')
        data = rv.get_json()
        assert isinstance(data['with_photos_count'], int)


# ---------------------------------------------------------------------------
# HTML wiring tests — checkbox + JS round-trip
# ---------------------------------------------------------------------------

class TestIndexHtmlHasImageWiring:
    """index.html must wire has_image through filter bar, JS, and badge."""

    def _read_index_html(self):
        idx_path = os.path.join(RENT_DIR, 'templates', 'index.html')
        with open(idx_path, encoding='utf-8') as f:
            return f.read()

    def test_index_has_has_image_checkbox(self):
        html = self._read_index_html()
        assert 'id="has_image"' in html, "missing #has_image checkbox"
        assert 'type="checkbox"' in html

    def test_index_has_has_image_toggle_wrapper(self):
        html = self._read_index_html()
        assert 'id="has_image_toggle"' in html, "missing #has_image_toggle wrapper"

    def test_index_has_has_image_count_badge_element(self):
        html = self._read_index_html()
        assert 'id="has_image_count"' in html, "missing #has_image_count badge"

    def test_index_buildparams_includes_has_image(self):
        html = self._read_index_html()
        assert "params.set('has_image', 'true')" in html, \
            "buildParams() missing has_image param"

    def test_index_parseparams_reads_has_image(self):
        html = self._read_index_html()
        # parseQueryParams() must read has_image from URL and toggle the checkbox
        assert "params.get('has_image')" in html, \
            "parseQueryParams() missing has_image read"
        assert "document.getElementById('has_image').checked = true" in html, \
            "parseQueryParams() missing checked = true"

    def test_index_updatefiltercount_counts_has_image(self):
        html = self._read_index_html()
        assert "document.getElementById('has_image').checked" in html
        # updateFilterCount must include has_image so the badge reflects it.
        # Look for a section that counts `has_image`.
        assert "if (document.getElementById('has_image').checked) count++" in html, \
            "updateFilterCount missing has_image ++"

    def test_index_resetfilters_clears_has_image(self):
        html = self._read_index_html()
        assert "document.getElementById('has_image').checked = false" in html, \
            "resetFilters() missing has_image clear"

    def test_index_applysavedfilters_handles_has_image(self):
        html = self._read_index_html()
        # applySavedFilters must reload has_image from saved filters
        assert "filters.has_image" in html, \
            "applySavedFilters missing has_image handling"

    def test_index_listener_array_includes_has_image(self):
        html = self._read_index_html()
        # The wiring array for filter-count listeners should include 'has_image'.
        # Look for the array literal (it appears just before the forEach call)
        # inside a window of ~500 chars before forEach.
        wiring_idx = html.find("forEach(function(id)")
        assert wiring_idx > 0, "missing forEach wiring call"
        start = max(0, wiring_idx - 500)
        section = html[start:wiring_idx + 100]
        assert "'has_image'" in section, \
            f"listener wiring array missing 'has_image' (window: {section!r})"

    def test_index_loadhasimagecountbadge_function_exists(self):
        html = self._read_index_html()
        assert 'function loadHasImageCountBadge' in html, \
            "missing loadHasImageCountBadge function"
        assert '/api/meta' in html, "loadHasImageCountBadge must hit /api/meta"

    def test_index_loadhasimagecountbadge_invoked_at_init(self):
        html = self._read_index_html()
        # Look for the badge call as part of init
        assert 'loadHasImageCountBadge()' in html, \
            "loadHasImageCountBadge() not called at init"

    def test_index_toggle_click_handler_exists(self):
        html = self._read_index_html()
        # Inline change handler that toggles .active class on the wrapper
        assert "document.getElementById('has_image').addEventListener" in html, \
            "missing change handler for #has_image"
        assert "has_image_toggle" in html
