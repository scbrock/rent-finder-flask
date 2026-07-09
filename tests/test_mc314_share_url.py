"""MC-314: Python integration tests for shareable compare URL + Clear All button.

Validates:
- Flask renders the new compare buttons (clear_all_btn, cmp_share_btn)
- Static compare.js file has all new API functions exposed
- index.html markup contains the wiring for both new buttons
- All 38 Node tests pass
"""

import os
import re
import subprocess

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(THIS_DIR)
STATIC_JS = os.path.join(PROJECT_DIR, "static", "compare.js")
INDEX_HTML = os.path.join(PROJECT_DIR, "templates", "index.html")
TEST_JS = os.path.join(THIS_DIR, "test_mc314_share_url.js")


# ── Static asset checks ───────────────────────────────────────────────────

def test_static_compare_js_has_mc314_api():
    """compare.js must declare all MC-314 functions in module.exports + IIFE closure."""
    with open(STATIC_JS, encoding="utf-8") as f:
        src = f.read()
    funcs = [
        "parseSelectionString",
        "encodeSelection",
        "parseURLSelection",
        "restoreFromURL",
        "clearURLParam",
        "buildShareURL",
        "copyShareLink",
        "fallbackCopy",
        "flashCopyButton",
        "updateClearAllButton",
    ]
    for fn in funcs:
        assert fn in src, f"compare.js must define {fn}"


def test_static_compare_js_storage_key_unchanged():
    """Storage key rf_selected_ids must remain unchanged for backwards compat with MC-313."""
    with open(STATIC_JS, encoding="utf-8") as f:
        src = f.read()
    assert "rf_selected_ids" in src


def test_static_compare_js_comments_call_out_mc314():
    """Source must include MC-314 banner so future readers know what changed."""
    with open(STATIC_JS, encoding="utf-8") as f:
        src = f.read()
    # Top-of-file comment header
    assert "MC-313" in src and "MC-314" in src


# ── index.html wiring checks ──────────────────────────────────────────────

def test_index_html_has_clear_all_btn_in_filter_bar():
    """Filter bar must include the new clear_all_btn next to compare_btn."""
    with open(INDEX_HTML, encoding="utf-8") as f:
        src = f.read()
    assert 'id="clear_all_btn"' in src, 'expected id="clear_all_btn" in template'
    assert 'id="clear_all_btn_label"' in src, 'expected label span id'
    # The clear_all_btn should appear in the filter bar (not inside the modal)
    # Filter bar buttons come after id="filter_apply".
    apply_idx = src.find('id="filter_apply"')
    clr_idx = src.find('id="clear_all_btn"')
    cmpmdl_idx = src.find('id="compare_modal"')
    assert apply_idx > 0 and clr_idx > 0 and cmpmdl_idx > 0
    assert apply_idx < clr_idx < cmpmdl_idx, (
        "clear_all_btn must be in the filter bar (between filter_apply and compare_modal)"
    )


def test_index_html_clear_all_btn_handler_calls_clearcompare():
    """Inline onclick of clear_all_btn must invoke window.__compare.clearCompare."""
    with open(INDEX_HTML, encoding="utf-8") as f:
        src = f.read()
    idx = src.find('id="clear_all_btn"')
    assert idx > 0
    ctx = src[idx:idx + 600]
    assert "clearCompare" in ctx, "clear_all_btn onclick must call clearCompare"
    assert "syncRowCheckboxes" in ctx, "clear_all_btn onclick must call syncRowCheckboxes"
    assert "updateCompareBadge" in ctx, "clear_all_btn onclick must call updateCompareBadge"


def test_index_html_cmp_share_btn_inside_compare_modal():
    """Copy Link button must live inside the compare modal."""
    with open(INDEX_HTML, encoding="utf-8") as f:
        src = f.read()
    assert 'id="cmp_share_btn"' in src, 'expected id="cmp_share_btn" in template'
    cmpmdl_idx = src.find('id="compare_modal"')
    cmp_end_idx = src.find('</div>\n    </div>', cmpmdl_idx)
    assert cmpmdl_idx > 0
    share_idx = src.find('id="cmp_share_btn"')
    # Must be after the modal opens and before the modal closes
    assert cmpmdl_idx < share_idx, "cmp_share_btn must be inside compare_modal"
    assert share_idx < cmp_end_idx + 50, "cmp_share_btn must be inside compare_modal"


