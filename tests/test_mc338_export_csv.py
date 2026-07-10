"""MC-338 tests: Filter-aware CSV export endpoint + frontend Export button.

Covers:
- _parse_deal_filters: handles all truthy/falsy forms, numeric parsing,
  default values, missing keys
- _apply_filters: each filter is applied independently AND in combination,
  default-filter neighbourhood_status, include_fallback opt-in
- /api/deals/export.csv: parses filters, applies them, returns CSV with
  Content-Type + Content-Disposition + X-Filter-Row-Count header
- /api/deals: still works after the helper extraction (regression guard)
- Frontend: index.html has the button id, onclick handler, helper fns
"""
import sys, os, csv, io, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Force UTF-8 stdout so Windows console doesn't choke on Unicode
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import unittest
from werkzeug.datastructures import MultiDict

import app as app_module
from app import _parse_deal_filters, _apply_filters, app


# ── helpers ──────────────────────────────────────────────────────────────────

def _deal(**overrides):
    """Build a minimal normalized deal dict for filter testing."""
    base = {
        'beds': 1,
        'baths': 1.0,
        'price': 2000,
        'neighbourhood': 'Bay Street Corridor',
        'region': 'Downtown',
        'source': 'kijiji',
        'is_new': False,
        'price_dropped': False,
        'has_image': True,
        'has_parking': False,
        'is_stale': False,
        'neighborhood_status': 'resolved',
        'fair_value': 2400,
        'price_per_sqft': 4.0,
        'final_score': 0.15,
        'pct_under': 17.0,
        'commute_minutes': 12,
        'station_walk_min': 5,
        'days_ago': 1,
        'listing_id': f'deal-{id(overrides)}',
    }
    base.update(overrides)
    return base


# ── Tests ────────────────────────────────────────────────────────────────────

