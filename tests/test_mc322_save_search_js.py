"""MC-322: Python wrapper that shells out to `node tests/test_mc322_save_search.js`.

Re-uses the existing Node test runner pattern from MC-318 / MC-313.
We don't parse Node's stdout — we just check the exit code. Node prints
'  17 passed, 0 failed' on success and exits 1 on failure.
"""

import os
import shutil
import subprocess
import sys

import pytest

RENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE_TEST = os.path.join(RENT_DIR, 'tests', 'test_mc322_save_search.js')


@pytest.fixture(scope='module')
def node_available():
    if shutil.which('node') is None:
        pytest.skip('node executable not on PATH')
    return shutil.which('node')


def _run_node_test():
    """Run the JS test and return (returncode, stdout, stderr)."""
    proc = subprocess.run(
        ['node', NODE_TEST],
        cwd=RENT_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_node_test_runs_clean(node_available):
    rc, out, err = _run_node_test()
    # On failure Node exits 1 + emits FAIL lines. On success: 0 + 'X passed, 0 failed'.
    if rc != 0:
        pytest.fail(
            f'node test_mc322_save_search.js failed (rc={rc})\n'
            f'--- stdout ---\n{out}\n--- stderr ---\n{err}'
        )
    assert 'passed' in out and 'failed' in out, (
        f'node test output missing summary line. stdout={out!r} stderr={err!r}'
    )
    # Sanity: assert the success count is at least the expected threshold.
    # The Node test prints lines like "  17 passed, 0 failed".
    first_pass_line = next(
        (ln for ln in out.splitlines() if 'passed' in ln and 'failed' in ln),
        ''
    )
    assert first_pass_line.endswith('failed'), (
        f'final summary line unexpected: {first_pass_line!r}'
    )
    # Pull the leading number out and make sure it's > 10 (sanity).
    n_passed = int(first_pass_line.strip().split()[0])
    assert n_passed >= 10, f'expected >= 10 passing JS tests, got {n_passed}'


def test_no_failures_in_stdout(node_available):
    rc, out, _ = _run_node_test()
    # If any FAIL line shows up, node exits 1 — but be explicit so a CI
    # log shows the failing test name clearly even if exit code is 0.
    fail_lines = [ln for ln in out.splitlines() if ln.strip().startswith('FAIL ')]
    assert not fail_lines, 'FAIL lines in JS test output:\n' + '\n'.join(fail_lines)


def test_node_test_is_wired_for_index_html(node_available):
    # Sanity check: make sure the JS test actually reads index.html
    # and saved_searches.html (so we don't silently skip coverage).
    with open(NODE_TEST, 'r', encoding='utf-8') as f:
        body = f.read()
    assert 'templates' in body or 'TPL_DIR' in body, \
        'JS test does not reference templates dir'
    assert 'index.html' in body, 'JS test does not mention index.html'
    assert 'saved_searches.html' in body, 'JS test does not mention saved_searches.html'


def test_python_and_node_test_files_exist():
    for relpath in [
        'tests/test_mc322_save_search.py',
        'tests/test_mc322_save_search.js',
    ]:
        path = os.path.join(RENT_DIR, relpath)
        assert os.path.isfile(path), f'MC-322 file missing: {path}'
        assert os.path.getsize(path) > 500, f'{path} unexpectedly small'


def test_saved_searches_html_template_exists():
    path = os.path.join(RENT_DIR, 'templates', 'saved_searches.html')
    assert os.path.isfile(path), f'missing template: {path}'
    # Sanity content
    with open(path, 'r', encoding='utf-8') as f:
        body = f.read()
    for marker in ['<title>Saved Searches', 'function loadSearches',
                   'function buildCard', 'function loadSearch',
                   'function deleteSearch', 'function submitRename',
                   '/api/saved-searches', '/saved-searches']:
        assert marker in body, f'saved_searches.html missing marker {marker!r}'


def test_index_html_has_save_search_wiring():
    path = os.path.join(RENT_DIR, 'templates', 'index.html')
    with open(path, 'r', encoding='utf-8') as f:
        body = f.read()
    for marker in ['id="save_search_btn"', 'openSaveSearchModal',
                   'save_search_modal', 'save_search_form',
                   'save_search_name', 'save_search_email',
                   'id="mc322_toast"', 'showMc322Toast',
                   'applySavedFilters', 'describeFilters',
                   'getCurrentFilterStateAsObject', 'maybeLoadFromPreselect',
                   '/api/saved-searches', 'id="saved_searches_link"']:
        assert marker in body, f'index.html missing MC-322 marker {marker!r}'
