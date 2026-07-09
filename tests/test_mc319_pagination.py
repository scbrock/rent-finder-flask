"""Tests for MC-319: Server-side pagination for /api/deals.

Verifies:
- Default response shape: {deals, total, limit, offset, has_more}
- Limit + offset query params work, with default cap and maximum cap
- has_more is computed correctly across the boundary (offset+len vs total)
- Total reflects the FULL filtered count BEFORE pagination is applied
- Backward-compat regression: every previous filter param still works
"""
import os
import sys
import pytest
import importlib.util

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENT_FINDER = PROJECT_ROOT

# Load app.py as a module
app_path = os.path.join(RENT_FINDER, 'app.py')
spec = importlib.util.spec_from_file_location('app_mc319', app_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
app = mod.app

# Capture deals so we can compute expected totals against the same baseline.
_baseline_payload = None


@pytest.fixture(scope="module")
def client():
    return app.test_client()


@pytest.fixture(scope="module")
def baseline(client):
    """Snapshot the unfiltered deal payload for total-count assertions."""
    global _baseline_payload
    resp = client.get('/api/deals')
    assert resp.status_code == 200
    _baseline_payload = resp.get_json()
    return _baseline_payload


# ── Shape ────────────────────────────────────────────────────────────────────

class TestResponseShape:
    def test_returns_dict(self, client):
        resp = client.get('/api/deals')
        data = resp.get_json()
        assert isinstance(data, dict), "MC-319: /api/deals should return a dict"

    def test_dict_has_required_keys(self, client):
        resp = client.get('/api/deals')
        data = resp.get_json()
        for key in ('deals', 'total', 'limit', 'offset', 'has_more'):
            assert key in data, f"MC-319: response missing key '{key}'"

    def test_deals_is_list(self, client):
        resp = client.get('/api/deals')
        data = resp.get_json()
        assert isinstance(data['deals'], list)

    def test_total_is_non_negative_int(self, client):
        resp = client.get('/api/deals')
        data = resp.get_json()
        assert isinstance(data['total'], int)
        assert data['total'] >= 0

    def test_limit_is_positive_int(self, client):
        resp = client.get('/api/deals')
        data = resp.get_json()
        assert isinstance(data['limit'], int)
        assert 1 <= data['limit'] <= 200

    def test_offset_is_non_negative_int(self, client):
        resp = client.get('/api/deals')
        data = resp.get_json()
        assert isinstance(data['offset'], int)
        assert data['offset'] >= 0

    def test_has_more_is_bool(self, client):
        resp = client.get('/api/deals')
        data = resp.get_json()
        assert isinstance(data['has_more'], bool)


# ── Defaults ────────────────────────────────────────────────────────────────

class TestDefaults:
    def test_default_limit_is_50(self, client):
        resp = client.get('/api/deals')
        data = resp.get_json()
        assert data['limit'] == 50

    def test_default_offset_is_0(self, client):
        resp = client.get('/api/deals')
        data = resp.get_json()
        assert data['offset'] == 0


# ── Limit behaviour ─────────────────────────────────────────────────────────

class TestLimit:
    def test_explicit_limit_10(self, client):
        resp = client.get('/api/deals?limit=10')
        data = resp.get_json()
        assert data['limit'] == 10
        assert len(data['deals']) <= 10

    def test_limit_over_max_clamped_to_200(self, client):
        resp = client.get('/api/deals?limit=99999')
        data = resp.get_json()
        assert data['limit'] == 200, "limit > 200 should clamp to 200"

    def test_limit_zero_clamped_to_1(self, client):
        resp = client.get('/api/deals?limit=0')
        data = resp.get_json()
        assert data['limit'] == 1
        assert len(data['deals']) == 1

    def test_limit_negative_clamped_to_1(self, client):
        resp = client.get('/api/deals?limit=-5')
        data = resp.get_json()
        assert data['limit'] == 1

    def test_invalid_limit_falls_back_to_50(self, client):
        resp = client.get('/api/deals?limit=xyz')
        data = resp.get_json()
        assert data['limit'] == 50

    def test_limit_returns_at_most_limit_deals(self, client):
        resp = client.get('/api/deals?limit=25')
        data = resp.get_json()
        assert len(data['deals']) <= 25


# ── Offset behaviour ────────────────────────────────────────────────────────

class TestOffset:
    def test_offset_explicit_zero(self, client):
        resp = client.get('/api/deals?offset=0')
        data = resp.get_json()
        assert data['offset'] == 0

    def test_offset_10(self, client):
        resp = client.get('/api/deals?limit=10&offset=10')
        data = resp.get_json()
        assert data['offset'] == 10
        assert len(data['deals']) <= 10

    def test_offset_negative_clamped_to_zero(self, client):
        resp = client.get('/api/deals?offset=-5')
        data = resp.get_json()
        assert data['offset'] == 0

    def test_invalid_offset_falls_back_to_zero(self, client):
        resp = client.get('/api/deals?offset=abc')
        data = resp.get_json()
        assert data['offset'] == 0

    def test_offset_beyond_total_returns_empty_page(self, client, baseline):
        total = baseline['total']
        resp = client.get(f'/api/deals?offset={total}')
        data = resp.get_json()
        assert data['deals'] == []
        assert data['offset'] == total
        assert data['has_more'] is False


# ── has_more ────────────────────────────────────────────────────────────────

class TestHasMore:
    def test_first_page_with_more(self, client):
        """If total > limit, first page should report has_more=True."""
        resp = client.get('/api/deals?limit=10')
        data = resp.get_json()
        # If total > 10, has_more should be True
        if data['total'] > 10:
            assert data['has_more'] is True
        else:
            assert data['has_more'] is False

    def test_last_page_has_more_false(self, client, baseline):
        """At the boundary offset+len >= total, has_more should be False."""
        total = baseline['total']
        # fetch all in one go (server caps at 200 — see if total <= 200)
        if total <= 200:
            # single page case — has_more must be False
            resp = client.get('/api/deals?limit=200')
            data = resp.get_json()
            if data['total'] <= 200:
                assert data['has_more'] is False
        else:
            # multi-page: grab last partial page
            last_offset = total - 10
            resp = client.get(f'/api/deals?offset={last_offset}&limit=10')
            data = resp.get_json()
            # Last partial page must report has_more = False
            assert data['has_more'] is False

    def test_one_before_last_has_more_true(self, client, baseline):
        total = baseline['total']
        if total <= 51:
            pytest.skip("Not enough deals to test multi-page boundary")
        # Set offset such that the page contains exactly `limit` deals and at
        # least one more remains after this page.
        offset = total - 50 - 1  # so deals[offset:offset+50] = full 50, with 1 more after
        resp = client.get(f'/api/deals?offset={offset}&limit=50')
        data = resp.get_json()
        # Page is full (50 deals) and there is 1 more listing not in this page
        assert len(data['deals']) == 50
        assert data['has_more'] is True


# ── Total before pagination ────────────────────────────────────────────────

class TestTotalReflectsFilter:
    def test_total_unchanged_with_default_limit(self, client, baseline):
        """Total should reflect the FULL filtered count, not the page size."""
        resp = client.get('/api/deals?limit=10')
        data = resp.get_json()
        # The total stays the same as the unfiltered baseline even though only 10 returned
        assert data['total'] == baseline['total']

    def test_total_with_filter_smaller_than_default(self, client):
        """Total reflects filter result count BEFORE slicing."""
        resp_unfiltered = client.get('/api/deals')
        unfiltered_total = resp_unfiltered.get_json()['total']

        resp_filtered = client.get('/api/deals?price_max=2000')
        filtered_total = resp_filtered.get_json()['total']
        # Filter should reduce the total
        assert filtered_total <= unfiltered_total

    def test_total_for_zero_filter_result(self, client):
        """A filter that matches nothing should return total=0."""
        resp = client.get('/api/deals?neighbourhood=XYZNOTAREAL12345')
        data = resp.get_json()
        assert data['total'] == 0
        assert data['deals'] == []
        assert data['has_more'] is False


# ── Cross-page consistency ──────────────────────────────────────────────────

class TestCrossPageConsistency:
    def test_consecutive_pages_disjoint(self, client, baseline):
        total = baseline['total']
        if total < 20:
            pytest.skip("Need at least 20 deals to test pagination disjoint")
        page1 = client.get('/api/deals?limit=10&offset=0').get_json()['deals']
        page2 = client.get('/api/deals?limit=10&offset=10').get_json()['deals']
        ids1 = {d.get('listing_id') or d.get('link') for d in page1}
        ids2 = {d.get('listing_id') or d.get('link') for d in page2}
        assert ids1.isdisjoint(ids2), "page1 and page2 listings must not overlap"

    def test_full_traversal_equals_total(self, client):
        """Iterating all pages should equal total — no drops, no duplicates."""
        seen = []
        offset = 0
        limit = 50
        while True:
            resp = client.get(f'/api/deals?limit={limit}&offset={offset}').get_json()
            seen.extend(resp['deals'])
            if not resp['has_more']:
                break
            offset += limit
            if offset > 10000:
                pytest.fail("Pagination loop did not terminate")
        # Compare against total from a fresh request
        total = client.get('/api/deals?limit=1').get_json()['total']
        assert len(seen) == total, f"Iterated {len(seen)} but total is {total}"


# ── Filter integration ─────────────────────────────────────────────────────

class TestFiltersWithPagination:
    def test_source_filter_total_matches_filtered_count(self, client):
        """Filter narrows the universe, total reflects that, offset operates within it."""
        # Get the unfiltered total
        unfiltered = client.get('/api/deals?limit=1').get_json()['total']
        # Get kijiji-only total
        kijiji = client.get('/api/deals?source=kijiji&limit=200').get_json()
        assert kijiji['total'] < unfiltered
        assert kijiji['total'] == len(kijiji['deals'])  # all fit in 200

    def test_combined_filters_paginated_correctly(self, client):
        """Multiple filters + pagination should each work."""
        resp = client.get('/api/deals?price_max=2000&region=Downtown&sort=price&limit=5&offset=0')
        data = resp.get_json()
        # Limit honored
        assert len(data['deals']) <= 5
        # All deals respect filters
        for d in data['deals']:
            assert d['price'] <= 2000
            assert d['region'] == 'Downtown'


# ── HTML wiring (UI Load more) ─────────────────────────────────────────────

class TestHtmlWiring:
    def test_index_has_load_more_button(self):
        index_path = os.path.join(RENT_FINDER, 'templates', 'index.html')
        with open(index_path, 'r', encoding='utf-8-sig') as fh:
            html = fh.read()
        assert 'id="load_more_btn"' in html, "index.html must include Load more button"
        assert 'loadMoreDeals' in html, "index.html must call loadMoreDeals() somewhere"

    def test_index_has_pagination_footer(self):
        index_path = os.path.join(RENT_FINDER, 'templates', 'index.html')
        with open(index_path, 'r', encoding='utf-8-sig') as fh:
            html = fh.read()
        assert 'id="pagination_footer"' in html, "index.html must include pagination footer"
        assert 'pagination_status' in html, "index.html must include pagination status indicator"

    def test_index_defines_loadMoreDeals_function(self):
        index_path = os.path.join(RENT_FINDER, 'templates', 'index.html')
        with open(index_path, 'r', encoding='utf-8-sig') as fh:
            html = fh.read()
        assert 'async function loadMoreDeals' in html, "index.html must define loadMoreDeals()"
        assert 'function renderLoadMore' in html, "index.html must define renderLoadMore()"

    def test_index_renderdeals_passed_total(self):
        """renderDeals must accept a pagination object so total_count is correct."""
        index_path = os.path.join(RENT_FINDER, 'templates', 'index.html')
        with open(index_path, 'r', encoding='utf-8-sig') as fh:
            html = fh.read()
        assert 'pagination.total' in html or "pagination &&" in html, "renderDeals must reference pagination.total"

    def test_index_resets_offset_on_filter_change(self):
        index_path = os.path.join(RENT_FINDER, 'templates', 'index.html')
        with open(index_path, 'r', encoding='utf-8-sig') as fh:
            html = fh.read()
        assert 'currentOffset = 0' in html, "currentOffset must reset to 0 when filter changes"


# ── Index render smoke ─────────────────────────────────────────────────────

class TestIndexRender:
    def test_index_renders_with_200(self, client):
        resp = client.get('/')
        assert resp.status_code == 200

    def test_index_pagination_elements_in_rendered_html(self, client):
        resp = client.get('/')
        body = resp.data.decode('utf-8')
        assert 'load_more_btn' in body
        assert 'pagination_footer' in body
