"""Tests for MC-259: Listing detail page with deal breakdown and cautions."""
import sys, os, pytest, importlib.util

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENT_FINDER = os.path.join(PROJECT_ROOT)

app_path = os.path.join(RENT_FINDER, 'app.py')
spec = importlib.util.spec_from_file_location('app', app_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
app = mod.app
client = app.test_client()


class TestListingDetail:
    def test_listing_detail_returns_200(self):
        """GET /api/listing/0 should return 200."""
        resp = client.get('/api/listing/0')
        assert resp.status_code == 200

    def test_listing_detail_returns_dict(self):
        resp = client.get('/api/listing/0')
        d = resp.get_json()
        assert isinstance(d, dict)
        assert 'neighbourhood' in d
        assert 'price' in d
        assert 'breakdown' in d
        assert 'cautions' in d

    def test_listing_detail_has_breakdown_fields(self):
        d = client.get('/api/listing/0').get_json()
        bd = d['breakdown']
        assert 'segment' in bd
        assert 'deal_score' in bd
        assert 'listed_price' in bd
        assert 'fair_value' in bd
        assert 'pct_under' in bd

    def test_listing_detail_has_expanded_cautions(self):
        """Cautions should include flag text and explanation detail."""
        d = client.get('/api/listing/0').get_json()
        cautions = d['cautions']
        assert isinstance(cautions, list)
        for c in cautions:
            assert 'flag' in c
            assert 'detail' in c
            assert len(c['detail']) > 10, "Caution detail should be explanatory text"

    def test_listing_detail_includes_days_ago_str(self):
        """Response should include a human-readable freshness string."""
        d = client.get('/api/listing/0').get_json()
        assert 'days_ago_str' in d
        assert isinstance(d['days_ago_str'], str)
        assert len(d['days_ago_str']) > 0

    def test_listing_detail_includes_link(self):
        d = client.get('/api/listing/0').get_json()
        assert 'link' in d
        assert d['link'], "Listing should have a link"

    def test_listing_detail_out_of_range_returns_404(self):
        resp = client.get('/api/listing/99999')
        assert resp.status_code == 404

    def test_listing_detail_negative_returns_404(self):
        resp = client.get('/api/listing/-1')
        assert resp.status_code == 404

    def test_listing_detail_has_beds_baths_sqft(self):
        d = client.get('/api/listing/0').get_json()
        assert 'beds' in d
        assert 'baths' in d
        assert 'sqft' in d

    def test_listing_detail_commute_minutes_present(self):
        d = client.get('/api/listing/0').get_json()
        assert 'commute_minutes' in d

    def test_listing_detail_freshness_class(self):
        """days_ago_class should be one of the known CSS class values."""
        d = client.get('/api/listing/0').get_json()
        valid_classes = ('age-fresh', 'age-medium', 'age-stale', 'age-neutral')
        assert d.get('days_ago_class') in valid_classes

    def test_all_listings_have_detail(self):
        """Every listing index from 0 to min(9, len(deals)-1) should be accessible."""
        deals_resp = client.get('/api/deals')
        deals = deals_resp.get_json()
        count = min(10, len(deals))
        for i in range(count):
            resp = client.get(f'/api/listing/{i}')
            assert resp.status_code == 200, f"listing/{i} should be accessible"


class TestDetailModalLinks:
    def test_deals_have_link_column(self):
        deals = client.get('/api/deals').get_json()
        if deals:
            assert 'link' in deals[0]
            assert deals[0]['link'].startswith('http'), "Link should be a valid URL"
