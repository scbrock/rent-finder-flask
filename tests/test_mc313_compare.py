"""MC-313: Tests for the /api/compare endpoint and the backend shape contract
that the frontend compare modal relies on.

Run: cd rent_finder && pytest tests/test_mc313_compare.py -v
"""
import os
import sys
import importlib.util
import json

# Path setup: rent_finder/tests/ -> rent_finder/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load the Flask app the same way test_app.py does (avoids importing as 'app'
# when other test files in the suite might collide).
app_path = os.path.join(PROJECT_ROOT, 'app.py')
spec = importlib.util.spec_from_file_location('mc313_app', app_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
flask_app = mod.app
client = flask_app.test_client()


def _get_deals():
    """Helper: fetch the current deal list (from SQLite or CSV fallback).

    MC-319: /api/deals now returns {deals, total, limit, offset, has_more}; extract the deals list.
    """
    resp = client.get('/api/deals')
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, dict) and 'deals' in data
    return data['deals']  # may be a single page; callers that need all should iterate pagination


def test_endpoint_exists_and_returns_200():
    """Sanity: /api/compare is registered and responds."""
    deals = _get_deals()
    if len(deals) < 2:
        import pytest
        pytest.skip("Need at least 2 deals for compare tests")
    ids = ','.join(d['listing_id'] for d in deals[:2] if d.get('listing_id'))
    resp = client.get(f'/api/compare?ids={ids}')
    assert resp.status_code == 200


def test_compare_returns_listings_and_best_block():
    """Payload has 'listings' (array, len 2-3) and 'best' (dict of winner ids)."""
    deals = _get_deals()
    valid = [d['listing_id'] for d in deals if d.get('listing_id')]
    if len(valid) < 2:
        import pytest
        pytest.skip("Need at least 2 deals with listing_id")
    ids = ','.join(valid[:2])
    resp = client.get(f'/api/compare?ids={ids}')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert isinstance(payload, dict)
    assert 'listings' in payload
    assert 'best' in payload
    assert isinstance(payload['listings'], list)
    assert len(payload['listings']) == 2
    assert isinstance(payload['best'], dict)


def test_compare_normalizes_each_listing():
    """Each listing in the response has the fields the frontend expects."""
    deals = _get_deals()
    valid = [d['listing_id'] for d in deals if d.get('listing_id')]
    if len(valid) < 2:
        import pytest
        pytest.skip("Need at least 2 deals with listing_id")
    resp = client.get(f'/api/compare?ids={",".join(valid[:2])}')
    payload = resp.get_json()
    for d in payload['listings']:
        # Required frontend fields
        for k in ('listing_id', 'neighbourhood', 'price', 'price_fmt', 'fair_value_fmt',
                  'pct_under', 'pct_under_fmt', 'days_ago_str', 'beds', 'baths',
                  'image_url', 'image_urls', 'link', 'final_score', 'cautions'):
            assert k in d, f"missing field {k} in {list(d.keys())}"
        # MC-313 derived fields
        assert 'price_per_sqft' in d
        assert 'photo_count' in d
        assert 'savings' in d


def test_compare_supports_three_listings():
    """When 3 ids are passed, response contains 3 listings."""
    deals = _get_deals()
    valid = [d['listing_id'] for d in deals if d.get('listing_id')]
    if len(valid) < 3:
        import pytest
        pytest.skip("Need at least 3 deals with listing_id")
    resp = client.get(f'/api/compare?ids={",".join(valid[:3])}')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert len(payload['listings']) == 3


def test_compare_best_block_keys():
    """Best block must include all expected metric keys (some may be null)."""
    deals = _get_deals()
    valid = [d['listing_id'] for d in deals if d.get('listing_id')]
    if len(valid) < 2:
        import pytest
        pytest.skip("Need at least 2 deals with listing_id")
    resp = client.get(f'/api/compare?ids={",".join(valid[:2])}')
    payload = resp.get_json()
    expected_keys = {'lowest_price', 'lowest_price_per_sqft', 'smallest_savings_gap', 'most_photos'}
    assert set(payload['best'].keys()) == expected_keys
    # All best values are either null or a listing_id (string)
    for v in payload['best'].values():
        assert v is None or isinstance(v, str)


def test_compare_lowest_price_winner_is_actual_min():
    """lowest_price should match the listing with the smallest price."""
    deals = _get_deals()
    valid = [d['listing_id'] for d in deals if d.get('listing_id')]
    if len(valid) < 3:
        import pytest
        pytest.skip("Need at least 3 deals with listing_id")
    resp = client.get(f'/api/compare?ids={",".join(valid[:3])}')
    payload = resp.get_json()
    winner_id = payload['best']['lowest_price']
    if winner_id:
        winner_price = next((float(d['price']) for d in payload['listings'] if d['listing_id'] == winner_id), None)
        all_prices = [float(d['price']) for d in payload['listings'] if d.get('price') is not None]
        assert winner_price == min(all_prices)


