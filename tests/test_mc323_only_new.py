"""
Tests for MC-323: "Only NEW (6h)" filter on /api/deals + UI toggle.

is_new is already populated by MC-264 (1 for first 6hrs after first_seen)
and shown as the ✨ NEW badge in the deals table. This ticket adds:
  - /api/deals?is_new=true server-side filter (returns only is_new=1 rows)
  - /api/meta response includes 'new_count' field
  - templates/index.html: Only NEW toggle button + JS round-trip plumbing

Coverage:
  - _normalize_row() emits boolean is_new on every row (regression guard for MC-264)
  - GET /api/deals (no param) returns all rows (no behavior change)
  - GET /api/deals?is_new=true returns only is_new=1 rows
  - GET /api/deals?is_new=false returns all rows (explicit false)
  - GET /api/deals?is_new=1 also works (boolean-ish accept)
  - Combined with source: ?is_new=true&source=kijiji → only NEW kijiji
  - Combined with beds_min: ?is_new=true&beds_min=2 → only NEW 2+ BR
  - /api/meta response includes 'new_count' field
  - new_count counts is_new=1 rows in the underlying data set
  - Empty data set still returns new_count=0 (no KeyError)
  - index.html: toggle markup present, buildParams / parseQueryParams /
    resetFilters / updateFilterCount / applySavedFilters / describeFilters
    all wire 'only_new' / 'is_new' consistently.
"""

import os
import sys
import csv

import pytest

# Ensure rent_finder is importable
RENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RENT_DIR)

import app as app_module  # noqa: E402


# ---------------------------------------------------------------------------
# Sample data — 5 rows, 3 NEW + 2 OLD
# ---------------------------------------------------------------------------

def _row(idx, *, source='Kijiji', is_new='1', days_ago='1', neighborhood='Downtown',
         price='1500', beds='1', baths='1', region='Downtown'):
    """Build a CSV-shaped row with sensible defaults."""
    return {
        'source': source,
        'price': price, 'beds': beds, 'baths': baths, 'sqft': '',
        'neighborhood': neighborhood, 'days_ago': days_ago, 'is_stale': 'False',
        'link': f'https://example.com/{idx}', 'image_url': '',
        'image_urls': '[]',
        'fair_value': '2000', 'pct_under': '25.0', 'score': '0.85',
        'freshness_boost': '0.15', 'final_score': '1.00', 'rank': str(idx),
        'region': region,
        'is_new': is_new,
    }


SAMPLE_ROWS = [
    _row(1, source='Kijiji',     is_new='1', days_ago='1',  neighborhood='Downtown',
         price='1500', beds='1'),                 # NEW kijiji 1BR downtown
    _row(2, source='Craigslist', is_new='1', days_ago='2',  neighborhood='Queen West',
         price='1100', beds='1'),                 # NEW craigslist 1BR
    _row(3, source='Craigslist', is_new='1', days_ago='3',  neighborhood='King West',
         price='2200', beds='2'),                 # NEW craigslist 2BR
    _row(4, source='Kijiji',     is_new='0', days_ago='15', neighborhood='Downtown',
         price='900', beds='0'),                  # OLD kijiji studio
    _row(5, source='Kijiji',     is_new='0', days_ago='20', neighborhood='Liberty Village',
         price='3000', beds='2'),                 # OLD kijiji 2BR
]

NEW_COUNT_EXPECTED = 3
TOTAL_COUNT_EXPECTED = 5


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
# _normalize_row tests (regression for MC-264 is_new field)
# ---------------------------------------------------------------------------

