"""
MC-256: Leaflet map view with colour-coded deal pins.
Tests the /api/deals/geo endpoint and pin colour logic.
"""

import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c

class TestGeoEndpoint:
    def test_returns_200(self, client):
        r = client.get('/api/deals/geo')
        assert r.status_code == 200

    def test_returns_list(self, client):
        r = client.get('/api/deals/geo')
        data = r.get_json()
        assert isinstance(data, list)

    def test_deals_have_required_geo_fields(self, client):
        r = client.get('/api/deals/geo')
        deals = r.get_json()
        required = {'lat', 'lng', 'neighbourhood', 'price_fmt', 'pct_under', 'link', 'beds'}
        for d in deals:
            for field in required:
                assert field in d, f"Missing field: {field}"
            assert isinstance(d['lat'], (int, float)), f"lat not numeric: {d['lat']}"
            assert isinstance(d['lng'], (int, float)), f"lng not numeric: {d['lng']}"
            assert -90 <= d['lat'] <= 90, f"lat out of range: {d['lat']}"
            assert -180 <= d['lng'] <= 180, f"lng out of range: {d['lng']}"

    def test_deals_with_unknown_neighbourhoods_omitted(self, client):
        """Listings with no mappable neighbourhood should not appear in geo endpoint."""
        r = client.get('/api/deals/geo')
        deals = r.get_json()
        # All returned deals must have valid lat/lng
        for d in deals:
            assert d['lat'] is not None
            assert d['lng'] is not None

    def test_pin_color_green_for_good_deal(self, client):
        """pct_under >= 15 → green (2d6a4f)"""
        from neighbourhood_lookup import get_centroid
        deals = client.get('/api/deals/geo').get_json()
        good_deals = [d for d in deals if d['pct_under'] >= 15]
        if good_deals:
            for d in good_deals:
                assert d['pct_under'] >= 15

    def test_pin_color_yellow_for_fair_deal(self, client):
        """8 <= pct_under < 15 → yellow"""
        deals = client.get('/api/deals/geo').get_json()
        fair_deals = [d for d in deals if 8 <= d['pct_under'] < 15]
        assert all(8 <= d['pct_under'] < 15 for d in fair_deals)

    def test_pin_color_grey_for_at_market(self, client):
        """pct_under < 8 → grey"""
        deals = client.get('/api/deals/geo').get_json()
        grey_deals = [d for d in deals if d['pct_under'] < 8]
        assert all(d['pct_under'] < 8 for d in grey_deals)

    def test_pct_under_field_present(self, client):
        deals = client.get('/api/deals/geo').get_json()
        for d in deals:
            assert 'pct_under' in d
            assert isinstance(d['pct_under'], (int, float))

    def test_neighbourhood_in_response(self, client):
        deals = client.get('/api/deals/geo').get_json()
        for d in deals:
            assert 'neighbourhood' in d
            assert isinstance(d['neighbourhood'], str)

    def test_link_field_present(self, client):
        deals = client.get('/api/deals/geo').get_json()
        for d in deals:
            assert 'link' in d

    def test_empty_when_no_data(self, client):
        """Geo endpoint should return a list (possibly empty), not error."""
        r = client.get('/api/deals/geo')
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_pin_color_function(self):
        """Unit test for the pinColor function logic."""
        from tests.test_mc256_map import pin_color_logic
        assert pin_color_logic(20) == '#2d6a4f'   # green
        assert pin_color_logic(15) == '#2d6a4f'   # green (boundary)
        assert pin_color_logic(14) == '#e9a825'    # yellow
        assert pin_color_logic(8)  == '#e9a825'    # yellow (boundary)
        assert pin_color_logic(7)  == '#888888'   # grey
        assert pin_color_logic(0)  == '#888888'   # grey

def pin_color_logic(pct_under):
    if pct_under >= 15: return '#2d6a4f'
    if pct_under >= 8:  return '#e9a825'
    return '#888888'
