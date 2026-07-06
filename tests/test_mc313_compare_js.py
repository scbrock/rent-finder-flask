"""MC-313: Wrapper that shells out to Node to run tests/test_mc313_compare.js.

Used by `pytest tests/test_mc313_compare_js.py` so JS-side tests are part of
the suite without requiring a separate runner invocation.
"""
import os
import subprocess

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(THIS_DIR)
TEST_JS = os.path.join(THIS_DIR, "test_mc313_compare.js")


def test_node_mc313_compare_runs_clean():
    """`node tests/test_mc313_compare.js` exits 0 with all tests passing."""
    result = subprocess.run(
        ["node", TEST_JS],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "passed, 0 failed" in result.stdout or "passed, 0 failed (" in result.stdout, (
        f"Expected 0 failures. Stdout:\n{result.stdout}\nStderr:\n{result.stderr}"
    )
    assert result.returncode == 0, f"Exit code {result.returncode}: {result.stderr}"


def test_node_mc313_compare_storage_round_trip():
    result = subprocess.run(
        ["node", TEST_JS], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    assert "saveToStorage + loadFromStorage round-trip" in result.stdout
    assert "loadFromStorage: empty when nothing stored" in result.stdout
    assert "storage ignores malformed JSON" in result.stdout
    assert "storage filters non-string entries" in result.stdout


def test_node_mc313_compare_selection_mgmt():
    result = subprocess.run(
        ["node", TEST_JS], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    assert "addToCompare:" in result.stdout
    assert "removeFromCompare:" in result.stdout
    assert "toggleCompare:" in result.stdout
    assert "clearCompare:" in result.stdout


def test_node_mc313_compare_render_rows():
    result = subprocess.run(
        ["node", TEST_JS], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    assert "renderCompareRows:" in result.stdout
    assert "marks best-value cells with cmp-cell-best" in result.stdout
    assert "all required metric labels" in result.stdout


def test_node_mc313_compare_index_html_wiring():
    result = subprocess.run(
        ["node", TEST_JS], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    out = result.stdout
    assert "index.html: includes the compare.js script tag" in out
    assert "index.html: contains the compare modal markup" in out
    assert "index.html: deals table has checkbox column header" in out
    assert "index.html: renderDeals emits compare-check checkbox" in out
    assert "index.html: contains CSS for compare modal" in out


def test_static_compare_js_exists_and_has_api():
    """Static asset must be committed and have the expected API surface."""
    full = os.path.join(PROJECT_DIR, "static", "compare.js")
    assert os.path.exists(full), f"Missing: {full}"
    with open(full, encoding="utf-8") as f:
        src = f.read()
    # Sanity: file is non-empty, declares module export, has API surface
    assert len(src) > 1500
    assert "module.exports" in src
    for api in ["addToCompare", "removeFromCompare", "toggleCompare",
                "clearCompare", "openCompareModal", "closeCompareModal",
                "renderCompareRows", "rf_selected_ids", "MAX_SELECTED"]:
        assert api in src, f"compare.js missing API: {api}"