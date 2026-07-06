"""MC-312: Wrapper that shells out to Node to run tests/test_mc312_gallery.js.

Used by `pytest tests/test_mc312_*.py` so that JS-side tests are part of the suite
without requiring a separate runner invocation.
"""
import os
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(THIS_DIR)
TEST_JS = os.path.join(THIS_DIR, "test_mc312_gallery.js")


def test_node_mc312_gallery_runs_clean():
    """`node tests/test_mc312_gallery.js` exits 0 with PASS lines on stdout."""
    result = subprocess.run(
        ["node", TEST_JS],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = result.stdout
    assert "passed, 0 failed" in out or "passed, 0 failed (" in out, (
        f"Expected 0 failures. Output:\n{out}\nStderr:\n{result.stderr}"
    )


def test_node_mc312_gallery_handles_zero_images():
    """Sanity check the 0-image path explicitly via Node stderr/stdout."""
    result = subprocess.run(
        ["node", TEST_JS],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Exit code {result.returncode}: {result.stderr}"
    assert "renderGallery: 0 images" in result.stdout


def test_node_mc312_gallery_state_transitions():
    """next/prev/goTo are unit-tested in the JS suite; check the suite covers them."""
    result = subprocess.run(
        ["node", TEST_JS],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    out = result.stdout
    assert "next(): advances" in out
    assert "prev():" in out
    assert "goTo():" in out
    assert "onChange:" in out


def test_node_mc312_gallery_index_html_wiring():
    """Suite verifies index.html includes the script tag."""
    result = subprocess.run(
        ["node", TEST_JS],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    out = result.stdout
    assert "index.html: includes the listing_gallery.js script tag" in out
    assert "index.html: contains data-count" in out


def test_listing_gallery_js_exists_and_minimal_size():
    """Static asset must be committed and loadable by Node test runner."""
    full = os.path.join(PROJECT_DIR, "static", "listing_gallery.js")
    assert os.path.exists(full), f"Missing: {full}"
    with open(full, encoding="utf-8") as f:
        src = f.read()
    # Sanity: file is non-empty, declares module export, has API surface
    assert len(src) > 1000
    assert "module.exports" in src
    assert "renderGallery" in src
    assert "next" in src
    assert "prev" in src
    assert "goTo" in src
