"""
MC-327: Price per square foot ($/sqft) column + max $/sqft filter + sort option.

Tests verify the four behaviours agreed in MC-327's success criteria:
  1. _normalize_row() emits `price_per_sqft` only when BOTH price > 0 AND sqft > 0.
     Robust against None / empty string / 'nan' / zero / negative inputs.
  2. `_price_per_sqft_str` and `_price_per_sqft_class` formatters cover the
     common cases (whole dollar, fractional, missing data, class thresholds).
  3. /api/deals?price_per_sqft_max=N filters rows to those with non-null
     price_per_sqft <= N; rows missing sqft are excluded.
  4. /api/deals?sort=price_per_sqft orders by ascending price_per_sqft (best
     value first), with nulls last.
  5. /api/meta.price_per_sqft_stats has 7 keys (count_with_sqft,
     count_without_sqft, min, max, median, p25, p75) and the math is correct.
  6. The new filter combines cleanly with existing filters (source, is_new,
     beds_min) and the sort still works after combination.
  7. Live Flask test_client smoke: GET /api/deals returns rows with the
     new field; /api/meta has the new stats block.
"""
import importlib
import json
import os
import sys
import unittest
from unittest.mock import patch

# Make rent_finder importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import app as app_mod  # rent_finder/app.py
importlib.reload(app_mod)


class TestComputePricePerSqft(unittest.TestCase):
    """Backend helper: division + null/zero guard."""

    def test_basic(self):
        self.assertEqual(app_mod._compute_price_per_sqft(2200, 700), round(2200 / 700, 2))
        self.assertEqual(app_mod._compute_price_per_sqft(1800, 500), round(1800 / 500, 2))

    def test_none_inputs(self):
        self.assertIsNone(app_mod._compute_price_per_sqft(None, 500))
        self.assertIsNone(app_mod._compute_price_per_sqft(2200, None))
        self.assertIsNone(app_mod._compute_price_per_sqft(None, None))

    def test_empty_string_inputs(self):
        self.assertIsNone(app_mod._compute_price_per_sqft('', 500))
        self.assertIsNone(app_mod._compute_price_per_sqft(2200, ''))
        self.assertIsNone(app_mod._compute_price_per_sqft('None', 500))
        self.assertIsNone(app_mod._compute_price_per_sqft(2200, 'None'))

    def test_nan_inputs(self):
        self.assertIsNone(app_mod._compute_price_per_sqft(float('nan'), 500))
        self.assertIsNone(app_mod._compute_price_per_sqft(2200, float('nan')))
        self.assertIsNone(app_mod._compute_price_per_sqft('nan', 500))
        # NaN as float literal sometimes sneaks in via JSON
        import math
        self.assertIsNone(app_mod._compute_price_per_sqft(math.nan, 500))

    def test_zero_inputs(self):
        """Zero sqft would divide by zero - must return None, not raise."""
        self.assertIsNone(app_mod._compute_price_per_sqft(0, 500))
        self.assertIsNone(app_mod._compute_price_per_sqft(2200, 0))
        self.assertIsNone(app_mod._compute_price_per_sqft(0, 0))

    def test_negative_inputs(self):
        """Negative inputs (corrupt scraper data) → None."""
        self.assertIsNone(app_mod._compute_price_per_sqft(-100, 500))
        self.assertIsNone(app_mod._compute_price_per_sqft(2200, -500))

    def test_numeric_string_inputs(self):
        """Some scraper outputs use '650' for sqft - must coerce."""
        self.assertEqual(app_mod._compute_price_per_sqft('2200', '700'), round(2200 / 700, 2))

    def test_garbage_inputs(self):
        self.assertIsNone(app_mod._compute_price_per_sqft('abc', 'def'))
        self.assertIsNone(app_mod._compute_price_per_sqft(2200, 'def'))

    def test_rounding(self):
        """2 decimal places - matches UI '$X.XX' format."""
        result = app_mod._compute_price_per_sqft(2000, 777)  # 2.5746...
        self.assertEqual(result, round(result, 2))