class TestNormalizeIsNewField:
    """_normalize_row() must emit a boolean 'is_new' field on every row."""

    def test_normalize_is_new_true_when_one(self):
        out = app_module._normalize_row(dict(SAMPLE_ROWS[0]))
        assert out['is_new'] is True, f"expected True, got {out['is_new']!r}"

    def test_normalize_is_new_false_when_zero(self):
        out = app_module._normalize_row(dict(SAMPLE_ROWS[3]))
        assert out['is_new'] is False, f"expected False, got {out['is_new']!r}"

    def test_normalize_is_new_handles_string_true(self):
        row = dict(SAMPLE_ROWS[0])
        row['is_new'] = 'true'
        out = app_module._normalize_row(row)
        assert out['is_new'] is True

    def test_normalize_is_new_handles_empty_string(self):
        row = dict(SAMPLE_ROWS[0])
        row['is_new'] = ''
        out = app_module._normalize_row(row)
        assert out['is_new'] is False

    def test_normalize_is_new_handles_missing(self):
        row = dict(SAMPLE_ROWS[0])
        del row['is_new']
        out = app_module._normalize_row(row)
        assert out['is_new'] is False


# ---------------------------------------------------------------------------
# /api/deals endpoint tests — is_new filter
# ---------------------------------------------------------------------------

class TestApiDealsIsNewFilter:
    """/api/deals?is_new=... filters by MC-264 freshness flag."""

    def test_default_returns_all_rows(self, client):
        """No param: behavior unchanged — every row is returned."""
        rv = client.get('/api/deals')
        assert rv.status_code == 200
        payload = rv.get_json()
        assert payload['total'] == TOTAL_COUNT_EXPECTED
        assert len(payload['deals']) == TOTAL_COUNT_EXPECTED

    def test_is_new_true_returns_only_new(self, client):
        rv = client.get('/api/deals?is_new=true')
        payload = rv.get_json()
        assert payload['total'] == NEW_COUNT_EXPECTED
        for row in payload['deals']:
            assert row['is_new'] is True

    def test_is_new_one_returns_only_new(self, client):
        """Boolean-ish accepted values (1, yes) also enable the filter."""
        rv = client.get('/api/deals?is_new=1')
        payload = rv.get_json()
        assert payload['total'] == NEW_COUNT_EXPECTED

    def test_is_new_yes_returns_only_new(self, client):
        rv = client.get('/api/deals?is_new=yes')
        payload = rv.get_json()
        assert payload['total'] == NEW_COUNT_EXPECTED

    def test_is_new_false_returns_all_rows(self, client):
        """Explicit false is treated as 'no filter' — same as default."""
        rv = client.get('/api/deals?is_new=false')
        payload = rv.get_json()
        assert payload['total'] == TOTAL_COUNT_EXPECTED

    def test_is_new_empty_string_returns_all_rows(self, client):
        """Empty value: no filter applied (back-compat with missing param)."""
        rv = client.get('/api/deals?is_new=')
        payload = rv.get_json()
        assert payload['total'] == TOTAL_COUNT_EXPECTED

    def test_is_new_zero_returns_all_rows(self, client):
        """Explicit 0 / no: no filter applied."""
        rv = client.get('/api/deals?is_new=0')
        payload = rv.get_json()
        assert payload['total'] == TOTAL_COUNT_EXPECTED

    def test_is_new_garbage_value_returns_all_rows(self, client):
        """Unknown values fall back to no-filter (safer than 500)."""
        rv = client.get('/api/deals?is_new=banana')
        payload = rv.get_json()
        assert payload['total'] == TOTAL_COUNT_EXPECTED

    def test_combined_is_new_and_source(self, client):
        """?is_new=true&source=kijiji → only NEW kijiji listings."""
        rv = client.get('/api/deals?is_new=true&source=kijiji')
        payload = rv.get_json()
        # Of the 3 NEW rows, only 1 is kijiji
        assert payload['total'] == 1
        assert payload['deals'][0]['source'] == 'kijiji'
        assert payload['deals'][0]['is_new'] is True

    def test_combined_is_new_and_beds(self, client):
        """?is_new=true&beds_min=2 → only NEW 2+ BR listings."""
        rv = client.get('/api/deals?is_new=true&beds_min=2')
        payload = rv.get_json()
        # Of the 3 NEW rows, only the 2BR is >= 2
        assert payload['total'] == 1
        assert payload['deals'][0]['beds'] == 2
        assert payload['deals'][0]['is_new'] is True

    def test_combined_is_new_and_price_max(self, client):
        """?is_new=true&price_max=1500 → only NEW listings at <= $1500."""
        rv = client.get('/api/deals?is_new=true&price_max=1500')
        payload = rv.get_json()
        # Of the 3 NEW rows, $1500 (==), $1100 (<=) qualify; $2200 does not
        assert payload['total'] == 2
        for row in payload['deals']:
            assert row['price'] <= 1500
            assert row['is_new'] is True


