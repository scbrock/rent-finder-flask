"""MC-323: Wrapper that shells out to Node to run tests/test_mc323_only_new.js.

Used by `pytest tests/test_mc323_only_new_js.py` so the JS-side wiring
test is part of the suite without requiring a separate runner invocation.
"""
import os
import subprocess

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(THIS_DIR)
TEST_JS = os.path.join(THIS_DIR, "test_mc323_only_new.js")


def _run_node():
    return subprocess.run(
        ["node", TEST_JS],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_node_mc323_runs_clean():
    """`node tests/test_mc323_only_new.js` exits 0 with all tests passing."""
    result = _run_node()
    assert "passed, 0 failed" in result.stdout, (
        f"Expected 0 failures. Stdout:\n{result.stdout}\nStderr:\n{result.stderr}"
    )
    assert result.returncode == 0, f"Exit code {result.returncode}: {result.stderr}"


def test_node_mc323_toggle_markup_present():
    result = _run_node()
    assert result.returncode == 0
    assert "Only NEW toggle input + label present" in result.stdout


def test_node_mc323_count_badge_wired():
    result = _run_node()
    assert result.returncode == 0
    assert "count badge placeholder element present" in result.stdout
    assert "loadNewCountBadge function fetches /api/meta" in result.stdout
    assert "loadNewCountBadge called during init" in result.stdout


def test_node_mc323_build_params_round_trip():
    result = _run_node()
    assert result.returncode == 0
    out = result.stdout
    assert "buildParams() sets is_new=true when toggle is checked" in out
    assert "buildParams() reads onlyNew from #only_new checkbox" in out


def test_node_mc323_parse_query_params_round_trip():
    result = _run_node()
    assert result.returncode == 0
    assert "parseQueryParams() reads is_new=true from URL" in result.stdout


def test_node_mc323_reset_clears_toggle():
    result = _run_node()
    assert result.returncode == 0
    assert "resetFilters() clears the Only NEW toggle" in result.stdout


def test_node_mc323_filter_count_increments():
    result = _run_node()
    assert result.returncode == 0
    assert "updateFilterCount() increments when Only NEW is checked" in result.stdout


def test_node_mc323_wiring_array_includes_only_new():
    result = _run_node()
    assert result.returncode == 0
    assert "bottom-of-file wiring array contains" in result.stdout


def test_node_mc323_existing_eight_filter_ids_preserved():
    """Regression guard: wiring array still contains beds_min..max_subway."""
    result = _run_node()
    assert result.returncode == 0
    assert "wiring array still includes the existing 8 filter ids" in result.stdout


def test_node_mc323_saved_search_round_trip():
    result = _run_node()
    assert result.returncode == 0
    out = result.stdout
    assert "applySavedFilters() reads filters.is_new" in out
    assert "getCurrentFilterStateAsObject() writes out.is_new" in out
    assert "describeFilters() mentions" in out


def test_node_mc323_active_class_styling_and_change_listener():
    result = _run_node()
    assert result.returncode == 0
    assert "explicit toggle handler (active-class toggle) wired" in result.stdout
    assert "CSS rule for #only_new_toggle active state" in result.stdout


def test_node_mc323_simulated_change_event():
    result = _run_node()
    assert result.returncode == 0
    assert "simulated change: only_new checkbox change fires updateFilterCount" in result.stdout