"""Tests for rent_finder/app.py"""
import sys, os, pytest, importlib.util

# rent_finder/tests/ -> project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENT_FINDER = os.path.join(PROJECT_ROOT)  # rent_finder/ is at project root

app_path = os.path.join(RENT_FINDER, 'app.py')
spec = importlib.util.spec_from_file_location('app', app_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
app = mod.app
client = app.test_client()


def test_index_returns_200():
    resp = client.get('/')
    assert resp.status_code == 200


def test_index_contains_title():
    resp = client.get('/')
    assert b'Toronto Rent Deals' in resp.data


def test_api_deals_returns_200():
    resp = client.get('/api/deals')
    assert resp.status_code == 200


def test_api_deals_returns_list():
    resp = client.get('/api/deals')
    deals = resp.get_json()
    assert isinstance(deals, list)


def test_api_deals_returns_min_listings():
    """Pipeline success gate: >= 50 fresh listings required per run (AC1)."""
    resp = client.get('/api/deals')
    deals = resp.get_json()
    assert len(deals) >= 50, f"Expected >= 50 listings, got {len(deals)}"


def test_csv_exists():
    csv_path = os.path.join(RENT_FINDER, 'deals_output.csv')
    assert os.path.exists(csv_path)


def test_filter_by_min_beds():
    resp = client.get('/api/deals?beds_min=1')
    deals = resp.get_json()
    for d in deals:
        assert d.get('beds', 0) >= 1


def test_filter_by_max_price():
    resp = client.get('/api/deals?max_price=2000')
    deals = resp.get_json()
    # Should return filtered deals (top 50 only for price filter)
    assert len(deals) <= 55


def test_filter_by_neighbourhood():
    resp = client.get('/api/deals?neighbourhood=Queen')
    deals = resp.get_json()
    for d in deals:
        assert 'queen' in d.get('neighbourhood', '').lower()


def test_sort_options():
    for sort_opt in ['score', 'pct', 'price']:
        resp = client.get(f'/api/deals?sort={sort_opt}')
        assert resp.status_code == 200
        deals = resp.get_json()
        assert isinstance(deals, list)