# ---------------------------------------------------------------------------
# /api/meta new_count field
# ---------------------------------------------------------------------------

class TestApiMetaNewCount:
    """/api/meta must include 'new_count' for the Only NEW badge."""

    def test_meta_includes_new_count_key(self, client):
        rv = client.get('/api/meta')
        assert rv.status_code == 200
        data = rv.get_json()
        assert 'new_count' in data, f"new_count missing: {list(data.keys())}"

    def test_meta_new_count_matches_is_new_total(self, client):
        rv = client.get('/api/meta')
        data = rv.get_json()
        assert data['new_count'] == NEW_COUNT_EXPECTED

    def test_meta_preserves_existing_keys(self, client):
        """Regression guard: existing keys must still be present."""
        rv = client.get('/api/meta')
        data = rv.get_json()
        for required in ('beds', 'price', 'baths', 'regions', 'sources', 'neighborhoods'):
            assert required in data, f"missing pre-existing key {required!r}"


# ---------------------------------------------------------------------------
# Empty-data-set robustness
# ---------------------------------------------------------------------------

class TestEmptyDataSet:
    """When load_deals() returns no rows, /api/meta must still work."""

    def test_meta_empty_returns_zero_new_count(self, monkeypatch, tmp_path):
        # Write a CSV with only the header so load_deals() yields []
        p = tmp_path / 'deals_output.csv'
        with open(p, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(SAMPLE_ROWS[0].keys()))
            writer.writeheader()
        monkeypatch.setattr(app_module, 'DEALS_CSV', str(p))
        monkeypatch.setattr(app_module, 'DB_PATH', str(tmp_path / 'no-such-db.sqlite'))

        app_module.app.config['TESTING'] = True
        with app_module.app.test_client() as c:
            rv = c.get('/api/meta')
            assert rv.status_code == 200
            data = rv.get_json()
            assert data.get('new_count') == 0, f"expected 0, got {data.get('new_count')!r}"


# ---------------------------------------------------------------------------
# HTML wiring tests
# ---------------------------------------------------------------------------

