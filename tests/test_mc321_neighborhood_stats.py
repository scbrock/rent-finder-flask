"""
Tests for MC-321: Neighborhood stats drill-down endpoint + drill-down page +
table link.

Coverage:
  - _slugify: simple, empty/None, special chars, multi-word
  - _median: empty, odd, even, unsorted
  - _safe_float: None / empty / 'None' / nan / numeric / inf
  - _neighborhood_stats: shape, median accuracy, beds breakdown, top-5 selection,
    empty case, unknown name
  - _neighborhoods_summary: shape, sorted output, count + median accuracy
  - _slug_to_neighborhood: known slug, unknown, empty
  - _normalize_row: adds neighborhood_slug
  - /api/meta: includes 'neighborhoods' key with correct shape
  - /api/neighborhoods/<slug>/stats: 200 for known, 404 for unknown
  - /neighborhood/<slug>: 200 for known, 200 (page) for unknown (client-side 404 handling)
  - /api/deals response: every row has neighborhood_slug
  - index.html: drill-down link wiring (neighborhood_slug rendered in row template)
  - index.html: nbhd-stats-link CSS class exists
"""

import os
import sys
import csv
import tempfile

import pytest

# Ensure rent_finder is importable
RENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RENT_DIR)

import app as app_module  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic data: 4 listings in "Bay Street Corridor", 1 in "Other"
# ---------------------------------------------------------------------------

SYNTH_ROWS = [
    {
        'source': 'kijiji', 'price': 2000, 'beds': 1, 'baths': 1, 'sqft': '600',
        'neighbourhood': 'Bay Street Corridor', 'days_ago': 3, 'is_stale': False,
        'link': 'https://kijiji.ca/a', 'image_url': 'https://img/a.jpg',
        'image_urls': ['https://img/a.jpg'],
        'fair_value': 3000, 'pct_under': 33.3, 'score': 0.8,
        'final_score': 1.10, 'region': 'Downtown',
        'listing_id': 'kijiji.ca/a', 'title': 'Bay 1BR A',
    },
    {
        'source': 'craigslist', 'price': 2500, 'beds': 1, 'baths': 1, 'sqft': '700',
        'neighbourhood': 'Bay Street Corridor', 'days_ago': 5, 'is_stale': False,
        'link': 'https://craigslist.org/b', 'image_url': '',
        'image_urls': [],
        'fair_value': 3000, 'pct_under': 16.7, 'score': 0.7,
        'final_score': 0.85, 'region': 'Downtown',
        'listing_id': 'craigslist.org/b', 'title': 'Bay 1BR B',
    },
    {
        'source': 'kijiji', 'price': 3500, 'beds': 2, 'baths': 1, 'sqft': '900',
        'neighbourhood': 'Bay Street Corridor', 'days_ago': 2, 'is_stale': False,
        'link': 'https://kijiji.ca/c', 'image_url': '',
        'image_urls': [],
        'fair_value': 4000, 'pct_under': 12.5, 'score': 0.5,
        'final_score': 0.65, 'region': 'Downtown',
        'listing_id': 'kijiji.ca/c', 'title': 'Bay 2BR C',
    },
    {
        'source': 'craigslist', 'price': 1500, 'beds': 0, 'baths': 1, 'sqft': '',
        'neighbourhood': 'Bay Street Corridor', 'days_ago': 1, 'is_stale': False,
        'link': 'https://craigslist.org/d', 'image_url': '',
        'image_urls': [],
        'fair_value': 2000, 'pct_under': 25.0, 'score': 0.4,
        'final_score': 0.55, 'region': 'Downtown',
        'listing_id': 'craigslist.org/d', 'title': 'Bay Studio D',
    },
    {
        'source': 'kijiji', 'price': 9999, 'beds': 1, 'baths': 1, 'sqft': '500',
        'neighbourhood': 'Other', 'days_ago': 4, 'is_stale': False,
        'link': 'https://kijiji.ca/z', 'image_url': '',
        'image_urls': [],
        'fair_value': 11000, 'pct_under': 9.1, 'score': 0.9,
        'final_score': 1.05, 'region': 'Midtown',
        'listing_id': 'kijiji.ca/z', 'title': 'Other 1BR',
    },
]


