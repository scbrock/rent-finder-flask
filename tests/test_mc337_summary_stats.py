"""MC-337 tests: Median Rent + Total Monthly Savings summary stats.

Covers:
- _median_price: rounding to nearest $50, empty handling, missing prices
- _total_savings: sum of (fair_value - price), exclusions
- /api/meta: new fields present, default 0, regression-safe
- HTML wiring: stat-card markup, IDs, JS handler updates the elements
"""
import sys, os, json, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Force UTF-8 stdout so Windows console doesn't choke on Unicode
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import unittest
from app import _median_price, _total_savings


def _norm(price=None, fair_value=None, pct_under=None):
    """Build a minimal deal dict matching what load_deals() returns."""
    return {'price': price, 'fair_value': fair_value, 'pct_under': pct_under}


class TestMedianPrice(unittest.TestCase):
    """_median_price: median of all listing prices, rounded to nearest $50."""

    def test_empty_returns_zero(self):
        self.assertEqual(_median_price([]), 0)

    def test_single_listing(self):
        self.assertEqual(_median_price([_norm(price=2300)]), 2300)

    def test_odd_count_median(self):
        # [1000, 2000, 3000] -> median 2000
        deals = [_norm(price=p) for p in [1000, 2000, 3000]]
        self.assertEqual(_median_price(deals), 2000)

    def test_even_count_median(self):
        # [1000, 2000, 3000, 4000] -> median (2000+3000)/2 = 2500
        deals = [_norm(price=p) for p in [1000, 2000, 3000, 4000]]
        self.assertEqual(_median_price(deals), 2500)

    def test_rounds_to_nearest_50(self):
        # median ~2347 -> rounds to 2350
        deals = [_norm(price=p) for p in [2300, 2347, 2400]]
        # raw median = 2347 -> round(2347/50)*50 = round(46.94)*50 = 47*50 = 2350
        self.assertEqual(_median_price(deals), 2350)

    def test_rounds_down_to_nearest_50(self):
        # median 2326 -> rounds to 2350 (46.52 -> 47)
        deals = [_norm(price=p) for p in [2300, 2326, 2400]]
        self.assertEqual(_median_price(deals), 2350)

    def test_skips_missing_prices(self):
        # 3 valid + 2 missing -> median of valid
        deals = [_norm(price=p) for p in [1000, 2000, 3000]]
        deals.append(_norm(price=None))
        deals.append(_norm(price=''))
        self.assertEqual(_median_price(deals), 2000)

    def test_skips_nonnumeric_prices(self):
        deals = [_norm(price=p) for p in [1000, 2000, 3000]]
        deals.append(_norm(price='garbage'))
        deals.append(_norm(price='None'))
        self.assertEqual(_median_price(deals), 2000)

    def test_skips_zero_and_negative_prices(self):
        deals = [_norm(price=p) for p in [1000, 2000, 3000]]
        deals.append(_norm(price=0))
        deals.append(_norm(price=-100))
        self.assertEqual(_median_price(deals), 2000)


class TestTotalSavings(unittest.TestCase):
    """_total_savings: sum of (fair_value - price) where pct_under > 0."""

    def test_empty_returns_zero(self):
        self.assertEqual(_total_savings([]), 0)

    def test_basic_sum(self):
        # 2 deals, both under market by $500 each -> 1000
        deals = [
            _norm(price=1500, fair_value=2000, pct_under=25.0),
            _norm(price=1700, fair_value=2200, pct_under=22.7),
        ]
        self.assertEqual(_total_savings(deals), 1000)

    def test_pct_zero_excluded(self):
        # pct_under = 0 means at market, not under -> exclude
        deals = [
            _norm(price=1500, fair_value=2000, pct_under=25.0),  # +500
            _norm(price=2000, fair_value=2000, pct_under=0),     # 0 (at market)
        ]
        self.assertEqual(_total_savings(deals), 500)

    def test_pct_negative_excluded(self):
        # pct_under < 0 means overpriced -> exclude
        deals = [
            _norm(price=1500, fair_value=2000, pct_under=25.0),  # +500
            _norm(price=2500, fair_value=2000, pct_under=-25.0), # overpriced
        ]
        self.assertEqual(_total_savings(deals), 500)

    def test_fair_value_le_price_excluded(self):
        # fair_value=0 or fair_value <= price -> exclude (no benchmark)
        deals = [
            _norm(price=1500, fair_value=2000, pct_under=25.0),   # +500
            _norm(price=1500, fair_value=0, pct_under=25.0),       # no FV
            _norm(price=1500, fair_value=1500, pct_under=0),       # at market
            _norm(price=1500, fair_value=1400, pct_under=-7.0),    # overpriced
        ]
        self.assertEqual(_total_savings(deals), 500)

    def test_missing_fields_excluded(self):
        deals = [
            _norm(price=1500, fair_value=2000, pct_under=25.0),   # +500
            _norm(price=None, fair_value=2000, pct_under=25.0),    # bad price
            _norm(price=1500, fair_value=None, pct_under=25.0),    # bad FV
            _norm(price=1500, fair_value=2000, pct_under=None),    # bad pct
        ]
        self.assertEqual(_total_savings(deals), 500)

    def test_rounds_to_nearest_dollar(self):
        # 2347.6 savings -> 2348
        deals = [_norm(price=7653, fair_value=10000.6, pct_under=23.5)]
        self.assertEqual(_total_savings(deals), 2348)


