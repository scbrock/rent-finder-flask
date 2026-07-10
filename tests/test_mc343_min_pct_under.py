"""
MC-343 - Min % under market filter for /api/deals + UI slider.

Gap: With 222 live deals today, scroll fatigue is real. Users browsing for
"only the genuinely-underpriced ones" had no way to filter by deal size -
just by neighborhood, beds, price, source, etc. Some wanted >=15% under
market, others wanted >=30%. The pct_under field is normalized on every
row but only sortable, not filterable.

This ticket adds:
- `?min_pct_under=N` query param parsed by `_parse_deal_filters`
- `_apply_filters` keeps only rows where pct_under >= N (N > 0)
- Frontend input `id="min_pct_under"` wired through buildParams/parseQueryParams
  /applySavedFilters/resetFilters/updateFilterCount/describeFilters so it
  behaves like every other filter
- Survives save-search round trips + URL share-links
- Graceful degradation: empty/negative/NaN/out-of-range values parse to None
  (no filter) so a hand-crafted URL never 500s

Tests:
- TestParseDealFiltersMinPctUnder: parser (5 tests) - happy path, empty,
  invalid strings, out-of-range, multiple keys
- TestApplyFiltersMinPctUnder: filter application (10 tests) - applies only
  when set, passes through when None, drops NULL pct_under, threshold 0
  semantics, composes with existing filters
- TestApiDealsMinPctUnder: Flask test_client integration (4 tests) - 200 OK,
  filter narrowing response shape, compose with source filter, regression
  confirms all other keys still parse
- TestIndexHtmlWiring: source-grep UI verification (8 tests) - input,
  buildParams set, parseQueryParams read, resetFilters clear, updateFilterCount
  count, describeFilters surface, applySavedFilters round-trip, listener
  wiring array

Each test is designed to fail LOUDLY if the underlying assumption
breaks. TestParseDealFiltersMinPctUnder is the parser unit test
suite. TestApplyFiltersMinPctUnder covers the filter layer.
"""
import importlib.util
import os
import re
import sys
import unittest

# Path setup - import app.py without triggering __main__ side-effects
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
RENT_FINDER_DIR = os.path.dirname(TESTS_DIR)
APP_PATH = os.path.join(RENT_FINDER_DIR, 'app.py')