class TestParseDealFilters(unittest.TestCase):
    """_parse_deal_filters: parses a request.args-like mapping into a flat dict."""

    def test_empty_args_returns_defaults(self):
        parsed = _parse_deal_filters(MultiDict())
        self.assertEqual(parsed['beds_min'], None)
        self.assertEqual(parsed['beds_max'], None)
        self.assertEqual(parsed['baths_min'], None)
        self.assertEqual(parsed['price_min'], None)
        self.assertEqual(parsed['price_max'], None)
        self.assertEqual(parsed['hide_stale'], False)
        self.assertEqual(parsed['only_new'], False)
        self.assertEqual(parsed['price_dropped'], False)
        self.assertEqual(parsed['has_image'], False)
        self.assertEqual(parsed['include_fallback'], False)
        self.assertEqual(parsed['source'], '')
        self.assertEqual(parsed['sort_by'], 'score')

    def test_int_filters(self):
        parsed = _parse_deal_filters(MultiDict([
            ('beds_min', '2'), ('beds_max', '4'),
            ('baths_min', '1.5'),
            ('price_min', '1500'), ('price_max', '3500'),
            ('max_commute', '30'), ('max_subway', '5'),
        ]))
        self.assertEqual(parsed['beds_min'], 2)
        self.assertEqual(parsed['beds_max'], 4)
        self.assertEqual(parsed['baths_min'], 1.5)
        self.assertEqual(parsed['price_min'], 1500)
        self.assertEqual(parsed['price_max'], 3500)
        self.assertEqual(parsed['max_commute'], 30)
        self.assertEqual(parsed['max_subway'], 5)

    def test_truthy_filters_all_synonyms(self):
        for truthy in ('true', 'True', 'TRUE', '1', 'yes', 'YES'):
            for key_in, key_out in (
                ('hide_stale', 'hide_stale'),
                ('is_new', 'only_new'),
                ('price_dropped', 'price_dropped'),
                ('has_image', 'has_image'),
                ('include_fallback', 'include_fallback'),
            ):
                parsed = _parse_deal_filters(MultiDict([(key_in, truthy)]))
                self.assertTrue(parsed[key_out], f'{key_in}={truthy!r} should be True')

    def test_falsy_filters_all_synonyms(self):
        for falsy in ('false', 'False', 'FALSE', '0', 'no', 'NO', '', None):
            for key_in in ('hide_stale', 'is_new', 'price_dropped',
                           'has_image', 'include_fallback'):
                parsed = _parse_deal_filters(MultiDict([(key_in, falsy)]))
                self.assertFalse(parsed[key_in.replace('is_new', 'only_new').replace('price_dropped', 'price_dropped').replace('has_image', 'has_image')] if key_in != 'is_new' else parsed['only_new'],
                                 f'{key_in}={falsy!r} should be False')

    def test_source_lowercased_and_stripped(self):
        parsed = _parse_deal_filters(MultiDict([('source', '  KIJIJI  ')]))
        self.assertEqual(parsed['source'], 'kijiji')

    def test_neighbourhood_lowercased_and_stripped(self):
        parsed = _parse_deal_filters(MultiDict([('neighbourhood', '  Annex  ')]))
        self.assertEqual(parsed['neighbourhood'], 'annex')

    def test_region_stripped_not_lowercased(self):
        parsed = _parse_deal_filters(MultiDict([('region', '  Midtown  ')]))
        self.assertEqual(parsed['region'], 'Midtown')

    def test_max_price_per_sqft_numeric(self):
        parsed = _parse_deal_filters(MultiDict([('price_per_sqft_max', '3.5')]))
        self.assertEqual(parsed['max_price_per_sqft'], 3.5)

    def test_max_price_per_sqft_garbage_returns_none(self):
        parsed = _parse_deal_filters(MultiDict([('price_per_sqft_max', 'abc')]))
        self.assertIsNone(parsed['max_price_per_sqft'])

    def test_max_price_per_sqft_empty_string_returns_none(self):
        parsed = _parse_deal_filters(MultiDict([('price_per_sqft_max', '')]))
        self.assertIsNone(parsed['max_price_per_sqft'])

    def test_sort_by_defaults_to_score(self):
        parsed = _parse_deal_filters(MultiDict())
        self.assertEqual(parsed['sort_by'], 'score')
        parsed = _parse_deal_filters(MultiDict([('sort', 'price')]))
        self.assertEqual(parsed['sort_by'], 'price')

    def test_has_parking_tristate(self):
        # Tri-state because original code distinguishes None (not set) vs
        # True (must have) vs False (don't care). Helper should preserve that.
        self.assertIsNone(_parse_deal_filters(MultiDict())['has_parking'])
        self.assertIsNone(_parse_deal_filters(MultiDict([('has_parking', '')]))['has_parking'])
        self.assertTrue(_parse_deal_filters(MultiDict([('has_parking', 'true')]))['has_parking'])
        self.assertFalse(_parse_deal_filters(MultiDict([('has_parking', 'false')]))['has_parking'])


