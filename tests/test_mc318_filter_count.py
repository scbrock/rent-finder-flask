"""MC-318: Wrapper that shells out to Node to run tests/test_mc318_filter_count.js.

Used by `pytest tests/test_mc318_filter_count.py` so the JS-side wiring
test is part of the suite without requiring a separate runner invocation.
"""
import os
import subprocess

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(THIS_DIR)
TEST_JS = os.path.join(THIS_DIR, "test_mc318_filter_count.js")


def _run_node():
    return subprocess.run(
        ["node", TEST_JS],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_node_mc318_runs_clean():
    """`node tests/test_mc318_filter_count.js` exits 0 with all tests passing."""
    result = _run_node()
    assert "passed, 0 failed" in result.stdout, (
        f"Expected 0 failures. Stdout:\n{result.stdout}\nStderr:\n{result.stderr}"
    )
    assert result.returncode == 0, f"Exit code {result.returncode}: {result.stderr}"


def test_node_mc318_wiring_array_includes_source():
    result = _run_node()
    assert result.returncode == 0
    assert "wiring array contains" in result.stdout
    assert "PASS index.html: wiring array contains" in result.stdout


def test_node_mc318_wiring_array_includes_max_subway():
    result = _run_node()
    assert result.returncode == 0
    out = result.stdout
    assert "wiring array contains" in out
    assert "max_subway" in out


def test_node_mc318_original_six_filter_ids_present():
    """Regression guard: beds_min, baths_min, price_min, price_max, neighbourhood, region."""
    result = _run_node()
    assert result.returncode == 0
    assert "wiring array still contains the original 6 filter ids" in result.stdout


def test_node_mc318_update_filter_count_body_has_source_and_max_subway():
    result = _run_node()
    assert result.returncode == 0
    assert "updateFilterCount body already counts source + max_subway" in result.stdout


def test_node_mc318_simulated_change_events_fire():
    result = _run_node()
    assert result.returncode == 0
    assert "simulated change: source select change updates badge" in result.stdout
    assert "simulated change: number input change updates badge" in result.stdout