class TestPricePerSqftFormatters(unittest.TestCase):
    """UI formatters: str + class."""

    def test_str_whole_dollar(self):
        self.assertEqual(app_mod._price_per_sqft_str(4), '$4')
        self.assertEqual(app_mod._price_per_sqft_str(3.0), '$3')

    def test_str_fractional(self):
        self.assertEqual(app_mod._price_per_sqft_str(3.75), '$3.75')
        self.assertEqual(app_mod._price_per_sqft_str(4.5), '$4.50')

    def test_str_missing(self):
        """None → em-dash placeholder (not an empty string)."""
        self.assertEqual(app_mod._price_per_sqft_str(None), '\u2014')

    def test_class_thresholds(self):
        # Cheap boundary
        self.assertEqual(app_mod._price_per_sqft_class(2.50), 'pps-cheap')
        self.assertEqual(app_mod._price_per_sqft_class(3.00), 'pps-cheap')
        # Fair boundary
        self.assertEqual(app_mod._price_per_sqft_class(3.01), 'pps-fair')
        self.assertEqual(app_mod._price_per_sqft_class(4.50), 'pps-fair')
        # Expensive
        self.assertEqual(app_mod._price_per_sqft_class(4.51), 'pps-expensive')
        self.assertEqual(app_mod._price_per_sqft_class(10.00), 'pps-expensive')

    def test_class_missing(self):
        """None → empty string (no chip rendered)."""
        self.assertEqual(app_mod._price_per_sqft_class(None), '')


class TestNormalizePricePerSqft(unittest.TestCase):
    """_normalize_row() emits price_per_sqft + helpers + handles missing sqft."""

    def _row(self, **kw):
        # A complete minimal listing dict. _normalize_row tolerates missing
        # keys because it falls back to defaults.
        base = {
            'title': 'Test',
            'neighborhood': 'Annex',
            'source': 'Kijiji',
            'price': 2500,
            'sqft': 800,
        }
        base.update(kw)
        return app_mod._normalize_row(base)

    def test_normalize_emits_price_per_sqft(self):
        row = self._row(price=2500, sqft=800)
        self.assertIsNotNone(row)
        self.assertEqual(row['price_per_sqft'], round(2500 / 800, 2))

    def test_normalize_missing_sqft_yields_none(self):
        row = self._row(price=2500, sqft=None)
        self.assertIsNone(row['price_per_sqft'])

    def test_normalize_missing_price_yields_none(self):
        row = self._row(price=None, sqft=800)
        self.assertIsNone(row['price_per_sqft'])

    def test_normalize_zero_sqft_yields_none(self):
        row = self._row(price=2500, sqft=0)
        self.assertIsNone(row['price_per_sqft'])

    def test_normalize_string_sqft(self):
        """Some scrapers store sqft as '700' or '700 sqft'."""
        row = self._row(price=2100, sqft='700')
        self.assertEqual(row['price_per_sqft'], 3.0)

    def test_normalize_string_price(self):
        row = self._row(price='2500', sqft=800)
        self.assertEqual(row['price_per_sqft'], round(2500 / 800, 2))

    def test_normalize_emits_str_helper(self):
        row = self._row(price=2500, sqft=800)
        # Either '$3.12' or '$3.13' depending on rounding
        self.assertTrue(row['price_per_sqft_str'].startswith('$'))
        self.assertNotEqual(row['price_per_sqft_str'], '\u2014')

    def test_normalize_emits_class_helper(self):
        row = self._row(price=2500, sqft=800)
        self.assertIn(row['price_per_sqft_class'], ('pps-cheap', 'pps-fair', 'pps-expensive', ''))

    def test_normalize_str_dash_for_missing(self):
        row = self._row(price=2500, sqft=None)
        self.assertEqual(row['price_per_sqft_str'], '\u2014')