class TestIndexHtmlOnlyNewWiring:
    """index.html must have the Only NEW toggle and JS round-trip plumbing."""

    @pytest.fixture
    def html(self):
        idx_path = os.path.join(RENT_DIR, 'templates', 'index.html')
        with open(idx_path, encoding='utf-8') as f:
            return f.read()

    def test_toggle_input_present(self, html):
        assert 'id="only_new"' in html, "missing #only_new checkbox"
        assert 'id="only_new_toggle"' in html, "missing #only_new_toggle label"

    def test_toggle_label_mentions_new(self, html):
        assert 'Only NEW' in html, "missing 'Only NEW' label text"

    def test_count_badge_element_present(self, html):
        assert 'id="only_new_count"' in html, "missing #only_new_count badge element"

    def test_buildparams_sets_is_new(self, html):
        """buildParams() must serialize the toggle to ?is_new=true."""
        assert "params.set('is_new', 'true')" in html, \
            "buildParams() doesn't set is_new=true when toggle is on"

    def test_parseparams_reads_is_new(self, html):
        """parseQueryParams() must restore the toggle from URL on reload."""
        assert "params.get('is_new') === 'true'" in html, \
            "parseQueryParams() doesn't read is_new from URL"

    def test_resetfilters_clears_toggle(self, html):
        """resetFilters() must clear the Only NEW toggle along with others."""
        assert "document.getElementById('only_new').checked = false" in html, \
            "resetFilters() doesn't clear #only_new"

    def test_updatefiltercount_counts_only_new(self, html):
        """updateFilterCount() must increment when Only NEW is checked.

        Extract the function body (single-brace, no nested braces — same
        approach as the MC-318 test) and assert the increment statement
        is present AFTER comment-stripping so commented-out lines can't
        satisfy the assertion.
        """
        m = html_text(html).search(r'function\s+updateFilterCount\s*\(\s*\)\s*\{[\s\S]*?\n\s*\}')
        assert m, "could not locate updateFilterCount function body"
        body = strip_js_comments(m.group(0))
        re_only_new = r'if\s*\(\s*document\.getElementById\([\'"]only_new[\'"]\)\.checked\s*\)\s*count\+\+'
        assert re.search(re_only_new, body), \
            "updateFilterCount body lacks `if (document.getElementById('only_new').checked) count++`"

    def test_wiring_array_includes_only_new(self, html):
        """Bottom-of-file wiring array must include 'only_new' so badge auto-updates."""
        m = re.search(
            r"\[\s*['\"]beds_min['\"][^\]]*\]",
            html_text(html).raw,
        )
        assert m, "wiring array not found"
        assert "'only_new'" in m.group(0) or '"only_new"' in m.group(0), \
            "wiring array missing 'only_new'"

    def test_save_search_round_trip_includes_is_new(self, html):
        """MC-322 round-trip: applySavedFilters / getCurrentFilterStateAsObject
        / describeFilters must all know about the Only NEW state.
        """
        # applySavedFilters reads filters.is_new === 'true'
        assert "filters.is_new === 'true'" in html, \
            "applySavedFilters() doesn't read filters.is_new"
        # getCurrentFilterStateAsObject writes out.is_new = ...
        assert "out.is_new = document.getElementById('only_new')" in html, \
            "getCurrentFilterStateAsObject() doesn't capture only_new state"
        # describeFilters includes "Only NEW (6h)" in summary
        assert "Only NEW (6h)" in html, \
            "describeFilters() doesn't surface Only NEW in summary"

    def test_only_new_active_class_styling(self, html):
        """CSS for the active state of the toggle (matches hide_stale pattern)."""
        assert '.only_new_toggle' in html or '#only_new_toggle' in html, \
            "missing CSS rule for #only_new_toggle active state"

    def test_load_new_count_badge_function_present(self, html):
        """Function to populate '(N new)' badge from /api/meta is wired in."""
        assert 'loadNewCountBadge' in html, \
            "missing loadNewCountBadge() function — count badge won't render"

    def test_saved_searches_page_renders_only_new_tag(self):
        """The /saved-searches management page must render an 'Only NEW' tag
        when the saved filter snapshot has is_new === 'true'."""
        ss_path = os.path.join(RENT_DIR, 'templates', 'saved_searches.html')
        with open(ss_path, encoding='utf-8') as f:
            ss_html = f.read()
        # JS tag-emit branch
        assert "fd.is_new === 'true'" in ss_html, \
            "saved_searches.html doesn't read fd.is_new === 'true' for tag emission"
        assert 'Only NEW (6h)' in ss_html, \
            "saved_searches.html doesn't render 'Only NEW (6h)' tag text"
        # CSS class for the tag
        assert '.only-new-tag' in ss_html, \
            "saved_searches.html missing .only-new-tag CSS class"


# Tiny helper class so the test can call .search / .raw without re-importing re everywhere.
import re  # noqa: E402  (kept here so the helper has it in scope)


def html_text(s):
    """No-op wrapper so test methods read like ``html_text(self.html).search(...)``."""
    class _W:
        def __init__(self, raw): self.raw = raw
        def search(self, pattern): return re.search(pattern, self.raw)
    return _W(s)


def strip_js_comments(s):
    """Strip JS line + block comments (matches the MC-318 helper)."""
    s = re.sub(r'/\*[\s\S]*?\*/', '', s)
    s = re.sub(r'//.*$', '', s, flags=re.MULTILINE)
    return s