# Raw CSV-style rows (US-spelling `neighborhood` + string numerics) for the
# CSV-fixture integration test + the _normalize_row tests.
RAW_ROWS = [
    {
        'source': 'Kijiji', 'price': '2000', 'beds': '1', 'baths': '1', 'sqft': '600',
        'neighborhood': 'Bay Street Corridor', 'days_ago': '3', 'is_stale': 'False',
        'link': 'https://kijiji.ca/a', 'image_url': 'https://img/a.jpg',
        'image_urls': '["https://img/a.jpg"]',
        'fair_value': '3000', 'pct_under': '33.3', 'score': '0.8',
        'freshness_boost': '0.15', 'final_score': '1.10', 'rank': '1', 'region': 'Downtown',
        'url': 'https://kijiji.ca/a', 'title': 'Bay 1BR A',
    },
    {
        'source': 'Craigslist', 'price': '2500', 'beds': '1', 'baths': '1', 'sqft': '700',
        'neighborhood': 'Bay Street Corridor', 'days_ago': '5', 'is_stale': 'False',
        'link': 'https://craigslist.org/b', 'image_url': '',
        'image_urls': '[]',
        'fair_value': '3000', 'pct_under': '16.7', 'score': '0.7',
        'freshness_boost': '0.15', 'final_score': '0.85', 'rank': '2', 'region': 'Downtown',
        'url': 'https://craigslist.org/b', 'title': 'Bay 1BR B',
    },
    {
        'source': 'Kijiji', 'price': '3500', 'beds': '2', 'baths': '1', 'sqft': '900',
        'neighborhood': 'Bay Street Corridor', 'days_ago': '2', 'is_stale': 'False',
        'link': 'https://kijiji.ca/c', 'image_url': '',
        'image_urls': '[]',
        'fair_value': '4000', 'pct_under': '12.5', 'score': '0.5',
        'freshness_boost': '0.15', 'final_score': '0.65', 'rank': '3', 'region': 'Downtown',
        'url': 'https://kijiji.ca/c', 'title': 'Bay 2BR C',
    },
    {
        'source': 'Craigslist', 'price': '1500', 'beds': '0', 'baths': '1', 'sqft': '',
        'neighborhood': 'Bay Street Corridor', 'days_ago': '1', 'is_stale': 'False',
        'link': 'https://craigslist.org/d', 'image_url': '',
        'image_urls': '[]',
        'fair_value': '2000', 'pct_under': '25.0', 'score': '0.4',
        'freshness_boost': '0.15', 'final_score': '0.55', 'rank': '4', 'region': 'Downtown',
        'url': 'https://craigslist.org/d', 'title': 'Bay Studio D',
    },
    {
        'source': 'Kijiji', 'price': '9999', 'beds': '1', 'baths': '1', 'sqft': '500',
        'neighborhood': 'Other', 'days_ago': '4', 'is_stale': 'False',
        'link': 'https://kijiji.ca/z', 'image_url': '',
        'image_urls': '[]',
        'fair_value': '11000', 'pct_under': '9.1', 'score': '0.9',
        'freshness_boost': '0.15', 'final_score': '1.05', 'rank': '5', 'region': 'Midtown',
        'url': 'https://kijiji.ca/z', 'title': 'Other 1BR',
    },
]