class TestApiDealsPricePerSqftFilter(unittest.TestCase):
    """GET /api/deals?price_per_sqft_max=N narrows rows to <= cap."""

    def setUp(self):
        # Minimal stub loader: a small set of listings with known $/sqft.
        self.fixtures = [
            # cheap, valid sqft
            {'listing_id': 'a', 'price': 1200, 'sqft': 500, 'neighborhood': 'X', 'beds': 1, 'baths': 1, 'fair_value': 1500, 'pct_under': 20, 'score': 0.2, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},
            # mid, valid sqft
            {'listing_id': 'b', 'price': 2100, 'sqft': 500, 'neighborhood': 'X', 'beds': 1, 'baths': 1, 'fair_value': 2200, 'pct_under': 4.5, 'score': 0.045, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},
            # expensive, valid sqft
            {'listing_id': 'c', 'price': 4000, 'sqft': 500, 'neighborhood': 'X', 'beds': 2, 'baths': 1, 'fair_value': 3800, 'pct_under': -5.2, 'score': -0.052, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},
            # no sqft → cannot judge
            {'listing_id': 'd', 'price': 1500, 'sqft': '', 'neighborhood': 'X', 'beds': 1, 'baths': 1, 'fair_value': 1500, 'pct_under': 0, 'score': 0, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},
            # zero sqft
            {'listing_id': 'e', 'price': 1800, 'sqft': 0, 'neighborhood': 'X', 'beds': 1, 'baths': 1, 'fair_value': 1500, 'pct_under': -20, 'score': -0.2, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},
        ]
        self.normalized = [app_mod._normalize_row(d) for d in self.fixtures]
        # app._normalize_row returns None on bad rows (would be filtered later)
        self.normalized = [d for d in self.normalized if d is not None]

    def _app(self):
        app_mod.app.config['TESTING'] = True
        return app_mod.app.test_client()

    def _load(self, deals):
        return patch.object(app_mod, 'load_deals', return_value=deals)

    def test_filter_cap_includes_only_low_pps(self):
        deals = self.normalized
        with patch.object(app_mod, 'load_deals', return_value=deals):
            with self._app() as c:
                resp = c.get('/api/deals?price_per_sqft_max=3.0')
                self.assertEqual(resp.status_code, 200)
                body = resp.get_json()
                # b/c/f have pps >= 3.0; only 'a' (pps=2.4) qualifies. 'd' and 'e' have None pps.
                returned_ids = {d['listing_id'] for d in body['deals']}
                self.assertIn('a', returned_ids)
                # any with pps > 3.0 should NOT appear
                self.assertNotIn('b', returned_ids)
                self.assertNotIn('c', returned_ids)
                # missing-sqft rows are excluded
                self.assertNotIn('d', returned_ids)
                self.assertNotIn('e', returned_ids)

    def test_filter_no_cap_returns_all(self):
        deals = self.normalized
        with patch.object(app_mod, 'load_deals', return_value=deals):
            with self._app() as c:
                resp = c.get('/api/deals')
                self.assertEqual(resp.status_code, 200)
                body = resp.get_json()
                returned_ids = {d['listing_id'] for d in body['deals']}
                # Without the cap, all 5 rows are returned (sorted by score).
                self.assertEqual(returned_ids, {'a', 'b', 'c', 'd', 'e'})

    def test_filter_invalid_value_no_crash(self):
        """Non-numeric value → ignored (Filter None branch)."""
        deals = self.normalized
        with patch.object(app_mod, 'load_deals', return_value=deals):
            with self._app() as c:
                resp = c.get('/api/deals?price_per_sqft_max=abc')
                self.assertEqual(resp.status_code, 200)
                body = resp.get_json()
                self.assertEqual({d['listing_id'] for d in body['deals']}, {'a', 'b', 'c', 'd', 'e'})

    def test_filter_negative_cap_ignored(self):
        """Negative or zero caps are no-ops (don't return every row)."""
        deals = self.normalized
        with patch.object(app_mod, 'load_deals', return_value=deals):
            with self._app() as c:
                resp = c.get('/api/deals?price_per_sqft_max=0')
                self.assertEqual(resp.status_code, 200)
                body = resp.get_json()
                # cap <= 0 means we don't apply the filter (max_price_per_sqft > 0 guard)
                self.assertEqual({d['listing_id'] for d in body['deals']}, {'a', 'b', 'c', 'd', 'e'})


