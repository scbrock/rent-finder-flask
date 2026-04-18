"""
Tests for MC-255: Cautions column — red flag warning chips.
"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import _compute_cautions


class TestComputeCautions:
    """MC-255: Caution rules for rental listings."""

    def test_no_cautions_clean_listing(self):
        d = {'pct_under': 15, 'days_ago': 3, 'sqft': '650', 'price': 2200, 'beds': 1, 'region': 'Downtown'}
        assert _compute_cautions(d) == []

    def test_unusually_cheap_25_pct(self):
        d = {'pct_under': 26, 'days_ago': 3, 'sqft': '650', 'price': 2200, 'beds': 1, 'region': 'Downtown'}
        assert 'Unusually cheap — verify condition' in _compute_cautions(d)

    def test_unusually_cheap_30_pct(self):
        d = {'pct_under': 30, 'days_ago': 3, 'sqft': '650', 'price': 2200, 'beds': 1, 'region': 'Downtown'}
        assert 'Unusually cheap — verify condition' in _compute_cautions(d)

    def test_unusually_cheap_exactly_25_no_flag(self):
        d = {'pct_under': 25, 'days_ago': 3, 'sqft': '650', 'price': 2200, 'beds': 1, 'region': 'Downtown'}
        assert 'Unusually cheap' not in _compute_cautions(d)

    def test_stale_listing(self):
        d = {'pct_under': 15, 'days_ago': 35, 'sqft': '650', 'price': 2200, 'beds': 1, 'region': 'Downtown'}
        assert 'Listing may be stale' in _compute_cautions(d)

    def test_stale_exactly_30_no_flag(self):
        d = {'pct_under': 15, 'days_ago': 30, 'sqft': '650', 'price': 2200, 'beds': 1, 'region': 'Downtown'}
        assert 'Listing may be stale' not in _compute_cautions(d)

    def test_no_sqft(self):
        d = {'pct_under': 15, 'days_ago': 3, 'sqft': '', 'price': 2200, 'beds': 1, 'region': 'Downtown'}
        assert 'Size not disclosed' in _compute_cautions(d)

    def test_sqft_none(self):
        d = {'pct_under': 15, 'days_ago': 3, 'sqft': None, 'price': 2200, 'beds': 1, 'region': 'Downtown'}
        assert 'Size not disclosed' in _compute_cautions(d)

    def test_sqft_nan(self):
        d = {'pct_under': 15, 'days_ago': 3, 'sqft': 'nan', 'price': 2200, 'beds': 1, 'region': 'Downtown'}
        assert 'Size not disclosed' in _compute_cautions(d)

    def test_below_basement_threshold_downtown(self):
        d = {'pct_under': 15, 'days_ago': 3, 'sqft': '650', 'price': 1050, 'beds': 1, 'region': 'Downtown'}
        assert 'Below typical basement threshold' in _compute_cautions(d)

    def test_below_basement_threshold_not_downtown(self):
        d = {'pct_under': 15, 'days_ago': 3, 'sqft': '650', 'price': 1050, 'beds': 1, 'region': 'West End'}
        assert 'Below typical basement threshold' not in _compute_cautions(d)

    def test_basement_threshold_price_1100_no_flag(self):
        d = {'pct_under': 15, 'days_ago': 3, 'sqft': '650', 'price': 1100, 'beds': 1, 'region': 'Downtown'}
        assert 'Below typical basement threshold' not in _compute_cautions(d)

    def test_basement_threshold_not_1br(self):
        d = {'pct_under': 15, 'days_ago': 3, 'sqft': '850', 'price': 900, 'beds': 2, 'region': 'Downtown'}
        assert 'Below typical basement threshold' not in _compute_cautions(d)

    def test_multiple_cautions(self):
        d = {'pct_under': 30, 'days_ago': 40, 'sqft': '', 'price': 1000, 'beds': 1, 'region': 'Downtown'}
        c = _compute_cautions(d)
        assert len(c) == 4  # cheap + stale + no sqft + basement threshold

    def test_caution_order_deterministic(self):
        d = {'pct_under': 30, 'days_ago': 40, 'sqft': '', 'price': 1000, 'beds': 1, 'region': 'Downtown'}
        c1 = _compute_cautions(d)
        c2 = _compute_cautions(d)
        assert c1 == c2

    def test_missing_fields_handled_gracefully(self):
        d = {'pct_under': None, 'days_ago': None, 'sqft': None, 'price': 0, 'beds': None, 'region': ''}
        c = _compute_cautions(d)
        # Should not raise, returns whatever cautions apply
        assert isinstance(c, list)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
