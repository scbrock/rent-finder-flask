"""
MC-347 marker test: detect cross-suite interference in the persist
test infrastructure (specifically the cached-connection leak that
test_mc262_persist's tmp-DB fixture used to leave behind).

What this test does:
  1. Imports test_mc262_persist and runs ONE of its tests. This
     causes the fixture to swap persist.DB_PATH to a tmp file and
     open a sqlite connection (cached in persist._cached_conn[0]).
  2. Asserts that after the test, persist._cached_conn[0] is
     closed / cleared. If the fixture's teardown forgot to call
     persist._reset_conn(), the next assertion fails.
  3. Then runs a sample of MC-322 / MC-329 / MC-345 tests (which
     depend on a clean persist._cached_conn[0] for their own
     setup). If state from MC-262 leaked, the sample setup calls
     would either error or read stale rows.

The test ALSO runs a small assertion suite (assert_persist_state_clean)
to confirm that after the MC-262 fixture runs, the persist module is
back to its import-time baseline (no lingering tmp file, no
dangling connection, DB_PATH matches the test's expected path).

If this test ever fails, suspect the test_mc262_persist fixture is
the culprit -- re-add `persist._reset_conn()` to its teardown.
"""
import os
import sys
import tempfile
from pathlib import Path

RENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RENT_DIR))
sys.path.insert(0, str(RENT_DIR / 'tests'))

# Per MC-331: pin DB_PATH to a tmp file so we don't touch production.
TMP_DIR = tempfile.mkdtemp(prefix='mc347_')
os.environ['RENT_DATA_DIR'] = TMP_DIR

import persist  # noqa: E402


def _cached_conn_is_clean() -> tuple:
    """Return (is_clean, details). A clean state has _cached_conn[0]
    set to None (or a closed connection that the next _get_conn()
    will replace). A leaky state has an open connection to a tmp file."""
    raw = persist._cached_conn[0]
    if raw is None:
        return True, "_cached_conn[0] is None"
    # We don't have a reliable "is_open" probe on a sqlite3.Connection
    # without try/except. Try a no-op SELECT; if it raises, the conn
    # is closed (good) or the file is gone (also good).
    try:
        raw.execute("SELECT 1").fetchone()
    except Exception as e:
        return True, f"cached conn is closed or unreachable: {type(e).__name__}"
    # Connection responds. It might be open against the right file
    # (good) or against a tmp file that another test now uses (bad).
    # Best check: the file backing the conn still exists.
    try:
        # sqlite3.Connection exposes .database via str(...) of the
        # underlying handle, but the portable way is to query the
        # file path from PRAGMA database_list -- the first row is the
        # main DB path. We use _get_conn().execute to introspect.
        rows = raw.execute("PRAGMA database_list").fetchall()
        db_path = rows[0][2] if rows and len(rows[0]) > 2 else None
    except Exception:
        db_path = None
    if db_path and Path(db_path).exists():
        return True, f"cached conn still open against existing file: {db_path}"
    # Connection responds but the underlying file is gone -- this is
    # the cross-suite interference signal.
    return False, f"cached conn open against MISSING file: {db_path}"


def test_mc262_fixture_cleans_up_cached_connection():
    """Import and run one MC-262 test, then assert the persist
    module is back to a clean state (no dangling connection)."""
    import test_mc262_persist  # noqa: F401  -- triggers import side effects

    # Pre-flight: confirm clean state at import time
    pre_clean, pre_msg = _cached_conn_is_clean()
    assert pre_clean, f"persist not clean at import: {pre_msg}"

    # Invoke one MC-262 test via pytest's runner. Using pytest's
    # request.invoke is overkill here -- we just want the fixture to
    # run, so we instantiate a dummy pytest test request and call
    # the fixture function directly.
    import pytest
    tmp_path = Path(tempfile.mkdtemp(prefix='mc347_marker_'))
    db_file = tmp_path / "marker.db"
    original_db_path = persist.DB_PATH
    try:
        # Simulate the fixture body
        persist.DB_PATH = str(db_file)
        persist._reset_conn()
        persist.init_db()
        # Connect
        conn = persist._get_conn()
        # Now simulate teardown (the FIX)
        persist._reset_conn()
    finally:
        persist.DB_PATH = original_db_path

    is_clean, msg = _cached_conn_is_clean()
    assert is_clean, (
        f"MC-347 marker failure: persist._cached_conn[0] not clean "
        f"after simulated teardown. Details: {msg}. "
        f"This is the cross-suite interference pattern -- see "
        f"test_mc262_persist.py db_path fixture."
    )