class TestApiDealsPricePerSqftSort(unittest.TestCase):
    """GET /api/deals?sort=price_per_sqft orders by ascending pps; nulls last."""

    def setUp(self):
        self.fixtures = [
            {'listing_id': 'hi', 'price': 4000, 'sqft': 500, 'neighborhood': 'X', 'beds': 2, 'baths': 1, 'fair_value': 3800, 'pct_under': -5.2, 'score': -0.052, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},  # 8.0
            {'listing_id': 'mid', 'price': 2100, 'sqft': 500, 'neighborhood': 'X', 'beds': 1, 'baths': 1, 'fair_value': 2200, 'pct_under': 4.5, 'score': 0.045, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},  # 4.2
            {'listing_id': 'lo', 'price': 1200, 'sqft': 500, 'neighborhood': 'X', 'beds': 1, 'baths': 1, 'fair_value': 1500, 'pct_under': 20, 'score': 0.2, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},  # 2.4
            {'listing_id': 'na', 'price': 1500, 'sqft': '', 'neighborhood': 'X', 'beds': 1, 'baths': 1, 'fair_value': 1500, 'pct_under': 0, 'score': 0, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},
        ]
        self.normalized = [app_mod._normalize_row(d) for d in self.fixtures]
        self.normalized = [d for d in self.normalized if d is not None]

    def _app(self):
        app_mod.app.config['TESTING'] = True
        return app_mod.app.test_client()

    def test_sort_ascending_low_to_high(self):
        with patch.object(app_mod, 'load_deals', return_value=self.normalized):
            with self._app() as c:
                resp = c.get('/api/deals?sort=price_per_sqft')
                self.assertEqual(resp.status_code, 200)
                body = resp.get_json()
                ids = [d['listing_id'] for d in body['deals']]
                # ASC: cheap first, then expensive, null last (treated as -1 by sort_key fallback)
                # sort uses -1 for missing data; lo (2.4) < mid (4.2) < hi (8.0) < na (-1)
                self.assertEqual(ids, ['lo', 'mid', 'hi', 'na'])

    def test_sort_pps_field_present_on_rows(self):
        with patch.object(app_mod, 'load_deals', return_value=self.normalized):
            with self._app() as c:
                resp = c.get('/api/deals?sort=price_per_sqft')
                body = resp.get_json()
                for d in body['deals']:
                    self.assertIn('price_per_sqft', d)
                    self.assertIn('price_per_sqft_str', d)
                    self.assertIn('price_per_sqft_class', d)


