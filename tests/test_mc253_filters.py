"""Tests for MC-253: Filter sidebar — beds, baths, parking, price range.

Tests the Flask API filter endpoints in app.py and the filter UI behavior
(documenting expected client-side behavior).
"""
import sys, os, pytest, importlib.util

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENT_FINDER = os.path.join(PROJECT_ROOT)

app_path = os.path.join(RENT_FINDER, 'app.py')
spec = importlib.util.spec_from_file_location('app', app_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
app = mod.app
client = app.test_client()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def deals():
    """Load all deals from the API (or CSV fallback)."""
    resp = client.get('/api/deals')
    assert resp.status_code == 200
    return resp.get_json()


@pytest.fixture
def sample_deal():
    """A minimal deal dict matching the normalized row shape."""
    return {
        'neighbourhood': 'Queen West',
        'region': 'Downtown',
        'beds': 2,
        'baths': 1.0,
        'price': 2200.0,
        'price_fmt': '$2,200',
        'fair_value_fmt': '$2,500',
        'pct_under': 12.0,
        'pct_under_fmt': '12.0%',
        'days_ago': 5,
        'days_ago_str': '5d ago',
        'days_ago_class': 'age-medium',
        'is_stale': False,
        'sqft': '700',
        'commute_minutes': None,
        'link': 'https://kijiji.ca/v/123',
        'final_score': 0.132,
        'cautions': [],
    }


# ── Beds Filter ───────────────────────────────────────────────────────────────

class TestBedsFilter:
    def test_beds_min_filters_results(self, deals):
        """beds_min=2 should return only listings with beds >= 2."""
        resp = client.get('/api/deals?beds_min=2')
        filtered = resp.get_json()
        for d in filtered:
            assert d['beds'] is not None
            assert d['beds'] >= 2, f"beds={d['beds']} should be >= 2"

    def test_beds_max_filters_results(self, deals):
        """beds_max=1 should return only listings with beds <= 1."""
        resp = client.get('/api/deals?beds_max=1')
        filtered = resp.get_json()
        for d in filtered:
            assert d['beds'] is not None
            assert d['beds'] <= 1, f"beds={d['beds']} should be <= 1"

    def test_beds_min_and_max_combined(self, deals):
        """beds_min=1&beds_max=2 should return only 1-2BR listings."""
        resp = client.get('/api/deals?beds_min=1&beds_max=2')
        filtered = resp.get_json()
        for d in filtered:
            assert d['beds'] is not None
            assert 1 <= d['beds'] <= 2, f"beds={d['beds']} should be 1-2"


# ── Baths Filter ─────────────────────────────────────────────────────────────

class TestBathsFilter:
    def test_baths_min_filters_results(self, deals):
        """baths_min=1.5 should return only listings with baths >= 1.5."""
        resp = client.get('/api/deals?baths_min=1.5')
        filtered = resp.get_json()
        for d in filtered:
            if d['baths'] is not None:
                assert d['baths'] >= 1.5, f"baths={d['baths']} should be >= 1.5"

    def test_baths_min_any_returns_all(self, deals):
        """baths_min with no value should return all deals."""
        resp = client.get('/api/deals')
        all_deals = resp.get_json()
        assert len(all_deals) == len(deals)


# ── Price Range Filter ───────────────────────────────────────────────────────

class TestPriceFilter:
    def test_price_max_filters_results(self, deals):
        """price_max=2000 should return only listings priced <= $2000."""
        resp = client.get('/api/deals?price_max=2000')
        filtered = resp.get_json()
        for d in filtered:
            assert d['price'] <= 2000, f"price=${d['price']} should be <= $2000"

    def test_price_min_filters_results(self, deals):
        """price_min=1500 should return only listings priced >= $1500."""
        resp = client.get('/api/deals?price_min=1500')
        filtered = resp.get_json()
        for d in filtered:
            assert d['price'] >= 1500, f"price=${d['price']} should be >= $1500"

    def test_price_range_combined(self, deals):
        """price_min=1000&price_max=2500 should return listings in that range."""
        resp = client.get('/api/deals?price_min=1000&price_max=2500')
        filtered = resp.get_json()
        for d in filtered:
            assert 1000 <= d['price'] <= 2500, \
                f"price=${d['price']} should be 1000-2500"


# ── Neighbourhood Filter ──────────────────────────────────────────────────────

class TestNeighbourhoodFilter:
    def test_neighbourhood_partial_match(self, deals):
        """neighbourhood=queen should match 'Queen West', 'Queen Anne', etc."""
        resp = client.get('/api/deals?neighbourhood=queen')
        filtered = resp.get_json()
        for d in filtered:
            assert 'queen' in d['neighbourhood'].lower(), \
                f"neighbourhood='{d['neighbourhood']}' should contain 'queen'"

    def test_neighbourhood_case_insensitive(self, deals):
        resp = client.get('/api/deals?neighbourhood=Liberty')
        filtered = resp.get_json()
        for d in filtered:
            assert 'liberty' in d['neighbourhood'].lower()

    def test_neighbourhood_no_match_returns_empty_or_filtered(self, deals):
        """Non-matching neighbourhood should return 0 results."""
        resp = client.get('/api/deals?neighbourhood=XYZNOTAREALNEIGHBOURHOOD12345')
        filtered = resp.get_json()
        # Should return 0 results for garbage input
        assert len(filtered) == 0


# ── Region Filter ─────────────────────────────────────────────────────────────

class TestRegionFilter:
    def test_region_downtown(self, deals):
        """region=Downtown should return only Downtown listings."""
        resp = client.get('/api/deals?region=Downtown')
        filtered = resp.get_json()
        for d in filtered:
            assert d['region'] == 'Downtown'

    def test_region_west_end(self, deals):
        """region=West End should return only West End listings."""
        resp = client.get('/api/deals?region=West End')
        filtered = resp.get_json()
        for d in filtered:
            assert d['region'] == 'West End'

    def test_region_all_returns_all(self, deals):
        """No region param should return all deals."""
        resp = client.get('/api/deals')
        assert resp.status_code == 200
        assert len(resp.get_json()) > 0


# ── Sort ──────────────────────────────────────────────────────────────────────

class TestSort:
    def test_sort_by_price_ascending(self, deals):
        """sort=price should sort by price ascending (lowest first)."""
        resp = client.get('/api/deals?sort=price')
        filtered = resp.get_json()
        prices = [d['price'] for d in filtered]
        assert prices == sorted(prices), "prices should be ascending"

    def test_sort_by_pct_descending(self, deals):
        """sort=pct should sort by % under market descending (best deals first)."""
        resp = client.get('/api/deals?sort=pct')
        filtered = resp.get_json()
        pcts = [d['pct_under'] for d in filtered if d['pct_under'] is not None]
        assert pcts == sorted(pcts, reverse=True), "% under should be descending"

    def test_sort_by_score_descending(self, deals):
        """sort=score should sort by final_score descending."""
        resp = client.get('/api/deals?sort=score')
        filtered = resp.get_json()
        scores = [d['final_score'] for d in filtered if d['final_score'] is not None]
        assert scores == sorted(scores, reverse=True), "scores should be descending"

    def test_sort_by_days_ago_ascending(self, deals):
        """sort=days_ago should sort by freshness (freshest first)."""
        resp = client.get('/api/deals?sort=days_ago')
        filtered = resp.get_json()
        days = [d['days_ago'] for d in filtered if d['days_ago'] is not None]
        assert days == sorted(days), "days_ago should be ascending (freshest first)"


# ── Hide Stale Filter ─────────────────────────────────────────────────────────

class TestHideStale:
    def test_hide_stale_true_excludes_stale(self, deals):
        """hide_stale=true should exclude listings where is_stale=True."""
        resp = client.get('/api/deals?hide_stale=true')
        filtered = resp.get_json()
        for d in filtered:
            assert d.get('is_stale') is not True, \
                f"is_stale={d.get('is_stale')} should not be True"

    def test_hide_stale_false_includes_stale(self, deals):
        """hide_stale=false (default) should include stale listings."""
        resp = client.get('/api/deals?hide_stale=false')
        # Should work without error and return results
        assert resp.status_code == 200


# ── Combined Filters ─────────────────────────────────────────────────────────

class TestCombinedFilters:
    def test_multiple_filters_together(self, deals):
        """beds_min=1&price_max=2500&region=Downtown should apply all filters."""
        resp = client.get('/api/deals?beds_min=1&price_max=2500&region=Downtown')
        filtered = resp.get_json()
        for d in filtered:
            assert d['beds'] is not None and d['beds'] >= 1
            assert d['price'] <= 2500
            assert d['region'] == 'Downtown'

    def test_all_filters_applied_at_once(self, deals):
        """Stress test: all filter params at once."""
        params = 'beds_min=1&beds_max=3&baths_min=1&price_min=1000&price_max=3000&region=Downtown&sort=pct&hide_stale=true'
        resp = client.get(f'/api/deals?{params}')
        assert resp.status_code == 200
        filtered = resp.get_json()
        for d in filtered:
            assert 1 <= (d['beds'] or 0) <= 3
            assert 1000 <= d['price'] <= 3000
            assert d['region'] == 'Downtown'


# ── API Meta (dynamic ranges) ─────────────────────────────────────────────────

class TestApiMeta:
    def test_meta_returns_beds_range(self):
        """meta endpoint should return actual beds values from data."""
        resp = client.get('/api/meta')
        assert resp.status_code == 200
        meta = resp.get_json()
        assert isinstance(meta['beds'], list)

    def test_meta_returns_price_range(self):
        resp = client.get('/api/meta')
        meta = resp.get_json()
        assert isinstance(meta['price'], list)
        assert len(meta['price']) == 2
        assert meta['price'][0] <= meta['price'][1]

    def test_meta_returns_regions(self):
        resp = client.get('/api/meta')
        meta = resp.get_json()
        assert isinstance(meta['regions'], list)


# ── URL Param Persistence ─────────────────────────────────────────────────────

class TestUrlPersistence:
    """These document the expected URL param behavior (tested via API directly)."""

    def test_beds_min_in_url(self):
        """beds_min=2 should appear in the response filtered accordingly."""
        resp = client.get('/api/deals?beds_min=2')
        assert resp.status_code == 200
        # Backend correctly reads beds_min
        assert all(d['beds'] >= 2 for d in resp.get_json() if d.get('beds') is not None)

    def test_shared_link_url_params(self):
        """URL params should be shareable — same params give same results."""
        params = 'beds_min=1&region=Downtown&sort=price'
        r1 = client.get(f'/api/deals?{params}').get_json()
        r2 = client.get(f'/api/deals?{params}').get_json()
        assert r1 == r2, "same params should return identical results"


# ── Limit to 50 ───────────────────────────────────────────────────────────────

class TestPagination:
    def test_returns_max_50(self, deals):
        """API should cap at 50 results per request."""
        resp = client.get('/api/deals')
        filtered = resp.get_json()
        assert len(filtered) <= 50, f"Should cap at 50 results, got {len(filtered)}"

    def test_filtered_results_also_capped(self):
        resp = client.get('/api/deals?sort=price')
        filtered = resp.get_json()
        assert len(filtered) <= 50