@pytest.fixture
def csv_deals_file(monkeypatch, tmp_path):
    """Write sample rows to a temp CSV and point app.DEALS_CSV at it."""
    p = tmp_path / 'deals_output.csv'
    fields = list(RAW_ROWS[0].keys())
    with open(p, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(RAW_ROWS)
    monkeypatch.setattr(app_module, 'DEALS_CSV', str(p))
    monkeypatch.setattr(app_module, 'DB_PATH', str(tmp_path / 'no-such-db.sqlite'))
    return p


@pytest.fixture
def client(csv_deals_file):
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_simple(self):
        assert app_module._slugify('Bay Street Corridor') == 'bay-street-corridor'

    def test_empty_string(self):
        assert app_module._slugify('') == ''

    def test_none(self):
        assert app_module._slugify(None) == ''

    def test_special_chars(self):
        # Parentheses, punctuation, apostrophes all become hyphens
        assert app_module._slugify('Niagara (St. Lawrence)!') == 'niagara-st-lawrence'

    def test_apostrophe(self):
        assert app_module._slugify("King's Crown") == 'king-s-crown'

    def test_whitespace_stripping(self):
        assert app_module._slugify('  Trinity-Bellwoods  ') == 'trinity-bellwoods'

    def test_lowercases(self):
        assert app_module._slugify('the annex') == 'the-annex'

    def test_collapse_runs_of_separators(self):
        assert app_module._slugify('123 -- Main St.') == '123-main-st'


# ---------------------------------------------------------------------------
# _median
# ---------------------------------------------------------------------------

class TestMedian:
    def test_empty_returns_none(self):
        assert app_module._median([]) is None

    def test_single_value(self):
        assert app_module._median([42]) == 42

    def test_odd_count(self):
        assert app_module._median([1, 2, 3]) == 2

    def test_even_count(self):
        assert app_module._median([1, 2, 3, 4]) == 2.5

    def test_unsorted_input(self):
        # Should sort internally
        assert app_module._median([4, 1, 3, 2]) == 2.5


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_none(self):
        assert app_module._safe_float(None) is None

    def test_empty_string(self):
        assert app_module._safe_float('') is None

    def test_none_string(self):
        assert app_module._safe_float('None') is None

    def test_nan_string(self):
        assert app_module._safe_float('nan') is None

    def test_numeric(self):
        assert app_module._safe_float(1.5) == 1.5

    def test_numeric_string(self):
        assert app_module._safe_float('2.0') == 2.0

    def test_inf_returns_none(self):
        assert app_module._safe_float(float('inf')) is None

    def test_neg_inf_returns_none(self):
        assert app_module._safe_float(float('-inf')) is None

    def test_nan_returns_none(self):
        import math
        assert app_module._safe_float(math.nan) is None

    def test_garbage_string(self):
        assert app_module._safe_float('not a number') is None


# ---------------------------------------------------------------------------
# _neighborhood_stats
# ---------------------------------------------------------------------------

class TestNeighborhoodStats:
    """Verify aggregation logic for a single neighbourhood."""

    def test_count(self):
        stats = app_module._neighborhood_stats(SYNTH_ROWS, 'Bay Street Corridor')
        assert stats is not None
        assert stats['count'] == 4

    def test_slug(self):
        stats = app_module._neighborhood_stats(SYNTH_ROWS, 'Bay Street Corridor')
        assert stats['slug'] == 'bay-street-corridor'

    def test_neighborhood_name_preserved(self):
        stats = app_module._neighborhood_stats(SYNTH_ROWS, 'Bay Street Corridor')
        assert stats['neighborhood'] == 'Bay Street Corridor'

    def test_median_price_even(self):
        # 4 listings, prices = 2000, 2500, 3500, 1500 -> sorted 1500,2000,2500,3500 -> median=(2000+2500)/2=2250
        stats = app_module._neighborhood_stats(SYNTH_ROWS, 'Bay Street Corridor')
        assert stats['median_price'] == 2250.0

    def test_min_max_price(self):
        stats = app_module._neighborhood_stats(SYNTH_ROWS, 'Bay Street Corridor')
        assert stats['min_price'] == 1500
        assert stats['max_price'] == 3500

    def test_median_price_per_sqft(self):
        # Listings with sqft: a (2000/600=3.33), b (2500/700=3.57), c (3500/900=3.89)
        # d has empty sqft -> excluded. sorted [3.33, 3.57, 3.89] -> median = 3.57
        stats = app_module._neighborhood_stats(SYNTH_ROWS, 'Bay Street Corridor')
        assert stats['median_price_per_sqft'] is not None
        assert round(stats['median_price_per_sqft'], 2) == 3.57

    def test_beds_breakdown(self):
        stats = app_module._neighborhood_stats(SYNTH_ROWS, 'Bay Street Corridor')
        assert stats['beds_breakdown'] == {'0': 1, '1': 2, '2': 1}

    def test_top_deals_sorted_by_final_score_desc(self):
        stats = app_module._neighborhood_stats(SYNTH_ROWS, 'Bay Street Corridor')
        scores = [d['final_score'] for d in stats['top_deals']]
        assert scores == sorted(scores, reverse=True)

    def test_top_deals_excludes_zero_scores(self):
        # Add a zero-score listing to confirm it's filtered out
        rows = list(SYNTH_ROWS) + [{
            'source': 'kijiji', 'price': 1100, 'beds': 0, 'baths': 1, 'sqft': '',
            'neighbourhood': 'Bay Street Corridor', 'days_ago': 30, 'is_stale': True,
            'link': 'https://kijiji.ca/zero', 'image_url': '', 'image_urls': [],
            'fair_value': 2000, 'pct_under': 0, 'score': 0,
            'final_score': 0, 'region': 'Downtown',
            'listing_id': 'zero-score-row', 'title': 'Zero Score',
        }]
        stats = app_module._neighborhood_stats(rows, 'Bay Street Corridor')
        listing_ids = [d['listing_id'] for d in stats['top_deals']]
        assert 'zero-score-row' not in listing_ids, "zero-score rows must be excluded from top_deals"
        # Sanity: the four existing listings still produced results
        assert len(stats['top_deals']) == 4

    def test_top_deals_capped_at_5(self):
        # Add 8 high-score listings -> still only 5 returned
        rows = list(SYNTH_ROWS)
        for i in range(8):
            rows.append({
                'source': 'kijiji', 'price': 1700, 'beds': 1, 'baths': 1, 'sqft': '',
                'neighbourhood': 'Bay Street Corridor', 'days_ago': 1, 'is_stale': False,
                'link': f'https://kijiji.ca/extra{i}', 'image_url': '', 'image_urls': [],
                'fair_value': 2200, 'pct_under': 22.7, 'score': 0.9,
                'final_score': 1.0, 'region': 'Downtown',
                'listing_id': f'extra{i}', 'title': f'Extra {i}',
            })
        stats = app_module._neighborhood_stats(rows, 'Bay Street Corridor')
        assert len(stats['top_deals']) == 5
        # Highest-scoring row (a @ 1.10) + 4 of the 8 extras (each @ 1.0) should be top 5.
        # Note: scores for SYNTH_ROWS are a=1.10, b=0.85, c=0.65, d=0.55.
        top_ids = [d['listing_id'] for d in stats['top_deals']]
        assert top_ids[0] == 'kijiji.ca/a', f"expected top by score, got {top_ids}"
        assert all(t.startswith('extra') for t in top_ids[1:]), \
            f"rows 2-5 should be the 1.0-scored extras, got {top_ids[1:]}"

    def test_unknown_neighborhood_returns_none(self):
        assert app_module._neighborhood_stats(SYNTH_ROWS, 'Atlantis') is None

    def test_empty_name_returns_none(self):
        assert app_module._neighborhood_stats(SYNTH_ROWS, '') is None

    def test_case_insensitive_match(self):
        # 'bay street CORRIDOR' should still match
        stats = app_module._neighborhood_stats(SYNTH_ROWS, 'bay street CORRIDOR')
        assert stats is not None
        assert stats['count'] == 4


# ---------------------------------------------------------------------------
# _neighborhoods_summary
# ---------------------------------------------------------------------------

class TestNeighborhoodsSummary:
    def test_shape(self):
        summary = app_module._neighborhoods_summary(SYNTH_ROWS)
        assert len(summary) == 2  # Bay Street Corridor + Other
        for entry in summary:
            assert set(entry.keys()) == {'name', 'slug', 'count', 'median_price'}

    def test_sorted_by_name(self):
        summary = app_module._neighborhoods_summary(SYNTH_ROWS)
        names = [s['name'] for s in summary]
        assert names == sorted(names, key=lambda x: x.lower())

    def test_count_correct(self):
        summary = app_module._neighborhoods_summary(SYNTH_ROWS)
        bay = next(s for s in summary if s['name'] == 'Bay Street Corridor')
        assert bay['count'] == 4

    def test_median_correct(self):
        summary = app_module._neighborhoods_summary(SYNTH_ROWS)
        bay = next(s for s in summary if s['name'] == 'Bay Street Corridor')
        assert bay['median_price'] == 2250.0

    def test_slug_matches(self):
        summary = app_module._neighborhoods_summary(SYNTH_ROWS)
        bay = next(s for s in summary if s['name'] == 'Bay Street Corridor')
        assert bay['slug'] == 'bay-street-corridor'

    def test_empty_neighborhoods_excluded(self):
        rows = [{'neighbourhood': '', 'price': 1500, 'beds': 1}]
        assert app_module._neighborhoods_summary(rows) == []


# ---------------------------------------------------------------------------
# _slug_to_neighborhood
# ---------------------------------------------------------------------------

class TestSlugToNeighborhood:
    def test_known_slug(self):
        assert app_module._slug_to_neighborhood(SYNTH_ROWS, 'bay-street-corridor') == 'Bay Street Corridor'

    def test_other_slug(self):
        assert app_module._slug_to_neighborhood(SYNTH_ROWS, 'other') == 'Other'

    def test_unknown_slug(self):
        assert app_module._slug_to_neighborhood(SYNTH_ROWS, 'atlantis') is None

    def test_empty_slug(self):
        assert app_module._slug_to_neighborhood(SYNTH_ROWS, '') is None


# ---------------------------------------------------------------------------
# _normalize_row: neighborhood_slug
# ---------------------------------------------------------------------------

class TestNormalizeAddsSlug:
    def test_known_neighborhood_has_slug(self):
        out = app_module._normalize_row(dict(RAW_ROWS[0]))
        assert out['neighborhood_slug'] == 'bay-street-corridor'

    def test_empty_neighborhood_no_slug(self):
        row = dict(RAW_ROWS[0])
        row['neighborhood'] = ''
        out = app_module._normalize_row(row)
        assert out['neighborhood_slug'] == ''

    def test_other_neighborhood_has_slug(self):
        out = app_module._normalize_row(dict(RAW_ROWS[4]))
        assert out['neighborhood_slug'] == 'other'


# ---------------------------------------------------------------------------
# /api/meta includes neighborhoods
# ---------------------------------------------------------------------------

class TestApiMetaNeighborhoods:
    def test_neighborhoods_key_present(self, client):
        r = client.get('/api/meta')
        assert r.status_code == 200
        meta = r.get_json()
        assert 'neighborhoods' in meta
        assert isinstance(meta['neighborhoods'], list)

    def test_neighborhoods_shape(self, client):
        r = client.get('/api/meta')
        meta = r.get_json()
        if meta['neighborhoods']:
            entry = meta['neighborhoods'][0]
            assert set(entry.keys()) == {'name', 'slug', 'count', 'median_price'}

    def test_meta_includes_existing_keys(self, client):
        """Regression: AC2 says add 'neighborhoods' — must not break existing keys."""
        r = client.get('/api/meta')
        meta = r.get_json()
        assert 'beds' in meta
        assert 'price' in meta
        assert 'baths' in meta
        assert 'regions' in meta
        assert 'sources' in meta


# ---------------------------------------------------------------------------
# /api/neighborhoods/<slug>/stats
# ---------------------------------------------------------------------------

class TestNeighborhoodStatsEndpoint:
    def test_known_slug_returns_200(self, client):
        r = client.get('/api/neighborhoods/bay-street-corridor/stats')
        assert r.status_code == 200

    def test_unknown_slug_returns_404(self, client):
        r = client.get('/api/neighborhoods/atlantis/stats')
        assert r.status_code == 404

    def test_empty_slug_returns_404(self, client):
        # /api/neighborhoods//stats routes differently; use a junk slug
        r = client.get('/api/neighborhoods/__nonexistent__/stats')
        assert r.status_code == 404

    def test_response_shape(self, client):
        r = client.get('/api/neighborhoods/bay-street-corridor/stats')
        s = r.get_json()
        # Required keys per AC1
        for k in ('neighborhood', 'slug', 'count', 'median_price',
                  'median_price_per_sqft', 'min_price', 'max_price',
                  'beds_breakdown', 'top_deals'):
            assert k in s, f"missing key: {k}"

    def test_response_values(self, client):
        r = client.get('/api/neighborhoods/bay-street-corridor/stats')
        s = r.get_json()
        assert s['count'] == 4
        assert s['neighborhood'] == 'Bay Street Corridor'
        assert s['slug'] == 'bay-street-corridor'
        assert s['median_price'] == 2250.0
        assert s['min_price'] == 1500
        assert s['max_price'] == 3500

    def test_top_deals_shape(self, client):
        r = client.get('/api/neighborhoods/bay-street-corridor/stats')
        s = r.get_json()
        assert isinstance(s['top_deals'], list)
        assert len(s['top_deals']) <= 5
        if s['top_deals']:
            d = s['top_deals'][0]
            for k in ('listing_id', 'price', 'beds', 'baths', 'sqft',
                      'pct_under', 'days_ago', 'final_score', 'link', 'title'):
                assert k in d, f"missing key in top_deal: {k}"


# ---------------------------------------------------------------------------
# /neighborhood/<slug> HTML page
# ---------------------------------------------------------------------------

class TestNeighborhoodPage:
    def test_known_slug_returns_200(self, client):
        r = client.get('/neighborhood/bay-street-corridor')
        assert r.status_code == 200

    def test_unknown_slug_still_returns_200(self, client):
        """Unknown slugs render the page shell with client-side error UI."""
        r = client.get('/neighborhood/atlantis')
        assert r.status_code == 200

    def test_page_contains_slug(self, client):
        r = client.get('/neighborhood/bay-street-corridor')
        assert b'bay-street-corridor' in r.data

    def test_page_contains_neighborhoods_endpoint(self, client):
        r = client.get('/neighborhood/bay-street-corridor')
        assert b'/api/neighborhoods/' in r.data

    def test_page_has_stats_grid_element(self, client):
        r = client.get('/neighborhood/bay-street-corridor')
        assert b'stats-grid' in r.data

    def test_page_has_top_deals_table(self, client):
        r = client.get('/neighborhood/bay-street-corridor')
        assert b'top-deals-body' in r.data


# ---------------------------------------------------------------------------
# /api/deals: every row carries neighborhood_slug
# ---------------------------------------------------------------------------

class TestDealsIncludeSlug:
    def test_each_row_has_neighborhood_slug(self, client):
        r = client.get('/api/deals')
        assert r.status_code == 200
        payload = r.get_json()
        rows = payload['deals'] if isinstance(payload, dict) and 'deals' in payload else payload
        assert rows, 'expected non-empty deals'
        for row in rows:
            assert 'neighborhood_slug' in row, f"row missing neighborhood_slug: {row.get('listing_id')}"

    def test_known_neighborhood_slug_correct(self, client):
        r = client.get('/api/deals')
        payload = r.get_json()
        rows = payload['deals'] if isinstance(payload, dict) and 'deals' in payload else payload
        bay_rows = [row for row in rows if (row.get('neighbourhood') or '').lower() == 'bay street corridor']
        for row in bay_rows:
            assert row['neighborhood_slug'] == 'bay-street-corridor'

    def test_filter_by_neighbourhood_still_works(self, client):
        """MC-321 must not regress the existing substring-match filter."""
        r = client.get('/api/deals?neighbourhood=bay')
        assert r.status_code == 200
        payload = r.get_json()
        rows = payload['deals'] if isinstance(payload, dict) and 'deals' in payload else payload
        assert all('bay' in (row.get('neighbourhood') or '').lower() for row in rows)


# ---------------------------------------------------------------------------
# index.html wiring: drill-down link + CSS
# ---------------------------------------------------------------------------

INDEX_HTML_PATH = os.path.join(RENT_DIR, 'templates', 'index.html')


class TestIndexHtmlWiring:
    @pytest.fixture(scope='class')
    def html(self):
        with open(INDEX_HTML_PATH, encoding='utf-8') as f:
            return f.read()

    def test_neighborhood_slug_rendered_in_row(self, html):
        """makeRowHtml should emit d.neighborhood_slug into the Stats link."""
        assert 'd.neighborhood_slug' in html, \
            "index.html must reference d.neighborhood_slug in row template"

    def test_drilldown_link_route(self, html):
        """Link must point to /neighborhood/<slug>."""
        assert '/neighborhood/' in html, \
            "index.html must contain /neighborhood/ link"

    def test_target_blank_attr(self, html):
        """Stats link must open in a new tab."""
        # The link is built via template literal; check the substring
        assert 'target="_blank"' in html

    def test_nbhd_stats_link_css_class_exists(self, html):
        """CSS for the drill-down link must be defined."""
        assert '.nbhd-stats-link' in html, \
            "index.html must define .nbhd-stats-link CSS"


# ---------------------------------------------------------------------------
# Regression sanity: existing API surface still works
# ---------------------------------------------------------------------------

class TestNoRegressions:
    def test_index_renders(self, client):
        r = client.get('/')
        assert r.status_code == 200

    def test_api_meta_works(self, client):
        r = client.get('/api/meta')
        assert r.status_code == 200

    def test_api_deals_works(self, client):
        r = client.get('/api/deals')
        assert r.status_code == 200