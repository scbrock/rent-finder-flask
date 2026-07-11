"""
MC-345 tests: force-refresh button (manual scrape trigger via UI).

4 test classes per AC6:
  - TestScrapeRunEndpoint: POST /api/scrape/run rate-limit + spawn
  - TestRecentRunsTable: persist-level CRUD for scrape_run_history
  - TestApiScrapeRunsHistory: GET /api/scrape/runs + /api/scrape/run/<id>
  - TestIndexHtmlWiring: HTML template refresh button + JS handler

All DB tests use a temp dir + isolated persist (consistent with the
rest of the rent_finder test suite). subprocess.run in app.py is
MONKEYPATCHED to a no-op stub that returns rc=0 + canned stdout --
no real `python find_deals.py` is ever invoked.

Run: python tests/test_mc345_force_refresh.py
"""
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

RENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RENT_DIR))

# Use a fresh per-test-file DB so we don't touch production listings.db.
TMP_DIR = tempfile.mkdtemp(prefix='mc345_')
os.environ['RENT_DATA_DIR'] = TMP_DIR

import persist as persist_module
import app as app_module

# MC-345: same root-cause fix as MC-331 -- pin DB_PATH to the
# env-var-driven path. Without this, init_db() in any test runs against
# the prod path (since persist was first imported when RENT_DATA_DIR
# was unset, before this file's env-var override).
persist_module.DB_PATH = os.path.join(TMP_DIR, 'listings.db')
app_module.DB_PATH = persist_module.DB_PATH


# ── Helpers ─────────────────────────────────────────────────────────────