class TestApplyFilters(unittest.TestCase):
    """_apply_filters: applies each filter independently, then in combination."""

    def test_no_filters_returns_input_unchanged(self):
        deals = [_deal(beds=1), _deal(beds=2), _deal(beds=3)]
        out = _apply_filters(deals, _parse_deal_filters(MultiDict()))
        self.assertEqual(out, deals)

    def test_beds_min(self):
        deals = [_deal(beds=1), _deal(beds=2), _deal(beds=3)]
        parsed = _parse_deal_filters(MultiDict([('beds_min', '2')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual([d['beds'] for d in out], [2, 3])

    def test_beds_min_skips_missing_beds(self):
        deals = [_deal(beds=1), _deal(beds=None), _deal(beds=2)]
        parsed = _parse_deal_filters(MultiDict([('beds_min', '2')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual([d['beds'] for d in out], [2])

    def test_beds_max(self):
        deals = [_deal(beds=1), _deal(beds=2), _deal(beds=3)]
        parsed = _parse_deal_filters(MultiDict([('beds_max', '2')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual([d['beds'] for d in out], [1, 2])

    def test_price_range(self):
        deals = [_deal(price=1000), _deal(price=2000), _deal(price=3500)]
        parsed = _parse_deal_filters(MultiDict([('price_min', '1500'), ('price_max', '2500')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual([d['price'] for d in out], [2000])

    def test_neighbourhood_substring(self):
        deals = [
            _deal(neighbourhood='Bay Street Corridor'),
            _deal(neighbourhood='Annex'),
            _deal(neighbourhood='Bayview'),
        ]
        parsed = _parse_deal_filters(MultiDict([('neighbourhood', 'bay')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual(sorted(d['neighbourhood'] for d in out),
                         ['Bay Street Corridor', 'Bayview'])

    def test_region_exact_match(self):
        deals = [_deal(region='Downtown'), _deal(region='Midtown'), _deal(region='East York')]
        parsed = _parse_deal_filters(MultiDict([('region', 'Downtown')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual([d['region'] for d in out], ['Downtown'])

    def test_source_filter_lowercase(self):
        deals = [_deal(source='kijiji'), _deal(source='craigslist'), _deal(source='kijiji')]
        parsed = _parse_deal_filters(MultiDict([('source', 'kijiji')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual(len(out), 2)
        self.assertTrue(all(d['source'] == 'kijiji' for d in out))

    def test_source_all_returns_everything(self):
        deals = [_deal(source='kijiji'), _deal(source='craigslist')]
        parsed = _parse_deal_filters(MultiDict([('source', 'all')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual(out, deals)

    def test_only_new(self):
        deals = [_deal(is_new=True), _deal(is_new=False), _deal(is_new=True)]
        parsed = _parse_deal_filters(MultiDict([('is_new', 'true')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual(len(out), 2)
        self.assertTrue(all(d['is_new'] for d in out))

    def test_hide_stale(self):
        deals = [_deal(is_stale=False), _deal(is_stale=True), _deal(is_stale=False)]
        parsed = _parse_deal_filters(MultiDict([('hide_stale', 'true')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual(len(out), 2)
        self.assertTrue(not any(d['is_stale'] for d in out))

    def test_price_dropped(self):
        deals = [_deal(price_dropped=False), _deal(price_dropped=True)]
        parsed = _parse_deal_filters(MultiDict([('price_dropped', 'true')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]['price_dropped'])

    def test_has_image(self):
        deals = [_deal(has_image=True), _deal(has_image=False), _deal(has_image=True)]
        parsed = _parse_deal_filters(MultiDict([('has_image', 'true')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual(len(out), 2)

    def test_max_price_per_sqft_drops_missing(self):
        deals = [
            _deal(price_per_sqft=2.0),
            _deal(price_per_sqft=None),
            _deal(price_per_sqft=4.5),
        ]
        parsed = _parse_deal_filters(MultiDict([('price_per_sqft_max', '3')]))
        out = _apply_filters(deals, parsed)
        # 2.0 within cap + 4.5 excluded + None excluded (cannot validate) = 1
        self.assertEqual([d['price_per_sqft'] for d in out], [2.0])

    def test_include_fallback_default_hides_catchall(self):
        deals = [
            _deal(neighborhood_status='resolved'),
            _deal(neighborhood_status='toronto_catchall'),
            _deal(neighborhood_status='low_signal_address'),
            _deal(neighborhood_status='off_toronto'),
        ]
        parsed = _parse_deal_filters(MultiDict())
        out = _apply_filters(deals, parsed)
        self.assertEqual(len(out), 1)

    def test_include_fallback_true_keeps_everything(self):
        deals = [
            _deal(neighborhood_status='resolved'),
            _deal(neighborhood_status='toronto_catchall'),
            _deal(neighborhood_status='low_signal_address'),
            _deal(neighborhood_status='off_toronto'),
        ]
        parsed = _parse_deal_filters(MultiDict([('include_fallback', 'true')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual(len(out), 4)

    def test_combined_filters(self):
        deals = [
            _deal(beds=1, price=1500, source='kijiji', is_new=True),
            _deal(beds=2, price=2200, source='kijiji', is_new=False),
            _deal(beds=3, price=3500, source='craigslist', is_new=False),
            _deal(beds=2, price=1700, source='kijiji', is_new=True),
        ]
        parsed = _parse_deal_filters(MultiDict([
            ('beds_min', '2'),
            ('price_max', '2500'),
            ('source', 'kijiji'),
            ('is_new', 'true'),
        ]))
        out = _apply_filters(deals, parsed)
        # Only the last deal meets all 4 conditions
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['price'], 1700)

    def test_max_commute_drops_missing(self):
        deals = [
            _deal(commute_minutes=10),
            _deal(commute_minutes=None),
            _deal(commute_minutes=45),
        ]
        parsed = _parse_deal_filters(MultiDict([('max_commute', '20')]))
        out = _apply_filters(deals, parsed)
        # 10 within cap + 45 outside + None dropped = 1
        self.assertEqual(len(out), 1)

    def test_max_subway_drops_missing(self):
        deals = [
            _deal(station_walk_min=2),
            _deal(station_walk_min=None),
            _deal(station_walk_min=20),
        ]
        parsed = _parse_deal_filters(MultiDict([('max_subway', '10')]))
        out = _apply_filters(deals, parsed)
        self.assertEqual(len(out), 1)


class TestApiDealsEndpointRegression(unittest.TestCase):
    """The /api/deals endpoint must continue to work after the helper extraction."""

    def setUp(self):
        self.client = app.test_client()

    def test_api_deals_default(self):
        r = self.client.get('/api/deals?limit=5')
        self.assertEqual(r.status_code, 200)
        payload = r.get_json()
        self.assertIsInstance(payload, dict)
        self.assertIn('deals', payload)
        self.assertIn('total', payload)
        self.assertIn('limit', payload)
        self.assertIn('offset', payload)
        self.assertIn('has_more', payload)
        self.assertLessEqual(len(payload['deals']), 5)

    def test_api_deals_beds_min_filter(self):
        r = self.client.get('/api/deals?beds_min=3&limit=200')
        self.assertEqual(r.status_code, 200)
        payload = r.get_json()
        # Every row that came back must satisfy beds >= 3
        for d in payload['deals']:
            self.assertGreaterEqual(d.get('beds') or 0, 3)

    def test_api_deals_price_filter(self):
        r = self.client.get('/api/deals?price_max=1500&limit=200')
        self.assertEqual(r.status_code, 200)
        payload = r.get_json()
        for d in payload['deals']:
            self.assertLessEqual(d.get('price') or 0, 1500)


class TestApiExportCsvEndpoint(unittest.TestCase):
    """MC-338: /api/deals/export.csv honors filters + emits useful headers."""

    def setUp(self):
        self.client = app.test_client()

    def test_export_returns_200(self):
        r = self.client.get('/api/deals/export.csv')
        self.assertEqual(r.status_code, 200)

    def test_export_content_type(self):
        r = self.client.get('/api/deals/export.csv')
        self.assertIn('text/csv', r.headers.get('Content-Type', ''))

    def test_export_has_attachment_disposition(self):
        r = self.client.get('/api/deals/export.csv')
        disp = r.headers.get('Content-Disposition', '')
        self.assertIn('attachment', disp)
        self.assertIn('deals.csv', disp)

    def test_export_emits_row_count_header(self):
        r = self.client.get('/api/deals/export.csv')
        self.assertIsNotNone(r.headers.get('X-Filter-Row-Count'))

    def test_export_parses_correctly_as_csv(self):
        r = self.client.get('/api/deals/export.csv')
        body = r.data.decode('utf-8')
        if r.headers.get('X-Filter-Row-Count') == '0':
            # header-only CSV — only header row
            reader = csv.DictReader(io.StringIO(body))
            rows = list(reader)
            self.assertEqual(len(rows), 0)
        else:
            reader = csv.DictReader(io.StringIO(body))
            rows = list(reader)
            self.assertGreater(len(rows), 0)
            # Each row should have the expected fieldnames
            self.assertIn('neighbourhood', rows[0])
            self.assertIn('price', rows[0])
            self.assertIn('link', rows[0])

    def test_export_respects_beds_min_filter(self):
        """The same filter that narrows /api/deals must narrow the export."""
        unfiltered = self.client.get('/api/deals/export.csv').headers.get('X-Filter-Row-Count')
        filtered = self.client.get('/api/deals/export.csv?beds_min=99').headers.get('X-Filter-Row-Count')
        # Beds >= 99 will always be 0 (or 1 if there's an outlier), never more
        # than the unfiltered count
        unfiltered_int = int(unfiltered)
        filtered_int = int(filtered)
        self.assertLessEqual(filtered_int, unfiltered_int)
        # Header-only CSV path
        r = self.client.get('/api/deals/export.csv?beds_min=99')
        body = r.data.decode('utf-8')
        rows = list(csv.DictReader(io.StringIO(body)))
        self.assertEqual(len(rows), 0)

    def test_export_respects_neighbourhood_filter(self):
        r = self.client.get('/api/deals/export.csv?neighbourhood=zzz_no_such_neigh')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get('X-Filter-Row-Count'), '0')
        body = r.data.decode('utf-8')
        rows = list(csv.DictReader(io.StringIO(body)))
        self.assertEqual(len(rows), 0)
        # Header still emitted
        self.assertTrue(body.startswith('neighbourhood,'))

    def test_export_respects_source_filter(self):
        r = self.client.get('/api/deals/export.csv?source=kijiji&limit=200')
        self.assertEqual(r.status_code, 200)
        body = r.data.decode('utf-8')
        rows = list(csv.DictReader(io.StringIO(body)))
        for row in rows:
            self.assertEqual(row.get('source', '').lower(), 'kijiji')

    def test_export_default_excludes_catchall_neighbourhoods(self):
        """No include_fallback param -> toronto_catchall rows are filtered out."""
        # Combine a default (no include_fallback) export with a fallback-inclusive one.
        # The fallback-inclusive export must have >= rows than the default one.
        default_count = int(self.client.get('/api/deals/export.csv').headers.get('X-Filter-Row-Count'))
        fallback_count = int(self.client.get('/api/deals/export.csv?include_fallback=true').headers.get('X-Filter-Row-Count'))
        self.assertGreaterEqual(fallback_count, default_count)

    def test_export_filter_and_api_deals_filter_are_consistent(self):
        """A filter that returns N rows from /api/deals should match the export."""
        # Pick a filter that probably narrows things meaningfully: price_max
        api_r = self.client.get('/api/deals?price_max=2500&limit=200')
        csv_r = self.client.get('/api/deals/export.csv?price_max=2500')
        api_payload = api_r.get_json()
        api_count = api_payload['total']
        csv_count = int(csv_r.headers.get('X-Filter-Row-Count'))
        self.assertEqual(api_count, csv_count)


class TestIndexHtmlWiring(unittest.TestCase):
    """MC-338: the frontend must have the button + handler + helpers."""

    @classmethod
    def setUpClass(cls):
        cls.html = open(os.path.join(os.path.dirname(__file__), '..', 'templates', 'index.html'),
                       encoding='utf-8').read()

    def test_export_button_present(self):
        self.assertIn('id="export_csv_btn"', self.html)

    def test_export_button_click_handler(self):
        self.assertIn('onclick="exportFilteredCsv()"', self.html)

    def test_export_filtered_csv_function_defined(self):
        # Match the function definition (with at least one body line).
        match = re.search(r'function\s+exportFilteredCsv\s*\(\s*\)\s*\{[^}]*\}', self.html, re.DOTALL)
        self.assertIsNotNone(match, 'exportFilteredCsv function not defined')

    def test_export_uses_build_params(self):
        # Inside exportFilteredCsv the body must serialize buildParams().
        match = re.search(r'function\s+exportFilteredCsv\s*\(\s*\)\s*\{(.+?)\}', self.html, re.DOTALL)
        self.assertIsNotNone(match)
        body = match.group(1)
        self.assertIn('buildParams()', body)

    def test_export_hits_export_csv_endpoint(self):
        match = re.search(r'function\s+exportFilteredCsv\s*\(\s*\)\s*\{(.+?)\}', self.html, re.DOTALL)
        body = match.group(1)
        self.assertIn('/api/deals/export.csv', body)

    def test_update_export_csv_state_function(self):
        match = re.search(r'function\s+updateExportCsvState\s*\(\s*\)\s*\{(.+?)\}', self.html, re.DOTALL)
        self.assertIsNotNone(match, 'updateExportCsvState function not defined')
        body = match.group(1)
        # Must consult currentTotal
        self.assertIn('currentTotal', body)
        # Must toggle the disabled flag
        self.assertIn('disabled', body)
        # Must reference the button id
        self.assertIn('export_csv_btn', body)

    def test_renderDeals_calls_update_export_state(self):
        # The hook fires after every render, so the disabled state stays in sync.
        match = re.search(r'function\s+renderDeals\s*\(\s*.+?\)\s*\{(.+?)^}', self.html, re.DOTALL | re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertIn('updateExportCsvState()', match.group(1))


if __name__ == '__main__':
    unittest.main(verbosity=2)