class TestApiMetaNewFields(unittest.TestCase):
    """/api/meta: median_price + total_monthly_savings + regression safety."""

    @classmethod
    def setUpClass(cls):
        from app import app
        cls.client = app.test_client()

    def test_meta_includes_median_price(self):
        r = self.client.get('/api/meta')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn('median_price', data)
        self.assertIsInstance(data['median_price'], int)
        # Median price should be >= 0
        self.assertGreaterEqual(data['median_price'], 0)

    def test_meta_includes_total_monthly_savings(self):
        r = self.client.get('/api/meta')
        data = r.get_json()
        self.assertIn('total_monthly_savings', data)
        self.assertIsInstance(data['total_monthly_savings'], int)
        self.assertGreaterEqual(data['total_monthly_savings'], 0)

    def test_meta_preserves_all_existing_keys(self):
        """Regression: AC requires ALL pre-MC-337 /api/meta keys still present."""
        r = self.client.get('/api/meta')
        data = r.get_json()
        expected_keys = {
            'beds', 'price', 'baths', 'regions', 'sources',
            'neighborhoods', 'new_count', 'price_drop_count',
            'with_photos_count', 'price_per_sqft_stats', 'neighborhood_trends',
            'median_price', 'total_monthly_savings',  # MC-337 additions
        }
        self.assertEqual(set(data.keys()), expected_keys)

    def test_meta_top_level_type_is_object(self):
        r = self.client.get('/api/meta')
        data = r.get_json()
        self.assertIsInstance(data, dict)


class TestIndexHtmlWiring(unittest.TestCase):
    """templates/index.html: stat-card markup + IDs + JS rendering."""

    @classmethod
    def setUpClass(cls):
        cls.html = open(os.path.join(os.path.dirname(__file__), '..', 'templates', 'index.html'),
                        encoding='utf-8').read()

    def test_median_rent_card_present(self):
        self.assertIn('id="median_rent"', self.html)
        self.assertIn('>Median Rent<', self.html)

    def test_total_savings_card_present(self):
        self.assertIn('id="total_savings"', self.html)
        self.assertIn('id="total_savings_yr"', self.html)
        self.assertIn('Total Monthly Savings', self.html)

    def test_renderdeals_computes_median(self):
        """renderDeals() should compute median from deals[].price."""
        # Locate the renderDeals function body
        idx = self.html.find('function renderDeals')
        self.assertGreater(idx, -1, 'renderDeals function not found')
        body = self.html[idx:idx + 6000]
        self.assertIn("median_rent", body)
        self.assertIn("priceVals", body)
        # Should round to nearest $50
        self.assertIn("/ 50)", body)

    def test_renderdeals_computes_total_savings(self):
        idx = self.html.find('function renderDeals')
        self.assertGreater(idx, -1)
        body = self.html[idx:idx + 8000]
        self.assertIn("total_savings", body)
        self.assertIn("savings += (fv - price)", body)
        # Should compute annualized figure
        self.assertIn("savings * 12", body)

    def test_renderdeals_empty_resets_new_cards(self):
        """If deals is empty, the new IDs should show '-' (not stale data)."""
        # Find the empty branch (not !deals || deals.length === 0)
        idx = self.html.find('if (!deals || deals.length === 0)')
        self.assertGreater(idx, -1)
        branch = self.html[idx:idx + 1500]
        self.assertIn("median_rent", branch)
        self.assertIn("total_savings", branch)
        self.assertIn("total_savings_yr", branch)

    def test_card_count_in_both_summary_bars(self):
        """Both summary bars (primary + post-similar-listings) should have
        the 5 cards now (Deals, Avg, Median, Best, Savings)."""
        # Direct approach: count occurrences of each card id in each bar block.
        # Each bar starts at "id=\"total_count\"" and extends to the next bar
        # (or end of the next stat-card row).
        bar_starts = [m.start() for m in __import__('re').finditer(r'id="total_count"', self.html)]
        self.assertGreaterEqual(len(bar_starts), 2,
            f'Expected at least 2 summary bars, found {len(bar_starts)}')
        # Slice each bar generously
        for bar_start in bar_starts[:2]:
            bar = self.html[bar_start:bar_start + 1500]
            for required_id in ('id="total_count"', 'id="avg_under"',
                                'id="median_rent"', 'id="best_deal"',
                                'id="total_savings"'):
                self.assertIn(required_id, bar,
                              f'Bar at offset {bar_start} missing {required_id}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