def test_index_html_cmp_share_btn_handler_copysharelink():
    """Copy Link button onclick must call copyShareLink."""
    with open(INDEX_HTML, encoding="utf-8") as f:
        src = f.read()
    idx = src.find('id="cmp_share_btn"')
    assert idx > 0
    ctx = src[idx:idx + 500]
    assert "copyShareLink" in ctx, "cmp_share_btn onclick must call copyShareLink"
    assert "Copy Link" in ctx, "default label is 'Copy Link'"


def test_index_html_init_calls_compare_init():
    """The init script must call window.__compare.init() so URL restore runs."""
    with open(INDEX_HTML, encoding="utf-8") as f:
        src = f.read()
    assert "window.__compare.init()" in src, "init() must be called on page load"


# ── Flask live render check ───────────────────────────────────────────────

def _get_app_module():
    """Import app.py and return the Flask app object."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "rent_finder_app", os.path.join(PROJECT_DIR, "app.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.app


def test_flask_home_renders_compare_buttons():
    """Hit / and confirm both new buttons are present in the rendered HTML."""
    app = _get_app_module()
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'id="compare_btn"' in body, "compare_btn must still be rendered"
    assert 'id="clear_all_btn"' in body, "clear_all_btn must be rendered in filter bar"
    assert 'id="cmp_share_btn"' in body, "cmp_share_btn must be rendered in modal"


def test_flask_static_compare_js_loads():
    """The compare.js static asset must serve and contain MC-314 functions."""
    app = _get_app_module()
    client = app.test_client()
    r = client.get("/static/compare.js")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    for fn in [
        "parseSelectionString", "parseURLSelection", "restoreFromURL",
        "clearURLParam", "buildShareURL", "copyShareLink",
        "updateClearAllButton",
    ]:
        assert fn in body, f"compare.js must contain {fn}"


def test_flask_api_compare_rejects_invalid_ids_in_url_equivalents():
    """Sanity: /api/compare still validates ids, complement to client-side URL restore."""
    app = _get_app_module()
    client = app.test_client()
    # No ids
    assert client.get("/api/compare").status_code == 400
    # Too many ids
    assert client.get("/api/compare?ids=a,b,c,d").status_code == 400
    # Single id
    assert client.get("/api/compare?ids=only").status_code == 400


# ── Run Node tests via subprocess ─────────────────────────────────────────

def test_node_mc314_share_url_runs_clean():
    result = subprocess.run(
        ["node", TEST_JS],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "passed, 0 failed" in result.stdout, (
        f"Expected 0 failures. Stdout:\n{result.stdout}\nStderr:\n{result.stderr}"
    )
    assert result.returncode == 0, f"Exit code {result.returncode}: {result.stderr}"


def test_node_mc314_url_parsing():
    result = subprocess.run(
        ["node", TEST_JS], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    out = result.stdout
    for marker in [
        "parseSelectionString:",
        "parseURLSelection:",
        "restoreFromURL:",
        "URL takes precedence over localStorage",
    ]:
        assert marker in out, f"missing test marker: {marker}"


def test_node_mc314_share_button():
    result = subprocess.run(
        ["node", TEST_JS], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    out = result.stdout
    assert "buildShareURL:" in out
    assert "copyShareLink:" in out
    assert "flashCopyButton:" in out


def test_node_mc314_clear_all_button():
    result = subprocess.run(
        ["node", TEST_JS], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    out = result.stdout
    assert "updateClearAllButton:" in out
    assert "shows button when 1+ selected" in out
    assert "hides button when 0 selected" in out


def test_node_mc314_init_fallback():
    result = subprocess.run(
        ["node", TEST_JS], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    out = result.stdout
    for marker in [
        "init: URL with 2 valid ids restores selection from URL",
        "init: silently falls back to localStorage when URL invalid",
        "init: silently falls back to localStorage when no cmp param",
        "init: silently falls back when URL present but malformed",
    ]:
        assert marker in out, f"missing init test: {marker}"


def test_node_mc314_index_wiring():
    result = subprocess.run(
        ["node", TEST_JS], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    out = result.stdout
    for marker in [
        "index.html: contains clear_all_btn filter-bar element",
        "index.html: clear_all_btn wires to clearCompare",
        "index.html: contains cmp_share_btn inside compare modal",
        "compare.js: exports all MC-314 functions",
    ]:
        assert marker in out, f"missing wiring test: {marker}"