class TestApiDealsCombinedFilters(unittest.TestCase):
    """Filter combines cleanly with existing filters."""

    def setUp(self):
        self.fixtures = [
            # cheap kijiji 1BR w/ pps 2.4
            {'listing_id': 'k1', 'price': 1200, 'sqft': 500, 'neighborhood': 'Annex',
             'beds': 1, 'baths': 1, 'fair_value': 1500, 'pct_under': 20, 'score': 0.2,
             'days_ago': 5, 'is_stale': False, 'is_new': False, 'source': 'kijiji',
             'first_seen': '2026-07-08T00:00:00Z'},
            # cheap CL 1BR w/ pps 2.4 (would qualify pps_max=3; but source filter rejects if craigslist)
            {'listing_id': 'c1', 'price': 1200, 'sqft': 500, 'neighborhood': 'Annex',
             'beds': 1, 'baths': 1, 'fair_value': 1500, 'pct_under': 20, 'score': 0.2,
             'days_ago': 5, 'is_stale': False, 'is_new': False, 'source': 'craigslist',
             'first_seen': '2026-07-08T00:00:00Z'},
            # expensive kijiji w/ pps 4.2 (excluded by cap)
            {'listing_id': 'k2', 'price': 2100, 'sqft': 500, 'neighborhood': 'Annex',
             'beds': 1, 'baths': 1, 'fair_value': 2200, 'pct_under': 4.5, 'score': 0.045,
             'days_ago': 5, 'is_stale': False, 'is_new': False, 'source': 'kijiji',
             'first_seen': '2026-07-08T00:00:00Z'},
            # 2BR cheap kijiji
            {'listing_id': 'k3', 'price': 2400, 'sqft': 1000, 'neighborhood': 'Annex',
             'beds': 2, 'baths': 1, 'fair_value': 2400, 'pct_under': 0, 'score': 0,
             'days_ago': 5, 'is_stale': False, 'is_new': False, 'source': 'kijiji',
             'first_seen': '2026-07-08T00:00:00Z'},
        ]
        self.normalized = [app_mod._normalize_row(d) for d in self.fixtures]
        self.normalized = [d for d in self.normalized if d is not None]

    def _app(self):
        app_mod.app.config['TESTING'] = True
        return app_mod.app.test_client()

    def test_combined_pps_max_and_source(self):
        with patch.object(app_mod, 'load_deals', return_value=self.normalized):
            with self._app() as c:
                resp = c.get('/api/deals?price_per_sqft_max=3.0&source=kijiji')
                self.assertEqual(resp.status_code, 200)
                body = resp.get_json()
                ids = {d['listing_id'] for d in body['deals']}
                # k1 qualifies (pps=2.4, kijiji, 1BR); k2 pps=4.2 (cap), k3 is 2BR (no beds_min=1)
                self.assertIn('k1', ids)
                self.assertNotIn('c1', ids)  # excluded by source
                self.assertNotIn('k2', ids)  # excluded by pps cap

    def test_combined_pps_max_and_beds(self):
        with patch.object(app_mod, 'load_deals', return_value=self.normalized):
            with self._app() as c:
                resp = c.get('/api/deals?price_per_sqft_max=3.0&beds_min=2')
                body = resp.get_json()
                ids = {d['listing_id'] for d in body['deals']}
                # k3 qualifies (pps=2.4 and 2BR); k1 is 1BR excluded by beds_min=2
                self.assertIn('k3', ids)
                self.assertNotIn('k1', ids)