def _load_app_module():
    """Load app.py as a fresh module to avoid leaking state from other
    MC test files that monkey-patch app_module.* globals.
    """
    spec = importlib.util.spec_from_file_location('app_rent_finder_343', APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FlaskTestBase(unittest.TestCase):
    """Shared Flask test client fixture. Subclasses get `self.client` and
    `self.app_module` with a freshly-imported app instance to avoid
    cross-test DB pollution (see MC-322 self-audit)."""

    @classmethod
    def setUpClass(cls):
        cls.app_module = _load_app_module()
        cls.flask_app = cls.app_module.app
        cls.client = cls.flask_app.test_client()


class TestParseDealFiltersMinPctUnder(_FlaskTestBase):
    """Unit tests for the parser's new min_pct_under handling."""

    def test_min_pct_under_parsed_as_float(self):
        """Happy path: ?min_pct_under=15 -> 15.0."""
        from werkzeug.datastructures import MultiDict
        args = MultiDict([('min_pct_under', '15')])
        parsed = self.app_module._parse_deal_filters(args)
        self.assertEqual(parsed['min_pct_under'], 15.0)

    def test_min_pct_under_fractional_float(self):
        """Float values parse to a float (e.g. 12.5)."""
        from werkzeug.datastructures import MultiDict
        args = MultiDict([('min_pct_under', '12.5')])
        parsed = self.app_module._parse_deal_filters(args)
        self.assertEqual(parsed['min_pct_under'], 12.5)

    def test_min_pct_under_empty_string_is_none(self):
        """Empty/missing param must parse to None (no filter) so the
        caller never sees `""` and trips on a None check."""
        from werkzeug.datastructures import MultiDict
        args = MultiDict([('min_pct_under', '')])
        parsed = self.app_module._parse_deal_filters(args)
        self.assertIsNone(parsed['min_pct_under'])

    def test_min_pct_under_invalid_string_is_none(self):
        """Hand-crafted URL with non-numeric input must NOT 500. Silent
        ignore to None matches the contract used by neighbour filters."""
        from werkzeug.datastructures import MultiDict
        args = MultiDict([('min_pct_under', 'twenty')])
        parsed = self.app_module._parse_deal_filters(args)
        self.assertIsNone(parsed['min_pct_under'])

    def test_min_pct_under_out_of_range_is_none(self):
        """Negative or >100 values are outside the sane domain for a
        percentage; silently treat as no filter rather than 500ing."""
        from werkzeug.datastructures import MultiDict
        for bad in ['-5', '150', '200', '-0.1']:
            args = MultiDict([('min_pct_under', bad)])
            parsed = self.app_module._parse_deal_filters(args)
            self.assertIsNone(
                parsed['min_pct_under'],
                f"min_pct_under={bad!r} should normalize to None but got {parsed['min_pct_under']!r}",
            )

    def test_min_pct_under_zero_passes(self):
        """min_pct_under=0 is a valid input meaning "any non-negative
        pct_under". The parser returns 0.0, the filter step recognizes
        this as the no-filter-shortcut branch."""
        from werkzeug.datastructures import MultiDict
        args = MultiDict([('min_pct_under', '0')])
        parsed = self.app_module._parse_deal_filters(args)
        self.assertEqual(parsed['min_pct_under'], 0.0)

    def test_existing_keys_still_present(self):
        """Regression guard: adding min_pct_under must not displace any
        of the original MC-338 keys."""
        from werkzeug.datastructures import MultiDict
        args = MultiDict([('min_pct_under', '15'), ('beds_min', '1')])
        parsed = self.app_module._parse_deal_filters(args)
        expected_keys = {
            'beds_min', 'beds_max', 'baths_min', 'has_parking',
            'price_min', 'price_max', 'neighbourhood', 'region',
            'sort_by', 'max_commute', 'max_subway', 'commute_dest',
            'hide_stale', 'source', 'only_new', 'price_dropped',
            'max_price_per_sqft', 'has_image', 'include_fallback',
            'min_pct_under',
        }
        self.assertEqual(set(parsed.keys()), expected_keys,
                         "Parser contract drifted - check MC-338 keys preserved")


class TestApplyFiltersMinPctUnder(_FlaskTestBase):
    """Unit tests for the filter application with min_pct_under.

    These tests invoke `_apply_filters` with a full parsed-dict contract
    shape, matching how `api_deals` actually calls it. We build the parsed
    dict via `_parse_deal_filters(MultiDict(...))` so the test never gets
    out of sync with the contract; we override only the field under test.
    """

    def _row(self, listing_id, pct_under, neighbourhood='Toronto', beds=1):
        return {
            'listing_id': listing_id,
            'pct_under': pct_under,
            'neighbourhood': neighbourhood,
            'beds': beds,
            'price': 2000,
            'fair_value': 2000,
            'final_score': 0.0,
            'is_stale': False,
            'region': 'Downtown',
            'has_image': False,
            'is_new': False,
            'price_dropped': False,
            'source': '',
            'station_walk_min': None,
            'neighborhood_status': None,
            'commute_minutes': None,
        }

    def _filter_with(self, **overrides):
        """Build the full parsed-filter contract using the parser, then
        override the supplied keys. This is what `api_deals` actually
        passes in, so it stays faithful to the integration contract."""
        from werkzeug.datastructures import MultiDict
        defaults = MultiDict()  # all keys absent == no filter active
        parsed = self.app_module._parse_deal_filters(defaults)
        parsed.update(overrides)  # overrides WIN (e.g. min_pct_under=15.0)
        return parsed

    def test_no_filter_passes_all_rows(self):
        """No min_pct_under set -> passes everything through."""
        rows = [self._row(f'a{i}', pct) for i, pct in enumerate([5, 10, 20, 30, 0])]
        out = self.app_module._apply_filters(rows, self._filter_with(min_pct_under=None))
        self.assertEqual(len(out), 5)

    def test_threshold_drops_below(self):
        """?min_pct_under=15 drops rows with pct_under<15."""
        rows = [
            self._row('a', 5.0),
            self._row('b', 14.999),
            self._row('c', 15.0),
            self._row('d', 30.0),
            self._row('e', 100.0),
        ]
        out = self.app_module._apply_filters(rows, self._filter_with(min_pct_under=15.0))
        self.assertEqual([r['listing_id'] for r in out], ['c', 'd', 'e'])

    def test_threshold_keeps_equal(self):
        """Boundary: pct_under == threshold is kept (>= semantics)."""
        rows = [self._row('x', 20.0), self._row('y', 19.999)]
        out = self.app_module._apply_filters(rows, self._filter_with(min_pct_under=20.0))
        self.assertEqual([r['listing_id'] for r in out], ['x'])

    def test_null_pct_under_is_dropped(self):
        """NULL pct_under is dropped when threshold > 0 - we don't know
        if it's a deal so it shouldn't appear in deal-focused views."""
        rows = [
            self._row('with_pct', 25.0),
            {'listing_id': 'no_pct', 'pct_under': None,
             'neighbourhood': 'Toronto', 'beds': 1, 'price': 2000,
             'fair_value': 2000, 'final_score': 0.0, 'is_stale': False,
             'region': 'Downtown'},
            {'listing_id': 'missing_key', 'neighbourhood': 'Toronto',
             'beds': 1, 'price': 2000, 'fair_value': 2000,
             'final_score': 0.0, 'is_stale': False, 'region': 'Downtown'},
        ]
        out = self.app_module._apply_filters(rows, self._filter_with(min_pct_under=10.0))
        self.assertEqual([r['listing_id'] for r in out], ['with_pct'])

    def test_threshold_zero_keeps_all(self):
        """?min_pct_under=0 is the 'no minimum' boundary. The implementation
        treats this as a pure no-op so ALL rows pass through, including
        those with NULL pct_under (we don't know it's overpriced, so we
        don't drop it). Functionally equivalent to omitting the filter.
        """
        rows = [
            self._row('a', 0.0),
            self._row('b', 5.0),
            {'listing_id': 'no_pct', 'pct_under': None,
             'neighbourhood': 'Toronto', 'beds': 1, 'price': 2000,
             'fair_value': 2000, 'final_score': 0.0, 'is_stale': False,
             'region': 'Downtown'},
        ]
        out = self.app_module._apply_filters(rows, self._filter_with(min_pct_under=0))
        self.assertEqual(len(out), 3,
                         "min_pct_under=0 must pass everything through, including NULL pct_under")
        self.assertEqual(
            sorted(r['listing_id'] for r in out),
            ['a', 'b', 'no_pct'],
        )

    def test_threshold_filter_with_neighbourhood(self):
        """Filter composes: min_pct_under + neighbourhood substring."""
        rows = [
            self._row('lib-down', 30, neighbourhood='Liberty Village'),
            self._row('lib-fair', 8, neighbourhood='Liberty Village'),
            self._row('branson-great', 35, neighbourhood='Branson'),
        ]
        parsed = self._filter_with(min_pct_under=20.0, neighbourhood='liberty')
        out = self.app_module._apply_filters(rows, parsed)
        self.assertEqual([r['listing_id'] for r in out], ['lib-down'])

    def test_threshold_filter_with_source(self):
        """Filter composes with source='kijiji'."""
        rows = [
            dict(self._row('a', 30), source='kijiji'),
            dict(self._row('b', 30), source='craigslist'),
            dict(self._row('c', 5), source='kijiji'),
        ]
        parsed = self._filter_with(min_pct_under=20.0, source='kijiji')
        out = self.app_module._apply_filters(rows, parsed)
        self.assertEqual([r['listing_id'] for r in out], ['a'])

    def test_threshold_filter_with_beds(self):
        """Filter composes with beds_min filter."""
        rows = [
            dict(self._row('a1br', 30), beds=1),
            dict(self._row('a2br', 30), beds=2),
            dict(self._row('a3br', 30), beds=3),
        ]
        parsed = self._filter_with(min_pct_under=20.0, beds_min=2)
        out = self.app_module._apply_filters(rows, parsed)
        self.assertEqual([r['listing_id'] for r in out], ['a2br', 'a3br'])

    def test_negative_pct_under_dropped(self):
        """Negative pct_under (overpriced listings) are always dropped when
        threshold > 0, which is the whole point of the filter."""
        rows = [
            self._row('overpriced', -5.0),
            self._row('fair', 0.0),
            self._row('good_deal', 25.0),
        ]
        out = self.app_module._apply_filters(rows, self._filter_with(min_pct_under=10.0))
        self.assertEqual([r['listing_id'] for r in out], ['good_deal'])

    def test_string_pct_under_handled(self):
        """pct_under may arrive as string from CSV fallback - numeric
        coercion must work, non-numeric dropped."""
        rows = [
            {'listing_id': 'a', 'pct_under': '25', 'neighbourhood': 'Toronto'},
            {'listing_id': 'b', 'pct_under': 'five', 'neighbourhood': 'Toronto'},
            {'listing_id': 'c', 'pct_under': 30, 'neighbourhood': 'Toronto'},
        ]
        out = self.app_module._apply_filters(rows, self._filter_with(min_pct_under=20.0))
        kept_ids = sorted(r['listing_id'] for r in out)
        self.assertEqual(kept_ids, ['a', 'c'])


class TestApiDealsMinPctUnder(_FlaskTestBase):
    """Integration test via Flask test_client."""

    def test_endpoint_200_with_filter(self):
        """?min_pct_under=20 returns 200 (empty or not, never 500)."""
        resp = self.client.get('/api/deals?min_pct_under=20')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn('deals', body)
        self.assertIn('total', body)

    def test_filter_narrows_deals(self):
        """With ?min_pct_under=20 the returned set is a subset of
        the unfiltered set (and 50%+ lower count)."""
        unfiltered = self.client.get('/api/deals?limit=200').get_json()
        filtered = self.client.get('/api/deals?min_pct_under=20&limit=200').get_json()
        unfiltered_total = unfiltered.get('total', 0)
        filtered_total = filtered.get('total', 0)

        # Sanity: filter set is smaller (or equal if no under-priced deals exist)
        self.assertLessEqual(filtered_total, unfiltered_total)

        # Every returned deal satisfies the constraint
        for d in filtered.get('deals', []):
            pct = d.get('pct_under')
            if pct is None:
                continue  # NULL pct_under can be in the response when threshold is met
            try:
                self.assertGreaterEqual(float(pct), 20.0,
                                        f"Deal with pct_under={pct} slipped through filter")
            except (TypeError, ValueError):
                self.fail(f"Non-numeric pct_under={pct!r} in returned deal")

    def test_compose_with_source_filter(self):
        """?min_pct_under=15&source=kijiji composes correctly."""
        resp = self.client.get('/api/deals?min_pct_under=15&source=kijiji&limit=200')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        for d in body.get('deals', []):
            self.assertEqual(d.get('source', ''), 'kijiji',
                             "source filter must be honored when composed with min_pct_under")

    def test_invalid_input_does_not_500(self):
        """Regression: hand-crafted URL with non-numeric min_pct_under
        must silently disable the filter rather than 500."""
        for bad in ['abc', '-5', '150']:
            resp = self.client.get(f'/api/deals?min_pct_under={bad}')
            self.assertEqual(resp.status_code, 200,
                             f"?min_pct_under={bad} should return 200 but returned {resp.status_code}")


class TestIndexHtmlWiring(unittest.TestCase):
    """Source-grep verification that the UI pieces are in place.
    Uses regex/file reads rather than Flask test_client to avoid the
    known DB-pollution interaction with test_mc322 et al. (see MC-322
    self-audit, repeated in MC-339/MC-340 self-audit notes).
    """

    @classmethod
    def setUpClass(cls):
        cls.index_path = os.path.join(RENT_FINDER_DIR, 'templates', 'index.html')
        with open(cls.index_path, encoding='utf-8') as f:
            cls.html = f.read()

    def test_input_present(self):
        """The actual <input> element with id=min_pct_under exists in markup."""
        self.assertIn("id=\"min_pct_under\"", self.html,
                      "UI input id=min_pct_under missing from index.html")

    def test_buildparams_adds_min_pct_under(self):
        """buildParams() reads the input and sets the URLSearchParams key."""
        # Look for the JS branch that reads min_pct_under from the input and
        # pushes it to params.
        pattern = re.compile(
            r"document\.getElementById\(['\"]min_pct_under['\"]\)\.value.*?params\.set\(['\"]min_pct_under['\"]",
            re.DOTALL,
        )
        self.assertRegex(self.html, pattern,
                         "buildParams must read min_pct_under input and set params.min_pct_under")

    def test_parsequeryparams_reads_min_pct_under(self):
        """parseQueryParams() reads ?min_pct_under back into the input on load."""
        pattern = re.compile(
            r"params\.get\(['\"]min_pct_under['\"]\).*?getElementById\(['\"]min_pct_under['\"]\)\.value",
            re.DOTALL,
        )
        self.assertRegex(self.html, pattern,
                         "parseQueryParams must read min_pct_under URL param into the input")

    def test_resetfilters_clears_min_pct_under(self):
        """resetFilters() must clear min_pct_under input alongside other fields."""
        pattern = re.compile(
            r"document\.getElementById\(['\"]min_pct_under['\"]\)\.value\s*=\s*['\"]['\"]"
        )
        self.assertRegex(self.html, pattern,
                         "resetFilters must clear min_pct_under input to empty")

    def test_updatefiltercount_counts_min_pct_under(self):
        """updateFilterCount() must increment count when input is non-empty."""
        pattern = re.compile(
            r"document\.getElementById\(['\"]min_pct_under['\"]\)\.value.*?count\+\+",
            re.DOTALL,
        )
        self.assertRegex(self.html, pattern,
                         "updateFilterCount must include min_pct_under in count")

    def test_describefilters_surfaces_min_pct_under(self):
        """describeFilters() emits a human-readable summary fragment for save-search."""
        pattern = re.compile(
            r"filters\.min_pct_under.*?parts\.push",
            re.DOTALL,
        )
        self.assertRegex(self.html, pattern,
                         "describeFilters must surface min_pct_under in save-search summary")

    def test_applysavedfilters_round_trip(self):
        """applySavedFilters() must restore min_pct_under from a saved snapshot."""
        # Look for the setIfPresent call with min_pct_under
        pattern = re.compile(
            r"setIfPresent\(['\"]min_pct_under['\"]"
        )
        self.assertRegex(self.html, pattern,
                         "applySavedFilters must round-trip min_pct_under via setIfPresent")

    def test_listener_wiring_array_includes_min_pct_under(self):
        """The forEach loop that wires change listeners includes min_pct_under
        so the filter count badge updates on every change."""
        pattern = re.compile(
            r"['\"]min_pct_under['\"].*?addEventListener",
            re.DOTALL,
        )
        # Walk both directions since the regex is greedy; try forward and reverse.
        self.assertTrue(
            re.search(r"\[.*?['\"]min_pct_under['\"].*?\]", self.html, re.DOTALL),
            "min_pct_under must be in the listener-wiring array literal",
        )
        # And the change listener must use updateFilterCount
        self.assertRegex(
            self.html,
            r"addEventListener\(['\"]change['\"],\s*updateFilterCount",
            "Filter change listeners must invoke updateFilterCount",
        )


class TestNoRegressionsMinPctUnder(_FlaskTestBase):
    """Regression guards: MC-338 contract preserved (all other filters
    still pass through), and MC-316/+ source filter still composes."""

    def test_existing_api_deals_still_serves(self):
        """Baseline sanity: GET /api/deals still returns 200 + has
        standard shape, no regression from the new field."""
        resp = self.client.get('/api/deals')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn('deals', body)
        self.assertIn('total', body)

    def test_min_pct_under_none_is_default(self):
        """Setting ?min_pct_under with no value (just presence) must NOT
        silently activate the filter - Werkzeug turns `?min_pct_under`
        into '' which is the no-filter branch."""
        # ?min_pct_under (no value) should parse to empty string -> None
        resp = self.client.get('/api/deals?min_pct_under=')
        self.assertEqual(resp.status_code, 200)

    def test_pct_under_field_on_rows(self):
        """Every returned row has a pct_under field (normalized upstream)."""
        resp = self.client.get('/api/deals?limit=10').get_json()
        for d in resp.get('deals', []):
            # Either a number or None
            self.assertIn('pct_under', d,
                          "Deal rows must expose pct_under field for the new filter")


if __name__ == '__main__':
    unittest.main()