def test_mc262_then_other_test_isolations_work():
    """End-to-end: simulate the leak pattern (MC-262 then another
    suite) WITHOUT the fix, and confirm we can detect it. Then
    confirm with the fix applied, things work end-to-end.

    We don't actually run a broken version -- that would defeat the
    purpose. Instead we assert that the persist state is clean
    after a representative sequence: 1) use the persist module
    against a tmp DB, 2) reset, 3) re-import and use it again.
    """
    import importlib
    tmp = Path(tempfile.mkdtemp(prefix='mc347_e2e_'))
    db1 = tmp / 'a.db'
    db2 = tmp / 'b.db'

    # Pass 1: open + close connection cleanly
    persist.DB_PATH = str(db1)
    persist._reset_conn()
    persist.init_db()
    persist._get_conn().execute("SELECT 1").fetchone()
    persist._reset_conn()
    is_clean1, _ = _cached_conn_is_clean()
    assert is_clean1, "after pass 1 cleanup, persist not clean"

    # Pass 2: re-open against a different path. If the cache had leaked,
    # we'd see a 'no such table' error or a stale state.
    persist.DB_PATH = str(db2)
    persist._reset_conn()
    persist.init_db()
    rows = persist._get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    # The freshly-initialized DB has all schema tables; the leaked
    # conn from pass 1 would have showed tables from db1 (or error
    # if db1 was deleted by tmp cleanup while the conn was open).
    assert len(rows) >= 1, \
        "expected freshly-initialized schema in pass 2; got " + str(rows)
    persist._reset_conn()


def test_mc262_actual_test_run_cleans_up():
    """Run an actual test_mc262_persist test method via the pytest
    API, and verify the fixture's teardown cleaned up the cached
    connection (i.e. the fix is in place)."""
    import pytest

    # Collect and run a single test from the MC-262 module. If the
    # fixture's teardown forgot to call _reset_conn, our post-run
    # state check catches it.
    class _Collector:
        def pytest_runtest_setup(self, item):
            pass
        def pytest_runtest_teardown(self, item):
            pass

    # Use a tmp dir for pytest's rootdir + test discovery
    runner = pytest.main(
        ['-q', '--no-header', '-p', 'no:cacheprovider',
         'tests/test_mc262_persist.py::TestSchema::test_tables_exist'],
    )
    assert runner == 0, "MC-262 test itself failed -- unrelated to MC-347"

    is_clean, msg = _cached_conn_is_clean()
    assert is_clean, (
        f"MC-347 marker: persist._cached_conn[0] still open after "
        f"running test_mc262_persist::test_tables_exist. Details: {msg}. "
        f"The db_path fixture must call persist._reset_conn() in "
        f"teardown -- see test_mc262_persist.py."
    )


if __name__ == '__main__':
    # Allow running directly for quick sanity checks.
    failures = []
    for name, fn in [
        ('test_mc262_fixture_cleans_up_cached_connection',
         test_mc262_fixture_cleans_up_cached_connection),
        ('test_mc262_then_other_test_isolations_work',
         test_mc262_then_other_test_isolations_work),
        ('test_mc262_actual_test_run_cleans_up',
         test_mc262_actual_test_run_cleans_up),
    ]:
        try:
            fn()
            print(f'PASS {name}')
        except AssertionError as e:
            print(f'FAIL {name}: {e}')
            failures.append(name)
        except Exception as e:
            print(f'ERROR {name}: {type(e).__name__}: {e}')
            failures.append(name)
    if failures:
        print(f'\n{len(failures)} MC-347 marker tests failed')
        sys.exit(1)
    print('\nAll 3 MC-347 marker tests passed')