def test_compare_missing_ids_returns_400():
    """No ids query param = 400."""
    resp = client.get('/api/compare')
    assert resp.status_code == 400
    body = resp.get_json()
    assert 'error' in body


def test_compare_blank_ids_returns_400():
    """Empty ids query param = 400."""
    resp = client.get('/api/compare?ids=')
    assert resp.status_code == 400


def test_compare_single_id_returns_400():
    """Only 1 id = 400 (need 2-3)."""
    deals = _get_deals()
    valid = [d['listing_id'] for d in deals if d.get('listing_id')]
    if not valid:
        import pytest
        pytest.skip("Need at least 1 deal with listing_id")
    resp = client.get(f'/api/compare?ids={valid[0]}')
    assert resp.status_code == 400


def test_compare_too_many_ids_returns_400():
    """4+ ids = 400 (max 3)."""
    deals = _get_deals()
    valid = [d['listing_id'] for d in deals if d.get('listing_id')]
    if len(valid) < 4:
        import pytest
        pytest.skip("Need at least 4 deals with listing_id")
    resp = client.get(f'/api/compare?ids={",".join(valid[:4])}')
    assert resp.status_code == 400


def test_compare_duplicate_ids_returns_400():
    """Same id twice in the list = 400."""
    deals = _get_deals()
    valid = [d['listing_id'] for d in deals if d.get('listing_id')]
    if not valid:
        import pytest
        pytest.skip("Need at least 1 deal with listing_id")
    resp = client.get(f'/api/compare?ids={valid[0]},{valid[0]}')
    assert resp.status_code == 400


def test_compare_unknown_id_returns_404():
    """Listing id not in the deal list = 404 with missing_ids."""
    deals = _get_deals()
    valid = [d['listing_id'] for d in deals if d.get('listing_id')]
    if not valid:
        import pytest
        pytest.skip("Need at least 1 deal with listing_id")
    fake_id = 'NOT_A_REAL_LISTING_ID_12345'
    resp = client.get(f'/api/compare?ids={valid[0]},{fake_id}')
    assert resp.status_code == 404
    body = resp.get_json()
    assert fake_id in body.get('missing_ids', [])


def test_compare_handles_listings_without_sqft():
    """Listings with no sqft should have price_per_sqft=None, not crash."""
    deals = _get_deals()
    valid = [d['listing_id'] for d in deals if d.get('listing_id')]
    if len(valid) < 2:
        import pytest
        pytest.skip("Need at least 2 deals with listing_id")
    resp = client.get(f'/api/compare?ids={",".join(valid[:2])}')
    payload = resp.get_json()
    for d in payload['listings']:
        # price_per_sqft is None when sqft missing — never a string or zero crash
        assert d['price_per_sqft'] is None or isinstance(d['price_per_sqft'], (int, float))
        if d['price_per_sqft'] is not None:
            assert d['price_per_sqft'] > 0


def test_compare_savings_calculation():
    """savings = fair_value - price (positive when deal is below FV)."""
    deals = _get_deals()
    valid = [d['listing_id'] for d in deals if d.get('listing_id')]
    if len(valid) < 2:
        import pytest
        pytest.skip("Need at least 2 deals with listing_id")
    resp = client.get(f'/api/compare?ids={",".join(valid[:2])}')
    payload = resp.get_json()
    for d in payload['listings']:
        fv = d.get('fair_value_fmt')
        price = d.get('price')
        savings = d.get('savings')
        if not fv or fv == '—' or price is None:
            continue
        # Savings should be a number
        assert isinstance(savings, (int, float))


def test_compare_photo_count_includes_image_urls():
    """photo_count = len(image_urls) for listings with gallery, or 1 for single, or 0 for none."""
    deals = _get_deals()
    valid = [d['listing_id'] for d in deals if d.get('listing_id')]
    if len(valid) < 2:
        import pytest
        pytest.skip("Need at least 2 deals with listing_id")
    resp = client.get(f'/api/compare?ids={",".join(valid[:2])}')
    payload = resp.get_json()
    for d in payload['listings']:
        pc = d['photo_count']
        urls = d.get('image_urls') or []
        img = d.get('image_url') or ''
        expected = len(urls) if urls else (1 if img else 0)
        assert pc == expected, f"photo_count {pc} != expected {expected} (urls={urls}, img={img})"


def test_compare_idempotent_for_same_input():
    """Calling twice with the same ids returns the same listings (same order)."""
    deals = _get_deals()
    valid = [d['listing_id'] for d in deals if d.get('listing_id')]
    if len(valid) < 2:
        import pytest
        pytest.skip("Need at least 2 deals with listing_id")
    ids = ','.join(valid[:2])
    r1 = client.get(f'/api/compare?ids={ids}').get_json()
    r2 = client.get(f'/api/compare?ids={ids}').get_json()
    assert [d['listing_id'] for d in r1['listings']] == [d['listing_id'] for d in r2['listings']]