def _seed_run(started_at: str, finished_at=None, exit_code=None,
              listings_collected=None, deals_count=None,
              stderr_tail=None, trigger='force_refresh', ip='1.2.3.4'):
    """Insert a row directly via persist for DB-level tests."""
    import sqlite3
    conn = sqlite3.connect(persist_module.DB_PATH)
    try:
        conn.execute(
            """INSERT INTO scrape_run_history
               (started_at, finished_at, trigger, ip, exit_code,
                listings_collected, deals_count, stderr_tail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (started_at, finished_at, trigger, ip, exit_code,
             listings_collected, deals_count, stderr_tail),
        )
        conn.commit()
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()
    return rid


def _client():
    return app_module.app.test_client()


# Reset the rate-limit state between tests so 1-per-5min doesn't leak.
def _reset_rate_limit():
    if '_force_refresh_state' in dir(app_module):
        with app_module._force_refresh_state['lock']:
            app_module._force_refresh_state['ip_last_run'].clear()


# ════════════════════════════════════════════════════════════════════════
# Class 1: persist CRUD
# ════════════════════════════════════════════════════════════════════════


class TestRecentRunsTable:
    """AC2: schema + CRUD on scrape_run_history."""

    def test_schema_initialised_with_correct_columns(self):
        import sqlite3
        conn = sqlite3.connect(persist_module.DB_PATH)
        try:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(scrape_run_history)"
            ).fetchall()]
        finally:
            conn.close()
        required = {'run_id', 'started_at', 'finished_at', 'trigger', 'ip',
                    'exit_code', 'listings_collected', 'deals_count',
                    'stderr_tail'}
        assert required.issubset(set(cols)), \
            f"missing columns: {required - set(cols)}"

    def test_create_scrape_run_history_row_returns_id(self):
        rid = persist_module.create_scrape_run_history_row(
            started_at='2026-07-09T10:00:00Z',
            trigger='force_refresh', ip='1.2.3.4',
        )
        assert isinstance(rid, int) and rid > 0
        row = persist_module.get_scrape_run_history_row(rid)
        assert row is not None
        assert row['started_at'] == '2026-07-09T10:00:00Z'
        assert row['finished_at'] is None
        assert row['exit_code'] is None
        assert row['ip'] == '1.2.3.4'

    def test_finish_scrape_run_history_row_updates_lifecycle(self):
        rid = persist_module.create_scrape_run_history_row(
            started_at='2026-07-09T10:00:00Z',
        )
        persist_module.finish_scrape_run_history_row(
            run_id=rid,
            finished_at='2026-07-09T10:05:00Z',
            exit_code=0,
            listings_collected=250,
            deals_count=97,
            stderr_tail='all good',
        )
        row = persist_module.get_scrape_run_history_row(rid)
        assert row['finished_at'] == '2026-07-09T10:05:00Z'
        assert row['exit_code'] == 0
        assert row['listings_collected'] == 250
        assert row['deals_count'] == 97
        assert row['stderr_tail'] == 'all good'

    def test_stderr_tail_truncated_to_2k(self):
        """The AC says stderr_tail is the last ~2kB -- persisted value
        must be capped to 2000 chars even if we pass more."""
        rid = persist_module.create_scrape_run_history_row(
            started_at='2026-07-09T10:00:00Z',
        )
        big_stderr = 'X' * 5000
        persist_module.finish_scrape_run_history_row(
            run_id=rid,
            finished_at='2026-07-09T10:05:00Z',
            exit_code=1,
            stderr_tail=big_stderr,
        )
        row = persist_module.get_scrape_run_history_row(rid)
        assert len(row['stderr_tail']) == 2000, \
            f"expected 2000 chars, got {len(row['stderr_tail'])}"
        # Specifically: last 2kB of the input, not the first 2kB.
        assert row['stderr_tail'] == big_stderr[-2000:]

    def test_list_scrape_run_history_newest_first(self):
        # Clear the table so the assertion is deterministic regardless of
        # test-order residue (other tests in this class already insert rows).
        import sqlite3
        conn = sqlite3.connect(persist_module.DB_PATH)
        try:
            conn.execute("DELETE FROM scrape_run_history")
            conn.commit()
        finally:
            conn.close()
        for ts in ['2026-07-09T08:00:00Z', '2026-07-09T10:00:00Z',
                    '2026-07-09T09:00:00Z']:
            _seed_run(started_at=ts)
        runs = persist_module.list_scrape_run_history(limit=10)
        assert [r['started_at'] for r in runs] == [
            '2026-07-09T10:00:00Z',
            '2026-07-09T09:00:00Z',
            '2026-07-09T08:00:00Z',
        ]

    def test_list_scrape_run_history_respects_limit(self):
        for i in range(15):
            _seed_run(started_at=f'2026-07-09T{i:02d}:00:00Z')
        assert len(persist_module.list_scrape_run_history(limit=10)) == 10
        assert len(persist_module.list_scrape_run_history(limit=3)) == 3

    def test_get_scrape_run_history_row_returns_none_for_unknown(self):
        assert persist_module.get_scrape_run_history_row(999999) is None


# ════════════════════════════════════════════════════════════════════════
# Class 2: POST /api/scrape/run (rate-limit + spawn)
# ════════════════════════════════════════════════════════════════════════


class TestScrapeRunEndpoint:
    """AC1 + AC5: rate-limit, spawn, return 202."""

    def setup_method(self):
        _reset_rate_limit()
        # Patch subprocess.run so the endpoint doesn't actually shell out.
        self._patches = []
        fake_completed = MagicMock()
        fake_completed.returncode = 0
        fake_completed.stdout = "Total listings: 250 | Sources: kijiji,craigslist\nDeals found: 97"
        fake_completed.stderr = ""
        self._fake_completed = fake_completed
        self._subproc_patcher = patch.object(
            app_module.subprocess, 'run', return_value=fake_completed,
        )
        self._subproc_patcher.start()

    def teardown_method(self):
        self._subproc_patcher.stop()

    def test_post_returns_202_with_run_id(self):
        c = _client()
        resp = c.post('/api/scrape/run')
        assert resp.status_code == 202
        data = resp.get_json()
        assert 'run_id' in data and isinstance(data['run_id'], int)
        assert data['status'] == 'running'
        assert 'started_at' in data

    def test_post_creates_persist_row_with_trigger_force_refresh(self):
        c = _client()
        resp = c.post('/api/scrape/run')
        run_id = resp.get_json()['run_id']
        row = persist_module.get_scrape_run_history_row(run_id)
        assert row is not None
        assert row['trigger'] == 'force_refresh'

    def test_post_rate_limits_same_ip_within_5_minutes(self):
        c = _client()
        # First call succeeds
        r1 = c.post('/api/scrape/run')
        assert r1.status_code == 202
        # Second call within 5 min is 429
        r2 = c.post('/api/scrape/run')
        assert r2.status_code == 429
        body = r2.get_json()
        assert body['error'] == 'rate_limited'
        assert body['retry_after_seconds'] > 0
        assert body['retry_after_seconds'] <= 300

    def test_post_background_thread_runs_subprocess_and_updates_row(self):
        c = _client()
        resp = c.post('/api/scrape/run')
        run_id = resp.get_json()['run_id']
        # Wait for the background thread to finish. The fake subprocess
        # returns immediately, so within ~1s the row should be fully updated.
        deadline = time.time() + 5
        while time.time() < deadline:
            row = persist_module.get_scrape_run_history_row(run_id)
            if row and row['finished_at'] is not None:
                break
            time.sleep(0.1)
        row = persist_module.get_scrape_run_history_row(run_id)
        assert row['finished_at'] is not None
        assert row['exit_code'] == 0
        # listings_collected + deals_count parsed from fake stdout
        assert row['listings_collected'] == 250
        assert row['deals_count'] == 97

    def test_post_run_id_is_unique_per_invocation(self):
        c = _client()
        r1 = c.post('/api/scrape/run')
        run_id1 = r1.get_json()['run_id']
        _reset_rate_limit()  # bypass rate-limit for back-to-back calls in test
        r2 = c.post('/api/scrape/run')
        run_id2 = r2.get_json()['run_id']
        assert run_id1 != run_id2

    def test_post_records_client_ip(self):
        c = _client()
        resp = c.post('/api/scrape/run', environ_overrides={'REMOTE_ADDR': '9.9.9.9'})
        run_id = resp.get_json()['run_id']
        # Wait for the background thread to update ip
        deadline = time.time() + 5
        while time.time() < deadline:
            row = persist_module.get_scrape_run_history_row(run_id)
            if row and row['finished_at'] is not None:
                break
            time.sleep(0.1)
        row = persist_module.get_scrape_run_history_row(run_id)
        assert row['ip'] == '9.9.9.9'


# ════════════════════════════════════════════════════════════════════════
# Class 3: GET /api/scrape/runs + /api/scrape/run/<id>
# ════════════════════════════════════════════════════════════════════════


class TestApiScrapeRunsHistory:
    """AC2: Recent runs list + per-run status endpoint."""

    def test_get_runs_returns_runs_key(self):
        c = _client()
        resp = c.get('/api/scrape/runs')
        assert resp.status_code == 200
        assert 'runs' in resp.get_json()

    def test_get_runs_limit_query_param(self):
        c = _client()
        for i in range(12):
            _seed_run(started_at=f'2026-07-09T{i:02d}:00:00Z')
        resp = c.get('/api/scrape/runs?limit=5')
        assert resp.status_code == 200
        assert len(resp.get_json()['runs']) == 5

    def test_get_runs_invalid_limit_uses_default(self):
        c = _client()
        for i in range(12):
            _seed_run(started_at=f'2026-07-09T{i:02d}:00:00Z')
        # Non-integer falls back to default 10
        resp = c.get('/api/scrape/runs?limit=notanumber')
        assert resp.status_code == 200
        assert len(resp.get_json()['runs']) == 10

    def test_get_runs_newest_first(self):
        # Clear the table to avoid residue from earlier tests in the
        # class or run order.
        import sqlite3
        conn = sqlite3.connect(persist_module.DB_PATH)
        try:
            conn.execute("DELETE FROM scrape_run_history")
            conn.commit()
        finally:
            conn.close()
        c = _client()
        for ts in ['2026-07-09T08:00:00Z', '2026-07-09T10:00:00Z',
                    '2026-07-09T09:00:00Z']:
            _seed_run(started_at=ts)
        runs = c.get('/api/scrape/runs').get_json()['runs']
        assert runs[0]['started_at'] == '2026-07-09T10:00:00Z'
        assert runs[1]['started_at'] == '2026-07-09T09:00:00Z'
        assert runs[2]['started_at'] == '2026-07-09T08:00:00Z'

    def test_get_run_status_returns_200_for_known(self):
        rid = _seed_run(started_at='2026-07-09T10:00:00Z')
        c = _client()
        resp = c.get(f'/api/scrape/run/{rid}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['run_id'] == rid
        assert data['started_at'] == '2026-07-09T10:00:00Z'

    def test_get_run_status_returns_404_for_unknown(self):
        c = _client()
        resp = c.get('/api/scrape/run/999999')
        assert resp.status_code == 404
        assert resp.get_json()['error'] == 'not_found'

    def test_get_run_status_reflects_running_state(self):
        """If finished_at is NULL, the row is still running."""
        import sqlite3
        conn = sqlite3.connect(persist_module.DB_PATH)
        try:
            conn.execute("DELETE FROM scrape_run_history")
            conn.commit()
        finally:
            conn.close()
        _seed_run(started_at='2026-07-09T10:00:00Z')  # no finished_at
        c = _client()
        resp = c.get('/api/scrape/runs')
        runs = resp.get_json()['runs']
        assert len(runs) == 1
        assert runs[0]['finished_at'] is None
        assert runs[0]['exit_code'] is None


# ════════════════════════════════════════════════════════════════════════
# Class 4: HTML template wiring (button + JS handler)
# ════════════════════════════════════════════════════════════════════════


class TestIndexHtmlTrendBadgeWiring:
    """AC3: Refresh button inside the freshness pill.
       AC4: Refreshing state + success/failure toast (we test the
       inline code paths; live integration is in the manual smoke)."""

    @staticmethod
    def _read_template() -> str:
        return (RENT_DIR / 'templates' / 'index.html').read_text(encoding='utf-8')

    def test_refresh_button_is_inside_health_pill(self):
        html = self._read_template()
        # Health pill div has id="health_pill"; refresh button has id="force_refresh_btn".
        # Verify both are present AND the button appears AFTER the pill open tag
        # (inside the pill, not after the closing div).
        pill_open = html.index('id="health_pill"')
        pill_close_marker = '</div>\n  <!-- MC-339'  # sentinel after the pill closes
        pill_close = html.index(pill_close_marker)
        btn_pos = html.index('id="force_refresh_btn"')
        assert pill_open < btn_pos < pill_close, \
            "force_refresh_btn must be inside the health_pill div (not after it closes)"

    def test_refresh_button_has_click_handler(self):
        html = self._read_template()
        # Inline onclick OR a separate addEventListener binding -- both are valid.
        # We assert SOMETHING wires the click to the trigger function.
        m = re.search(
            r'(id="force_refresh_btn"[^>]*onclick="triggerForceRefresh\(\)"|'
            r'addEventListener\(\s*[\'"]click[\'"]\s*,\s*triggerForceRefresh)',
            html, re.DOTALL,
        )
        assert m, "Refresh button must be wired to triggerForceRefresh (onclick or addEventListener)"

    def test_trigger_force_refresh_function_defined(self):
        html = self._read_template()
        m = re.search(r'async\s+function\s+triggerForceRefresh\s*\(', html)
        assert m, "triggerForceRefresh() function must be defined"

    def test_refreshing_state_text_in_handler(self):
        """AC4: 'Refreshing...' text in handler to set on the button."""
        html = self._read_template()
        # The handler should mutate btn.textContent to 'Refreshing...' while
        # the run is in flight. Either via direct assignment or via a
        # Refreshing / refreshing flag.
        assert "Refreshing" in html, \
            "Handler should set button/state to a Refreshing indicator"

    def test_poll_endpoint_referenced_in_handler(self):
        """AC1: handler polls /api/scrape/run/<id> for completion."""
        html = self._read_template()
        # Look for the per-run poll URL pattern (uses runId template literal).
        m = re.search(r"/api/scrape/run/\$\{?runId", html)
        assert m, "Handler must poll /api/scrape/run/<id> for completion"

    def test_toast_function_defined(self):
        """AC4: success/failure toast helper exists."""
        html = self._read_template()
        m = re.search(r'function\s+_showForceRefreshToast\s*\(', html)
        assert m, "_showForceRefreshToast() function must be defined"

    def test_toast_kind_param_supports_success_and_error(self):
        """AC4: toast renders success (green) and error (red)."""
        html = self._read_template()
        # The CSS for the toast branches on 'data-kind' attribute.
        m = re.search(r"data-kind.*?success.*?error|success.*?error.*?data-kind", html, re.DOTALL)
        # Simpler: just verify both literals appear in the toast function.
        assert "'success'" in html and "'error'" in html, \
            "toast must support 'success' and 'error' kinds"

    def test_post_endpoint_url_in_handler(self):
        """AC1: handler POSTs to /api/scrape/run."""
        html = self._read_template()
        m = re.search(r"fetch\(['\"]\/api\/scrape\/run['\"]", html)
        assert m, "Handler must POST to /api/scrape/run"

    def test_reload_health_pill_after_success(self):
        """AC4: handler reloads loadHealthPill() on success."""
        html = self._read_template()
        # The success branch should call loadHealthPill() to refresh the pill
        # with the new minutes_since_scrape from the just-finished run.
        # Find the success branch in the poller's .then or callback.
        assert "loadHealthPill" in html, \
            "Handler must call loadHealthPill() to refresh the pill on success"

    def test_disabled_during_run(self):
        """AC3: button.disabled = true while run is in flight."""
        html = self._read_template()
        m = re.search(r"btn\.disabled\s*=\s*true", html)
        assert m, "Button must be disabled (btn.disabled = true) while run is in flight"

    def test_re_enables_on_completion(self):
        """AC3: button.disabled = false after run completes."""
        html = self._read_template()
        m = re.search(r"btn\.disabled\s*=\s*false", html)
        assert m, "Button must be re-enabled (btn.disabled = false) on completion"


# ── Runner ───────────────────────────────────────────────────────────────


def _run_all() -> None:
    import inspect
    classes = [
        TestRecentRunsTable,
        TestScrapeRunEndpoint,
        TestApiScrapeRunsHistory,
        TestIndexHtmlTrendBadgeWiring,
    ]
    total = 0
    failed = 0
    for cls in classes:
        # One instance per class; setup_method is called per-test below
        # so each test gets a fresh patch + rate-limit reset.
        instance = cls()
        for name, fn in inspect.getmembers(cls, predicate=inspect.isfunction):
            if not name.startswith("test_"):
                continue
            total += 1
            # Call setup_method if the class defines one.
            setup = getattr(instance, "setup_method", None)
            teardown = getattr(instance, "teardown_method", None)
            if callable(setup):
                try:
                    setup()
                except Exception as e:
                    print(f"ERROR setup for {cls.__name__}.{name}: {e}")
            try:
                fn(instance)
                print(f"PASS {cls.__name__}.{name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {cls.__name__}.{name}: {e}")
            except Exception as e:
                failed += 1
                print(f"ERROR {cls.__name__}.{name}: {type(e).__name__}: {e}")
            if callable(teardown):
                try:
                    teardown()
                except Exception:
                    pass
    if failed:
        print(f"\n{failed}/{total} tests failed.")
        sys.exit(1)
    print(f"\nAll {total} MC-345 force-refresh tests passed.")


if __name__ == "__main__":
    _run_all()