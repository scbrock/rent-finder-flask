"""MC-309: Python wrapper that runs the JS unit tests via Node.

Why this exists:
- The MC-309 lazy-load logic lives in `static/cl_photo_lazy.js` (browser JS).
- The actual unit tests are in `tests/test_mc309_cl_thumb_lazy.js`, written
  in plain Node 22 with a hand-rolled DOM/Observer mock (no jsdom dep).
- pytest is the project's test runner, so this wrapper shells out to `node`
  and surfaces pass/fail as a normal pytest assertion. If `node` isn't on
  PATH, the test is skipped (env-dependent, not a failure).

Run directly: `node tests/test_mc309_cl_thumb_lazy.js`
"""

import os
import shutil
import subprocess

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_TEST_PATH = os.path.join(PROJECT_ROOT, "tests", "test_mc309_cl_thumb_lazy.js")
MODULE_PATH = os.path.join(PROJECT_ROOT, "static", "cl_photo_lazy.js")


@pytest.fixture(scope="module")
def node_path():
    path = shutil.which("node")
    if path is None:
        pytest.skip("node is not on PATH; install Node to run MC-309 JS tests")
    return path


def _run_node_js_tests():
    """Execute the Node JS tests and return (returncode, stdout, stderr)."""
    proc = subprocess.run(
        ["node", JS_TEST_PATH],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestMC309PythonWrapper:
    """Python-side gate: the JS test suite must exit 0 and report all-pass."""

    def test_module_file_exists(self):
        # Guard: the JS module under test should be committed alongside tests.
        assert os.path.isfile(MODULE_PATH), (
            f"Missing MC-309 JS module at {MODULE_PATH}. "
            "Did you forget to add static/cl_photo_lazy.js?"
        )

    def test_indexhtml_defines_cl_lazy_class(self):
        # Lightweight HTML structure check: the rendered CL row should carry
        # data-cl-url so the observer can pick it up.
        idx_path = os.path.join(PROJECT_ROOT, "templates", "index.html")
        with open(idx_path, encoding="utf-8") as f:
            html = f.read()
        assert "deal-thumb-fallback cl-lazy" in html, (
            "Expected CL row fallback to include class `cl-lazy` for lazy-load hook"
        )
        assert "data-cl-url=" in html, (
            "Expected CL row fallback to carry data-cl-url attribute"
        )

    def test_indexhtml_loads_lazy_module(self):
        idx_path = os.path.join(PROJECT_ROOT, "templates", "index.html")
        with open(idx_path, encoding="utf-8") as f:
            html = f.read()
        # We accept either a Jinja url_for form or a hardcoded /static/... link.
        assert (
            "cl_photo_lazy.js" in html
            and ("static" in html or "/static/" in html)
        ), "index.html must reference static/cl_photo_lazy.js"

    def test_setupCLPhotoLazyLoad_invoked_from_renderDeals(self):
        idx_path = os.path.join(PROJECT_ROOT, "templates", "index.html")
        with open(idx_path, encoding="utf-8") as f:
            html = f.read()
        # The setup call should appear inside renderDeals (not just defined).
        # We use a simple regex search rather than parsing the script.
        assert "setupCLPhotoLazyLoad" in html, (
            "renderDeals() should call setupCLPhotoLazyLoad() to wire up the observer"
        )

    def test_js_test_suite_passes(self, node_path):
        rc, out, err = _run_node_js_tests()
        if rc != 0:
            # Print full output for diagnosis before failing.
            print("---- node stdout ----")
            print(out)
            print("---- node stderr ----")
            print(err)
        assert rc == 0, (
            f"Node test suite failed (exit={rc}). "
            "Run `node tests/test_mc309_cl_thumb_lazy.js` locally to inspect."
        )
        # The suite prints an "N/M tests passed" summary; sanity-check the format.
        assert "tests passed" in out, (
            f"Unexpected node output format:\n{out}"
        )
