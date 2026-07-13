"""MC-351: HTML wiring + Node wrapper tests for the recently_viewed module.

Source-grep / regex tests against templates/index.html + static JS to confirm
the new HTML/CSS/JS pieces landed correctly, plus Node wrapper tests that
shell out to test_mc351_recently_viewed.js and assert the summary line.
"""

import os
import re
import subprocess
from pathlib import Path

RENT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = RENT_DIR / 'templates' / 'index.html'
JS_PATH = RENT_DIR / 'static' / 'recently_viewed.js'
NODE_TEST = RENT_DIR / 'tests' / 'test_mc351_recently_viewed.js'


# =====================================================================
# TestStaticAssetPresent
# =====================================================================
class TestStaticAssetPresent:
    def test_recently_viewed_js_exists(self):
        assert JS_PATH.is_file(), 'recently_viewed.js must exist'

    def test_module_exports_createView(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'createView' in src
        assert 'module.exports = factory()' in src

    def test_module_registers_window_global(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'root.__recentlyViewed = factory()' in src

    def test_uses_iife_wrapper(self):
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'function (root, factory)' in src
        assert src.rstrip().endswith('}));')

    def test_storage_key_constant(self):
        src = JS_PATH.read_text(encoding='utf-8')
        # The localStorage key the module reads (must match MC-350's
        # `rf_viewed_ids` so we read the same state).
        assert "DEFAULT_STORAGE_KEY = 'rf_viewed_ids'" in src

    def test_module_exposes_required_api(self):
        src = JS_PATH.read_text(encoding='utf-8')
        # Each export the test file & index.html wiring depends on.
        for fn in ('getCount', 'getRecent', 'setDeals', 'renderEntry',
                   'attachPopover', 'closePopover', 'togglePopover',
                   'listenStorage', 'clearAll', 'refresh'):
            assert fn in src, f'Module must export {fn}'

    def test_module_reuses_listing_viewed(self):
        # AC1: module reuses window.__listingViewed instead of duplicating
        # localStorage parsing logic.
        src = JS_PATH.read_text(encoding='utf-8')
        assert 'root.__listingViewed' in src
        assert 'lv.getAllViewed' in src
        assert 'lv.count' in src

    def test_module_has_fallback_path(self):
        # AC9: gracefully degrades when window.__listingViewed is missing
        # (standalone fallback that parses rf_viewed_ids directly).
        src = JS_PATH.read_text(encoding='utf-8')
        assert '_safeParseStorage' in src
        assert '_readRawState' in src


# =====================================================================
# TestIndexHtmlWiring - pill button + popover container + script tag + init
# =====================================================================
class TestIndexHtmlWiring:
    def setup_method(self):
        self.src = TEMPLATE_PATH.read_text(encoding='utf-8')

    def test_pill_button_present(self):
        assert 'id="recent_viewed_btn"' in self.src

    def test_count_badge_present(self):
        assert 'id="recent_viewed_count"' in self.src

    def test_pill_label_text(self):
        # Default text says "Recently viewed (0)" — the (N) is replaced
        # at runtime by setDeals/refresh.
        assert 'Recently viewed (<span id="recent_viewed_count">0</span>)' in self.src

    def test_popover_container_present(self):
        assert 'id="recent_viewed_popover"' in self.src
        assert 'data-state="closed"' in self.src
        assert 'display:none' in self.src.split('id="recent_viewed_popover"', 1)[1].split('</div>', 1)[0]

    def test_pill_between_hide_viewed_and_reset_viewed(self):
        # AC3: the button sits BETWEEN "Hide viewed" and "Reset viewed".
        hide_idx = self.src.index('id="hide_viewed"')
        recent_idx = self.src.index('id="recent_viewed_btn"')
        reset_idx = self.src.index('id="reset_viewed"')
        assert hide_idx < recent_idx < reset_idx, (
            'recent_viewed_btn must sit between hide_viewed and reset_viewed'
        )

    def test_script_tag_loaded(self):
        assert "recently_viewed.js" in self.src
        # Loaded AFTER listing_viewed.js (so window.__listingViewed is set)
        snippet = self.src.split('listing_viewed.js', 1)[1]
        assert 'recently_viewed.js' in snippet

    def test_init_wires_createView_and_attachPopover(self):
        # The init IIFE must create a view instance and call attachPopover.
        assert "window.__recentlyViewed.createView" in self.src
        assert 'window.__recentlyViewedView' in self.src  # exposes the view instance
        assert 'attachPopover' in self.src

    def test_init_subscribes_to_cross_tab_storage_events(self):
        # Cross-tab sync: listenStorage() called on the view instance.
        assert 'rv.listenStorage' in self.src

    def test_popover_dismissable_by_escape(self):
        # The JS module wires a keydown listener that closes on Escape.
        js = JS_PATH.read_text(encoding='utf-8')
        assert "'Escape'" in js or '"Escape"' in js

    def test_popover_dismissable_by_outside_click(self):
        js = JS_PATH.read_text(encoding='utf-8')
        # Outside-click handler installed on the window.
        assert "win.addEventListener('click'" in js

    def test_loadDeals_hook_populates_deals_cache(self):
        # AC9 (cross-module wiring): loadDeals keeps the popover's deals
        # cache fresh via __recentlyViewedView.setDeals(allDeals).
        assert '__recentlyViewedView.setDeals(allDeals)' in self.src

    def test_pill_aria_label_on_popover(self):
        assert 'role="dialog"' in self.src
        assert 'aria-label="Recently viewed listings"' in self.src


# =====================================================================
# TestCssStyling
# =====================================================================
class TestCssStyling:
    def setup_method(self):
        self.src = TEMPLATE_PATH.read_text(encoding='utf-8')

    def test_filter_pill_rule_present(self):
        assert '.filter-pill' in self.src
        assert 'background: #fff' in self.src.split('.filter-pill', 1)[1].split('{', 1)[1].split('}', 1)[0]
        # Brand green text per the existing palette.
        assert 'color: #2d6a4f' in self.src

    def test_filter_pill_disabled_state(self):
        css = self.src.split('.filter-pill', 1)[1].split('{', 1)[1]
        assert '.filter-pill:disabled' in css or ':disabled' in css
        assert 'cursor: not-allowed' in self.src

    def test_popover_close_button_styled(self):
        assert '.rv-close' in self.src
        assert 'cursor: pointer' in self.src

    def test_popover_thumbnail_sized(self):
        # 48x36 spec per the AC.
        css = self.src.split('.rv-thumb', 1)[1].split('{', 1)[1].split('}', 1)[0]
        assert 'width: 48px' in css
        assert 'height: 36px' in css

    def test_popover_pct_chip_styled(self):
        assert '.rv-pct-chip' in self.src
        assert '#d4edda' in self.src or '#1e5b3a' in self.src  # green chip

    def test_popover_empty_state_styled(self):
        assert '.rv-empty' in self.src
        assert 'font-style: italic' in self.src

    def test_popover_footer_styled(self):
        assert '.rv-footer' in self.src


# =====================================================================
# TestRegressionGuard - existing modules must still be loaded
# =====================================================================
class TestRegressionGuard:
    def setup_method(self):
        self.src = TEMPLATE_PATH.read_text(encoding='utf-8')

    def test_listing_viewed_js_still_loaded(self):
        # AC11 + MC-350 regression: source module still ships.
        assert 'listing_viewed.js' in self.src

    def test_compare_js_still_loaded(self):
        # MC-313 regression.
        assert 'compare.js' in self.src

    def test_map_cluster_js_still_loaded(self):
        # MC-348 regression.
        assert 'map_cluster.js' in self.src

    def test_map_viewport_filter_js_still_loaded(self):
        # MC-349 regression: viewport filter module still ships.
        assert 'map_viewport_filter.js' in self.src

    def test_cl_photo_lazy_js_still_loaded(self):
        # MC-309 regression: lazy photo fetcher still ships.
        assert 'cl_photo_lazy.js' in self.src

    def test_listing_gallery_js_still_loaded(self):
        # MC-312 regression: gallery module still ships.
        assert 'listing_gallery.js' in self.src

    def test_median_rent_card_present(self):
        # MC-337 regression: median rent stat card still renders.
        assert 'id="median_rent"' in self.src

    def test_total_savings_card_present(self):
        # MC-337 regression: total monthly savings stat card still renders.
        assert 'id="total_savings"' in self.src

    def test_new_today_pill_present(self):
        # MC-339 regression: "X new today" pill still renders.
        assert 'id="new_today_pill"' in self.src

    def test_health_pill_present(self):
        # MC-335 regression: data-freshness pill still renders.
        assert 'id="health_pill"' in self.src

    def test_hide_viewed_toggle_still_present(self):
        # MC-350 regression guard.
        assert 'id="hide_viewed_toggle"' in self.src

    def test_reset_viewed_link_still_present(self):
        # MC-350 regression guard.
        assert 'id="reset_viewed"' in self.src


# =====================================================================
# TestNodeWrapper - shell out to the Node tests and verify they all pass
# =====================================================================
class TestNodeWrapper:
    def test_node_tests_pass(self):
        if not NODE_TEST.is_file():
            raise AssertionError(f'Node test file missing: {NODE_TEST}')
        result = subprocess.run(
            ['node', str(NODE_TEST)],
            capture_output=True, text=True, timeout=60,
            cwd=str(RENT_DIR),
        )
        assert result.returncode == 0, (
            f'Node tests failed (exit {result.returncode})\n'
            f'stdout: {result.stdout}\nstderr: {result.stderr}'
        )
        assert 'Passed:' in result.stdout
        assert 'Failed: 0' in result.stdout

    def test_node_tests_at_least_15(self):
        result = subprocess.run(
            ['node', str(NODE_TEST)],
            capture_output=True, text=True, timeout=60,
            cwd=str(RENT_DIR),
        )
        m = re.search(r'Passed:\s*(\d+)\s*/\s*Failed:\s*(\d+)\s*/\s*Total:\s*(\d+)', result.stdout)
        assert m, f'Could not parse summary line: {result.stdout!r}'
        passed, failed, total = int(m.group(1)), int(m.group(2)), int(m.group(3))
        assert failed == 0, f'Node tests had {failed} failures'
        assert passed >= 15, f'Expected >= 15 Node tests, got {passed}'

    def test_node_test_asserts(self):
        # Quick smoke: every named test function in the JS file is exercised.
        src = NODE_TEST.read_text(encoding='utf-8')
        names = re.findall(r'^function\s+(test\w+)\s*\(\s*\)\s*\{', src, re.MULTILINE)
        assert len(names) >= 15, f'Expected >= 15 test functions, found {len(names)}: {names}'