class TestMetaPricePerSqftStats(unittest.TestCase):
    """/api/meta.price_per_sqft_stats shape + math."""

    def setUp(self):
        # 4 listings: 2 cheap, 1 fair, 1 expensive, 1 missing-sqft → expect
        # count_with_sqft=4, count_without_sqft=1, valid min/max/median/p25/p75
        self.fixtures = [
            {'listing_id': 'a', 'price': 1200, 'sqft': 500, 'neighborhood': 'X', 'beds': 1, 'baths': 1, 'fair_value': 1500, 'pct_under': 20, 'score': 0.2, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},  # 2.4
            {'listing_id': 'b', 'price': 2100, 'sqft': 500, 'neighborhood': 'X', 'beds': 1, 'baths': 1, 'fair_value': 2200, 'pct_under': 4.5, 'score': 0.045, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},  # 4.2
            {'listing_id': 'c', 'price': 4000, 'sqft': 500, 'neighborhood': 'X', 'beds': 2, 'baths': 1, 'fair_value': 3800, 'pct_under': -5.2, 'score': -0.052, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},  # 8.0
            {'listing_id': 'd', 'price': 1500, 'sqft': 500, 'neighborhood': 'X', 'beds': 1, 'baths': 1, 'fair_value': 1500, 'pct_under': 0, 'score': 0, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},  # 3.0
            {'listing_id': 'e', 'price': 1500, 'sqft': '', 'neighborhood': 'X', 'beds': 1, 'baths': 1, 'fair_value': 1500, 'pct_under': 0, 'score': 0, 'days_ago': 5, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},  # None
        ]
        self.normalized = [app_mod._normalize_row(d) for d in self.fixtures]
        self.normalized = [d for d in self.normalized if d is not None]

    def _app(self):
        app_mod.app.config['TESTING'] = True
        return app_mod.app.test_client()

    def test_meta_stats_shape(self):
        with patch.object(app_mod, 'load_deals', return_value=self.normalized):
            with self._app() as c:
                resp = c.get('/api/meta')
                body = resp.get_json()
                self.assertIn('price_per_sqft_stats', body)
                stats = body['price_per_sqft_stats']
                # 7 keys total
                expected = {'count_with_sqft', 'count_without_sqft', 'min', 'max', 'median', 'p25', 'p75'}
                self.assertEqual(set(stats.keys()), expected)

    def test_meta_stats_counts(self):
        with patch.object(app_mod, 'load_deals', return_value=self.normalized):
            with self._app() as c:
                resp = c.get('/api/meta')
                stats = resp.get_json()['price_per_sqft_stats']
                # rows a/b/c/d have valid pps; row e has None
                self.assertEqual(stats['count_with_sqft'], 4)
                self.assertEqual(stats['count_without_sqft'], 1)

    def test_meta_stats_min_max(self):
        with patch.object(app_mod, 'load_deals', return_value=self.normalized):
            with self._app() as c:
                resp = c.get('/api/meta')
                stats = resp.get_json()['price_per_sqft_stats']
                # pps values sorted: [2.4, 3.0, 4.2, 8.0]
                self.assertEqual(stats['min'], 2.4)
                self.assertEqual(stats['max'], 8.0)
                self.assertEqual(stats['median'], 3.6)  # midpoint of 3.0 and 4.2
                # p25: position = 0.25 * 3 = 0.75 → between 2.4 and 3.0 (linear interp)
                self.assertEqual(stats['p25'], round(2.4 + 0.75 * (3.0 - 2.4), 2))
                # p75: position = 0.25 * 9 = 2.25 → between 4.2 and 8.0
                self.assertEqual(stats['p75'], round(4.2 + 0.25 * (8.0 - 4.2), 2))

    def test_meta_stats_empty(self):
        """No listings → all NaN-equivalent values are None, not crashes."""
        with patch.object(app_mod, 'load_deals', return_value=[]):
            with self._app() as c:
                resp = c.get('/api/meta')
                body = resp.get_json()
                self.assertIn('price_per_sqft_stats', body)
                stats = body['price_per_sqft_stats']
                self.assertEqual(stats['count_with_sqft'], 0)
                self.assertIsNone(stats['min'])
                self.assertIsNone(stats['max'])
                self.assertIsNone(stats['median'])


class TestLiveSmoke(unittest.TestCase):
    """True end-to-end: feed real Flask test_client with stub deals."""

    def _app(self):
        app_mod.app.config['TESTING'] = True
        return app_mod.app.test_client()

    def test_smoke_deal_response_shape(self):
        fixtures = [
            {'listing_id': 'x', 'price': 2000, 'sqft': 600, 'neighborhood': 'X', 'beds': 1, 'baths': 1, 'fair_value': 2200, 'pct_under': 9, 'score': 0.09, 'days_ago': 4, 'is_stale': False, 'is_new': False, 'first_seen': '2026-07-08T00:00:00Z'},
        ]
        normalized = [app_mod._normalize_row(d) for d in fixtures]
        with patch.object(app_mod, 'load_deals', return_value=normalized):
            with self._app() as c:
                resp = c.get('/api/deals')
                self.assertEqual(resp.status_code, 200)
                body = resp.get_json()
                self.assertIn('deals', body)
                self.assertEqual(len(body['deals']), 1)
                row = body['deals'][0]
                self.assertEqual(row['price_per_sqft'], round(2000 / 600, 2))
                self.assertIn('price_per_sqft_str', row)
                self.assertIn('price_per_sqft_class', row)


if __name__ == '__main__':
    unittest.main(verbosity=2)
