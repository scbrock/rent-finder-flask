"""MC-353: HTML wiring + Node wrapper tests for the recent_searches module.

Source-grep / regex tests against templates/index.html + static JS to confirm
the new HTML/CSS/JS pieces landed correctly, plus Node wrapper tests that
shell out to test_mc353_recent_searches.js and assert the summary line.
"""

import os
import re
import subprocess
from pathlib import Path

RENT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = RENT_DIR / 'templates' / 'index.html'
JS_PATH = RENT_DIR / 'static' / 'recent_searches.js'
NODE_TEST = RENT_DIR / 'tests' / 'test_mc353_recent_searches.js'


# =====================================================================
# TestStaticAssetPresent
# =====================================================================
class TestStaticAssetPresent:
    def test_recent_searches_js_exists(self):
        assert JS_PATH.is_file(), 'recent_searches.js must exist'

    def test_module_exports_createView(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'createView' in src
        assert 'module.exports = factory()' in src

    def test_module_registers_window_global(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'root.__recentSearches = factory()' in src

    def test_uses_iife_wrapper(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'function (root, factory)' in src
        assert src.rstrip().endswith('}));')

    def test_storage_key_constant(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert "DEFAULT_STORAGE_KEY = 'rf_recent_searches'" in src

    def test_max_entries_is_five(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'DEFAULT_MAX_ENTRIES = 5' in src

    def test_module_exposes_required_api(self):
        src = JS_PATH.read_text(encoding='utf-8')
        for fn in ('saveCurrent', 'saveCurrentDebounced', 'getAll', 'getRecent',
                   'count', 'removeAt', 'clearAll', 'buildLabel',
                   'serializeFilters', 'renderEntry', 'attachPopover',
                   'closePopover', 'togglePopover', 'listenStorage',
                   'restoreFromObject', 'onRestore', 'refresh'):
            assert fn in src, f'Module must export {fn}'

    def test_storage_round_trip_keys_constant(self):
        # All filter keys the module round-trips in dedup/serialize are
        # listed explicitly so test ordering stays stable across builds.
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'ROUND_TRIP_KEYS' in src
        for key in ('beds_min', 'baths_min', 'price_min', 'price_max',
                    'neighbourhood', 'region', 'source', 'sort',
                    'max_subway', 'max_commute', 'hide_stale',
                    'is_new', 'price_dropped', 'has_image', 'has_parking'):
            assert f"'{key}'" in src, f'ROUND_TRIP_KEYS must include {key}'

    def test_module_uses_storage_event_for_cross_tab_sync(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'addEventListener' in src
        assert "'storage'" in src
        assert 'ev.key !== storageKey' in src

    def test_module_handles_no_window(self):
        # Defensive: factory accepts opts.window / opts.document / opts.storage
        # for test injection so the module runs in Node tests without a DOM.
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'opts.window' in src or 'opts.storage' in src


# =====================================================================
# TestIndexHtmlWiring - pill button + popover container + script tag + init
# =====================================================================
class TestIndexHtmlWiring:
    def setup_method(self):
        self.src = TEMPLATE_PATH.read_text(encoding='utf-8')

    def test_pill_button_present(self):
        assert 'id="recent_searches_btn"' in self.src

    def test_count_badge_present(self):
        assert 'id="recent_searches_count"' in self.src

    def test_pill_label_text(self):
        # Default text says "Recent searches (0)" — the (N) is replaced
        # at runtime by saveCurrent/refresh.
        assert 'Recent searches (<span id="recent_searches_count">0</span>)' in self.src

    def test_pill_caret_glyph(self):
        # The ▾ caret signals a dropdown (matches MC-353 AC).
        assert '▾' in self.src.split('id="recent_searches_btn"', 1)[1].split('</button>', 1)[0]

    def test_popover_container_present(self):
        assert 'id="recent_searches_popover"' in self.src
        assert 'data-state="closed"' in self.src.split('id="recent_searches_popover"', 1)[1].split('</div>', 1)[0]
        assert 'display:none' in self.src.split('id="recent_searches_popover"', 1)[1].split('</div>', 1)[0]

    def test_pill_sits_near_other_filter_pills(self):
        # The pill should sit somewhere in the filter bar — between Hide viewed
        # and Reset viewed, OR between Reset viewed and the Filter/Reset buttons.
        btn_idx = self.src.index('id="recent_searches_btn"')
        hide_idx = self.src.index('id="hide_viewed"')
        filter_apply_idx = self.src.index('id="filter_apply"')
        # In the same filter-bar block (within 3000 chars of hide_viewed)
        assert abs(btn_idx - hide_idx) < 3000, 'pill should sit in the filter bar'
        assert btn_idx < filter_apply_idx, 'pill should appear before the Filter/Reset buttons'

    def test_script_tag_loaded(self):
        assert "static/recent_searches.js" in self.src

    def test_init_runs_createView(self):
        # The init wiring block must call window.__recentSearches.createView().
        assert 'window.__recentSearches.createView()' in self.src

    def test_init_uses_attachPopover(self):
        assert 'rs.attachPopover(btn, pop)' in self.src

    def test_init_registers_storage_sync(self):
        assert 'rs.listenStorage' in self.src

    def test_init_calls_onRestore_with_apply_saved_filters(self):
        # AC4: clicking an entry restores filters via parseQueryParams +
        # dispatches change events. We use applySavedFilters (already wired
        # by MC-322) so no new round-trip helper is needed.
        assert 'rs.onRestore' in self.src
        assert 'applySavedFilters(filters)' in self.src

    def test_loadDeals_saves_active_filter_set(self):
        # AC5: active filter combo auto-saved on every successful loadDeals().
        # Sits inside the existing try/catch wrapper next to MC-351's hook.
        load_block = self.src.split('async function loadDeals', 1)[1].split('function loadMoreDeals', 1)[0]
        assert 'saveCurrentDebounced' in load_block, 'loadDeals must call saveCurrentDebounced'
        assert 'rf_recent_searches' in self.src or '__recentSearchesView' in load_block
        # Uses buildParams() so the saved filters are exactly the URL params.
        assert 'buildParams' in load_block

    def test_count_badge_updated_after_save(self):
        # The hook must update the pill count badge immediately so users see
        # the count move without waiting for the debounce to settle.
        load_block = self.src.split('async function loadDeals', 1)[1].split('function loadMoreDeals', 1)[0]
        assert "recent_searches_count" in load_block
        assert 'rsBtn.disabled = false' in load_block

    def test_apply_saved_filters_helper_exposed(self):
        # The init wiring uses window.applySavedFilters (defined in index.html
        # at the MC-322 hook). Make sure it's still present.
        assert 'function applySavedFilters(' in self.src


# =====================================================================
# TestCssStyling - popover CSS exists + matches brand palette
# =====================================================================
class TestCssStyling:
    def setup_method(self):
        self.src = TEMPLATE_PATH.read_text(encoding='utf-8')

    def test_popover_css_block_present(self):
        assert '#recent_searches_popover' in self.src

    def test_close_button_styled(self):
        block = self.src.split('#recent_searches_popover', 1)[1]
        assert '.rs-close' in block

    def test_entry_hover_state(self):
        block = self.src.split('#recent_searches_popover', 1)[1]
        assert '.rs-entry:hover' in block

    def test_label_color_matches_brand_green(self):
        block = self.src.split('#recent_searches_popover', 1)[1]
        assert '#1e5b3a' in block, 'rs-label color matches MC-335 brand green'

    def test_delete_button_styled(self):
        block = self.src.split('#recent_searches_popover', 1)[1]
        assert '.rs-delete' in block
        # Hover turns the × red to signal destructive action.
        assert '.rs-delete:hover' in block
        assert '#c1452d' in block

    def test_clear_btn_styled(self):
        block = self.src.split('#recent_searches_popover', 1)[1]
        assert '.rs-clear-btn' in block
        assert 'Clear all' in self.src

    def test_empty_state_styled(self):
        block = self.src.split('#recent_searches_popover', 1)[1]
        assert '.rs-empty' in block
        assert 'font-style: italic' in block

    def test_footer_styled(self):
        block = self.src.split('#recent_searches_popover', 1)[1]
        assert '.rs-footer' in block


# =====================================================================
# TestRegressionGuard - coexisting modules still intact
# =====================================================================
class TestRegressionGuard:
    def setup_method(self):
        self.src = TEMPLATE_PATH.read_text(encoding='utf-8')

    def test_mc350_listing_viewed_script_loaded(self):
        assert "listing_viewed.js" in self.src

    def test_mc351_recently_viewed_script_loaded(self):
        assert "recently_viewed.js" in self.src

    def test_mc351_recently_viewed_init_intact(self):
        assert '__recentlyViewedView' in self.src

    def test_mc322_save_search_button_still_present(self):
        # Save filters button (MC-322) must coexist with the new MC-353
        # dropdown — they're complementary (named-saved vs anonymous-history).
        assert 'id="save_search_btn"' in self.src
        assert 'openSaveSearchModal' in self.src

    def test_mc323_only_new_filter_still_present(self):
        # MC-353 round-trips the only_new key, so the only_new toggle must
        # still be present in the filter bar.
        assert 'id="only_new"' in self.src
        assert 'id="only_new_toggle"' in self.src

    def test_mc349_map_viewport_filter_still_loaded(self):
        assert "map_viewport_filter.js" in self.src
        assert '__mapViewportFilter' in self.src

    def test_build_params_includes_is_new(self):
        # Required for MC-353's serializeFilters to round-trip is_new.
        assert "is_new" in self.src.split('function buildParams', 1)[1].split('return params', 1)[0]

    def test_build_params_includes_price_dropped(self):
        assert "price_dropped" in self.src.split('function buildParams', 1)[1].split('return params', 1)[0]

    def test_build_params_includes_has_image(self):
        assert "has_image" in self.src.split('function buildParams', 1)[1].split('return params', 1)[0]

    def test_build_params_includes_hide_stale(self):
        assert "hide_stale" in self.src.split('function buildParams', 1)[1].split('return params', 1)[0]

    def test_build_params_includes_max_price_per_sqft(self):
        assert "price_per_sqft_max" in self.src.split('function buildParams', 1)[1].split('return params', 1)[0]

    def test_build_params_includes_min_pct_under(self):
        assert "min_pct_under" in self.src.split('function buildParams', 1)[1].split('return params', 1)[0]


# =====================================================================
# TestJsApiSurface - module exports + IIFE shape
# =====================================================================
class TestJsApiSurface:
    def test_module_uses_iife_pattern(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert "function (root, factory)" in src
        assert "module.exports = factory()" in src
        assert "root.__recentSearches = factory()" in src

    def test_module_registers_window_global(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert '__recentSearches' in src

    def test_module_default_debounce_is_1000ms(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'DEFAULT_DEBOUNCE_MS = 1000' in src

    def test_module_max_entries_is_5(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'DEFAULT_MAX_ENTRIES = 5' in src

    def test_module_handles_empty_filter_set(self):
        src = JS_PATH.read_text(encoding='utf-8')
        # AC5: skip writes when filter set is empty (so a default page load
        # doesn't spam "All deals" into the history every refresh).
        assert 'Object.keys(entry.filters).length === 0' in src

    def test_module_dedupes_via_serialize(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'serializeFilters' in src
        assert 'sig' in src  # dedup key short name

    def test_module_emits_cap_at_max(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'state.length > maxEntries' in src

    def test_module_escape_html_helper(self):
        # XSS guard: every user-derivable string in renderEntry goes through _escHtml.
        src = JS_PATH.read_text(encoding='utf-8')
        assert '_escHtml(label)' in src


# =====================================================================
# TestNodeWrapper - shell out to test_mc353_recent_searches.js
# =====================================================================
class TestNodeWrapper:
    def test_node_tests_pass(self):
        # Run the JS test file and assert exit code 0 + the summary line.
        result = subprocess.run(
            ['node', str(NODE_TEST)],
            capture_output=True, text=True, cwd=str(RENT_DIR / 'tests'),
        )
        assert result.returncode == 0, (
            f'Node tests failed:\nstdout: {result.stdout}\nstderr: {result.stderr}'
        )
        assert 'Failed: 0' in result.stdout, (
            f'Expected zero failures:\nstdout: {result.stdout}\nstderr: {result.stderr}'
        )

    def test_node_tests_at_least_25(self):
        # AC9 requires ≥15 Node tests. We have 30 to give us margin against
        # future edge-case additions.
        result = subprocess.run(
            ['node', str(NODE_TEST)],
            capture_output=True, text=True, cwd=str(RENT_DIR / 'tests'),
        )
        assert result.returncode == 0, 'Node tests must exit cleanly'
        m = re.search(r'Passed:\s*(\d+)\s*/\s*Failed:\s*(\d+)\s*/\s*Total:\s*(\d+)', result.stdout)
        assert m, f'Could not parse summary: {result.stdout}'
        passed = int(m.group(1))
        failed = int(m.group(2))
        total = int(m.group(3))
        assert failed == 0
        assert passed == total
        assert passed >= 25, f'Expected ≥25 tests, got {passed}'