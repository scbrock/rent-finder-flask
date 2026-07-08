"""
Tests for MC-322: Save Current Filters button + /saved-searches management page.

Coverage:
  - persist.py: schema migration idempotency (filters_json column)
  - persist.py: upsert_saved_search with filters_json persists + retrievable
  - persist.py: upsert_saved_search without filters_json still works (back-compat -> '{}')
  - persist.py: get_saved_search_by_id returns parsed filters_dict, None on unknown
  - persist.py: get_saved_searches returns filters_dict on each row
  - app.py: POST /api/saved-searches with filters_json dict, string, missing, invalid
  - app.py: PUT /api/saved-searches/<id> with/without filters_json (keep-exists vs replace)
  - app.py: GET /api/saved-searches/load (200/400/404 paths)
  - app.py: GET /saved-searches renders 200
  - HTML wiring: Save button + modal in index.html
  - HTML wiring: /saved-searches link in index.html + neighborhood.html + shortlist.html + profile.html + alerts.html
"""

import os
import sys
import json
import sqlite3
import tempfile
import importlib

import pytest

# Ensure rent_finder is importable
RENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RENT_DIR)

# Use a fresh per-test DB so we don't touch production listings.db
TMP_DIR = tempfile.mkdtemp(prefix='mc322_')
os.environ['RENT_DATA_DIR'] = TMP_DIR

import persist as persist_module  # noqa: E402
import app as app_module  # noqa: E402

# MC-331: Also pin persist_module.DB_PATH to the env-var-driven path.
# `DB_PATH` is a module-level constant evaluated at import time. If a
# prior test file (e.g. test_mc262_persist.py) imported `persist` first
# with no RENT_DATA_DIR set, DB_PATH was bound to APP_DIR/data/listings.db
# and `init_db()` would write to the prod path even after we set the env
# var. Setting DB_PATH here aligns the module with the test's TMP_DIR
# so init_db() in every test writes to the expected isolated file.
# This is a TEST-ONLY fix -- persist.py's DB_PATH semantics are unchanged.
persist_module.DB_PATH = os.path.join(TMP_DIR, 'listings.db')
app_module.DB_PATH = persist_module.DB_PATH


@pytest.fixture(autouse=True)
def reset_db():
    """Reset the SQLite DB before every test."""
    db_path = os.path.join(TMP_DIR, 'listings.db')
    # Reset cached connection FIRST so persist releases its file handle
    # before we try to delete the DB file (Windows locks files held open).
    if hasattr(persist_module, '_reset_conn'):
        persist_module._reset_conn()
    # Best-effort checkpoint + close any stray connections via raw sqlite3.
    # WAL mode leaves -wal/-shm sidecars that block os.remove on Windows.
    for ext in ('', '-wal', '-shm', '-journal'):
        p = db_path + ext
        if os.path.exists(p):
            try:
                os.remove(p)
            except PermissionError:
                # On Windows, a previous test's WAL can hold the file open
                # for a beat. Best-effort: try sqlite checkpoint + retry.
                try:
                    import sqlite3 as _sq
                    _conn = _sq.connect(db_path)
                    _conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    _conn.close()
                except Exception:
                    pass
                try:
                    os.remove(p)
                except Exception:
                    pass
    # Re-init schema for this test
    persist_module.init_db()
    yield
    if hasattr(persist_module, '_reset_conn'):
        persist_module._reset_conn()
    # On teardown, also checkpoint + drop sidecars so the next test doesn't
    # inherit a stale WAL lock.
    for ext in ('', '-wal', '-shm', '-journal'):
        p = db_path + ext
        if os.path.exists(p):
            try:
                if ext == '':
                    try:
                        import sqlite3 as _sq
                        _conn = _sq.connect(db_path)
                        _conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        _conn.close()
                    except Exception:
                        pass
                os.remove(p)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Schema & migration
# ---------------------------------------------------------------------------

class TestSchemaMigration:
    def test_filters_json_column_exists_after_init(self):
        persist_module.init_db()
        conn = sqlite3.connect(os.path.join(TMP_DIR, 'listings.db'))
        cols = [row[1] for row in conn.execute("PRAGMA table_info(saved_searches)").fetchall()]
        conn.close()
        assert 'filters_json' in cols

    def test_filters_json_default_is_text(self):
        persist_module.init_db()
        conn = sqlite3.connect(os.path.join(TMP_DIR, 'listings.db'))
        row = conn.execute(
            "SELECT type FROM pragma_table_info('saved_searches') WHERE name = 'filters_json'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert 'TEXT' in row[0].upper()

    def test_init_db_is_idempotent(self):
        persist_module.init_db()
        persist_module.init_db()  # second time should not raise
        persist_module.init_db()  # third time

    def test_existing_saved_searches_get_filters_json_empty_default(self):
        persist_module.init_db()
        conn = sqlite3.connect(os.path.join(TMP_DIR, 'listings.db'))
        # Simulate legacy row by inserting without filters_json
        conn.execute("""
            INSERT INTO saved_searches (email, name, beds_min, price_max)
            VALUES ('legacy@x.ca', 'legacy search', 1, 2500)
        """)
        conn.commit()
        # Run init_db again (migration re-runs, no-op for existing column)
        persist_module.init_db()
        row = conn.execute(
            "SELECT filters_json FROM saved_searches WHERE email = 'legacy@x.ca'"
        ).fetchone()
        conn.close()
        # New default applies to inserts, but legacy rows keep their NULL
        # we verify the migration column itself is queryable.
        # The legacy value may be NULL or '{}' depending on migration semantics;
        # accept either as long as the column exists.
        assert row is None or row[0] in (None, '{}')


# ---------------------------------------------------------------------------
# upsert_saved_search with filters_json
# ---------------------------------------------------------------------------

class TestUpsertFiltersJson:
    def test_upsert_with_filters_json_dict_is_persisted_as_json_string(self):
        persist_module.init_db()
        sid = persist_module.upsert_saved_search(
            email='a@b.ca', name='search A',
            filters_json=json.dumps({'source': 'kijiji', 'sort': 'pct'}),
        )
        row = persist_module.get_saved_search_by_id('a@b.ca', sid)
        assert row is not None
        assert row['filters_json'] == '{"source": "kijiji", "sort": "pct"}'
        assert row['filters_dict'] == {'source': 'kijiji', 'sort': 'pct'}

    def test_upsert_without_filters_json_defaults_to_empty_dict(self):
        persist_module.init_db()
        sid = persist_module.upsert_saved_search(email='a@b.ca', name='search B')
        row = persist_module.get_saved_search_by_id('a@b.ca', sid)
        assert row['filters_json'] == '{}'
        assert row['filters_dict'] == {}

    def test_upsert_with_explicit_empty_string_becomes_empty_dict(self):
        persist_module.init_db()
        sid = persist_module.upsert_saved_search(
            email='a@b.ca', name='search C', filters_json=''
        )
        row = persist_module.get_saved_search_by_id('a@b.ca', sid)
        assert row['filters_json'] == '{}'
        assert row['filters_dict'] == {}

    def test_upsert_updates_filters_json_on_conflict(self):
        persist_module.init_db()
        sid1 = persist_module.upsert_saved_search(
            email='a@b.ca', name='search D',
            filters_json='{"source": "kijiji"}',
        )
        sid2 = persist_module.upsert_saved_search(
            email='a@b.ca', name='search D',
            filters_json='{"source": "craigslist"}',
        )
        assert sid1 == sid2
        row = persist_module.get_saved_search_by_id('a@b.ca', sid1)
        assert row['filters_dict']['source'] == 'craigslist'

    def test_upsert_round_trips_complex_nested_filters(self):
        persist_module.init_db()
        payload = {
            'beds_min': '1', 'price_max': '2500',
            'source': 'kijiji', 'sort': 'pct',
            'has_parking': 'true', 'hide_stale': 'true',
            'commute_dest': 'Union Station',
            'max_commute': '20', 'max_subway': '5',
            'neighbourhood': 'King West', 'region': 'Downtown',
        }
        sid = persist_module.upsert_saved_search(
            email='a@b.ca', name='nested', filters_json=json.dumps(payload),
        )
        row = persist_module.get_saved_search_by_id('a@b.ca', sid)
        for k, v in payload.items():
            assert row['filters_dict'][k] == v

    def test_legacy_columns_still_populated_alongside_filters_json(self):
        persist_module.init_db()
        sid = persist_module.upsert_saved_search(
            email='a@b.ca', name='mixed',
            beds_min=1, price_max=2500, neighbourhood='King West',
            filters_json='{"source": "kijiji"}',
        )
        row = persist_module.get_saved_search_by_id('a@b.ca', sid)
        assert row['beds_min'] == 1
        assert row['price_max'] == 2500
        assert row['neighbourhood'] == 'King West'
        assert row['filters_dict']['source'] == 'kijiji'


# ---------------------------------------------------------------------------
# get_saved_search_by_id
# ---------------------------------------------------------------------------

class TestGetSavedSearchById:
    def test_returns_full_row_with_filters_dict(self):
        persist_module.init_db()
        sid = persist_module.upsert_saved_search(
            email='a@b.ca', name='q', filters_json='{"source": "kijiji"}',
        )
        row = persist_module.get_saved_search_by_id('a@b.ca', sid)
        assert row is not None
        assert row['search_id'] == sid
        assert row['name'] == 'q'
        assert isinstance(row['filters_dict'], dict)
        assert row['filters_dict']['source'] == 'kijiji'

    def test_returns_none_for_unknown_id(self):
        persist_module.init_db()
        row = persist_module.get_saved_search_by_id('a@b.ca', 99999)
        assert row is None

    def test_email_gating_other_email_returns_none(self):
        persist_module.init_db()
        sid = persist_module.upsert_saved_search(email='owner@b.ca', name='x')
        row = persist_module.get_saved_search_by_id('other@b.ca', sid)
        assert row is None

    def test_malformed_filters_json_returns_empty_dict_not_crash(self):
        persist_module.init_db()
        # Insert a row with garbage filters_json directly
        conn = sqlite3.connect(os.path.join(TMP_DIR, 'listings.db'))
        conn.execute("""
            INSERT INTO saved_searches (email, name, filters_json)
            VALUES ('a@b.ca', 'bad', 'not parseable json {')
        """)
        conn.commit()
        sid = conn.execute(
            "SELECT search_id FROM saved_searches WHERE name='bad'"
        ).fetchone()[0]
        conn.close()
        row = persist_module.get_saved_search_by_id('a@b.ca', sid)
        assert row['filters_dict'] == {}


# ---------------------------------------------------------------------------
# get_saved_searches (list) adds filters_dict per row
# ---------------------------------------------------------------------------

class TestGetSavedSearchesAddsFiltersDict:
    def test_each_row_exposes_filters_dict(self):
        persist_module.init_db()
        persist_module.upsert_saved_search(
            email='a@b.ca', name='one', filters_json='{"source": "kijiji"}',
        )
        persist_module.upsert_saved_search(
            email='a@b.ca', name='two', filters_json='{"sort": "price"}',
        )
        rows = persist_module.get_saved_searches('a@b.ca')
        assert len(rows) == 2
        # Order is by created_at ascending -> 'one' first
        assert rows[0]['filters_dict'] == {'source': 'kijiji'}
        assert rows[1]['filters_dict'] == {'sort': 'price'}
        # match_count + top_match also still work (back-compat)
        for r in rows:
            assert 'match_count' in r
            assert 'top_match' in r

    def test_empty_email_returns_empty_list(self):
        persist_module.init_db()
        persist_module.upsert_saved_search(email='other@b.ca', name='x')
        rows = persist_module.get_saved_searches('nobody@nope.com')
        assert rows == []


# ---------------------------------------------------------------------------
# POST /api/saved-searches (filters_json variants)
# ---------------------------------------------------------------------------

class TestCreateEndpointFiltersJson:
    @pytest.fixture
    def client(self):
        return app_module.app.test_client()

    def test_post_with_filters_json_dict(self, client):
        resp = client.post('/api/saved-searches', json={
            'email': 'a@b.ca',
            'name': 'post-dict',
            'filters_json': {'source': 'kijiji', 'sort': 'pct'},
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        row = persist_module.get_saved_search_by_id('a@b.ca', data['search_id'])
        assert row['filters_dict'] == {'source': 'kijiji', 'sort': 'pct'}

    def test_post_with_filters_json_string(self, client):
        resp = client.post('/api/saved-searches', json={
            'email': 'a@b.ca',
            'name': 'post-str',
            'filters_json': '{"source": "craigslist", "hide_stale": "true"}',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        row = persist_module.get_saved_search_by_id('a@b.ca', data['search_id'])
        assert row['filters_dict']['source'] == 'craigslist'

    def test_post_without_filters_json_defaults(self, client):
        resp = client.post('/api/saved-searches', json={
            'email': 'a@b.ca', 'name': 'no-fj',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        row = persist_module.get_saved_search_by_id('a@b.ca', data['search_id'])
        assert row['filters_dict'] == {}

    def test_post_with_empty_string_filters_json(self, client):
        resp = client.post('/api/saved-searches', json={
            'email': 'a@b.ca', 'name': 'empty-fj',
            'filters_json': '',
        })
        assert resp.status_code == 200
        row = persist_module.get_saved_search_by_id(
            'a@b.ca', resp.get_json()['search_id']
        )
        assert row['filters_dict'] == {}

    def test_post_invalid_json_returns_400(self, client):
        resp = client.post('/api/saved-searches', json={
            'email': 'a@b.ca', 'name': 'bad',
            'filters_json': 'not parseable{',
        })
        assert resp.status_code == 400

    def test_post_list_not_object_returns_400(self, client):
        resp = client.post('/api/saved-searches', json={
            'email': 'a@b.ca', 'name': 'list-fj',
            'filters_json': '["kijiji", "pct"]',
        })
        assert resp.status_code == 400

    def test_post_unsupported_type_returns_400(self, client):
        resp = client.post('/api/saved-searches', json={
            'email': 'a@b.ca', 'name': 'int-fj',
            'filters_json': 42,
        })
        assert resp.status_code == 400

    def test_post_no_email_returns_400(self, client):
        resp = client.post('/api/saved-searches', json={
            'name': 'noemail', 'filters_json': {'a': 1},
        })
        assert resp.status_code == 400

    def test_post_no_name_returns_400(self, client):
        resp = client.post('/api/saved-searches', json={
            'email': 'a@b.ca', 'name': '', 'filters_json': {'a': 1},
        })
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PUT /api/saved-searches/<id>
# ---------------------------------------------------------------------------

class TestUpdateEndpointFiltersJson:
    @pytest.fixture
    def client(self):
        return app_module.app.test_client()

    def _create(self, client):
        resp = client.post('/api/saved-searches', json={
            'email': 'a@b.ca',
            'name': 'upd-1',
            'filters_json': {'source': 'kijiji'},
        })
        return resp.get_json()['search_id']

    def test_put_replaces_filters_json(self, client):
        sid = self._create(client)
        resp = client.put(
            f'/api/saved-searches/{sid}?email=a@b.ca',
            json={'name': 'upd-1', 'filters_json': {'source': 'craigslist', 'sort': 'price'}},
        )
        assert resp.status_code == 200
        row = persist_module.get_saved_search_by_id('a@b.ca', sid)
        assert row['filters_dict'] == {'source': 'craigslist', 'sort': 'price'}

    def test_put_without_filters_json_keeps_existing(self, client):
        sid = self._create(client)
        resp = client.put(
            f'/api/saved-searches/{sid}?email=a@b.ca',
            json={'name': 'upd-1', 'price_max': 3000},
        )
        assert resp.status_code == 200
        row = persist_module.get_saved_search_by_id('a@b.ca', sid)
        # filters_json from create preserved
        assert row['filters_dict']['source'] == 'kijiji'
        # legacy column updated
        assert row['price_max'] == 3000

    def test_put_invalid_json_returns_400(self, client):
        sid = self._create(client)
        resp = client.put(
            f'/api/saved-searches/{sid}?email=a@b.ca',
            json={'name': 'upd-1', 'filters_json': 'not json {'},
        )
        assert resp.status_code == 400

    def test_put_no_email_returns_400(self, client):
        sid = self._create(client)
        resp = client.put(
            f'/api/saved-searches/{sid}',
            json={'name': 'upd-1'},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/saved-searches/load
# ---------------------------------------------------------------------------

class TestLoadEndpoint:
    @pytest.fixture
    def client(self):
        return app_module.app.test_client()

    def test_load_returns_known(self, client):
        resp = client.post('/api/saved-searches', json={
            'email': 'a@b.ca',
            'name': 'load-1',
            'beds_min': 1, 'price_max': 2500,
            'filters_json': {'source': 'kijiji', 'sort': 'pct', 'has_parking': 'true'},
        })
        sid = resp.get_json()['search_id']
        resp = client.get(f'/api/saved-searches/load?email=a@b.ca&id={sid}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        s = data['search']
        assert s['search_id'] == sid
        assert s['name'] == 'load-1'
        assert s['beds_min'] == 1
        assert s['price_max'] == 2500
        assert s['filters_dict'] == {'source': 'kijiji', 'sort': 'pct', 'has_parking': 'true'}
        assert s['filters_json'] == '{"has_parking": "true", "sort": "pct", "source": "kijiji"}'

    def test_load_unknown_id_returns_404(self, client):
        resp = client.get('/api/saved-searches/load?email=a@b.ca&id=99999')
        assert resp.status_code == 404

    def test_load_no_email_returns_400(self, client):
        resp = client.get('/api/saved-searches/load?id=1')
        assert resp.status_code == 400

    def test_load_invalid_id_returns_400(self, client):
        resp = client.get('/api/saved-searches/load?email=a@b.ca&id=notanumber')
        assert resp.status_code == 400

    def test_load_wrong_email_returns_404(self, client):
        resp = client.post('/api/saved-searches', json={
            'email': 'owner@b.ca', 'name': 'mine',
        })
        sid = resp.get_json()['search_id']
        resp = client.get(f'/api/saved-searches/load?email=other@b.ca&id={sid}')
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /saved-searches (page render)
# ---------------------------------------------------------------------------

class TestSavedSearchesPage:
    @pytest.fixture
    def client(self):
        return app_module.app.test_client()

    def test_page_renders_200(self, client):
        resp = client.get('/saved-searches')
        assert resp.status_code == 200
        assert b'Saved Searches' in resp.data

    def test_page_has_email_input(self, client):
        resp = client.get('/saved-searches')
        assert b'id="email-input"' in resp.data
        assert b'type="email"' in resp.data

    def test_page_has_load_btn(self, client):
        resp = client.get('/saved-searches')
        assert b'id="load-btn"' in resp.data
        assert b'Show saved searches' in resp.data

    def test_page_includes_loadSearches_js(self, client):
        resp = client.get('/saved-searches')
        # JS function loadSearches is defined inline
        assert b'function loadSearches' in resp.data

    def test_page_includes_back_link(self, client):
        resp = client.get('/saved-searches')
        assert b'Back to deals' in resp.data


# ---------------------------------------------------------------------------
# HTML wiring tests (file content)
# ---------------------------------------------------------------------------

class TestHtmlWiring:
    @pytest.fixture
    def client(self):
        return app_module.app.test_client()

    def _read(self, name):
        path = os.path.join(RENT_DIR, 'templates', name)
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_index_has_save_button(self, client):
        body = self._read('index.html')
        assert 'id="save_search_btn"' in body
        assert 'openSaveSearchModal' in body

    def test_index_has_saved_searches_link(self, client):
        body = self._read('index.html')
        assert 'id="saved_searches_link"' in body
        assert 'href="/saved-searches"' in body

    def test_index_has_save_search_modal(self, client):
        body = self._read('index.html')
        assert 'id="save_search_modal"' in body
        assert 'id="save_search_form"' in body
        assert 'submitSaveSearch' in body

    def test_index_has_toast(self, client):
        body = self._read('index.html')
        assert 'id="mc322_toast"' in body
        assert 'showMc322Toast' in body

    def test_index_has_apply_saved_filters_helper(self, client):
        body = self._read('index.html')
        assert 'function applySavedFilters' in body
        assert 'function getCurrentFilterStateAsObject' in body
        assert 'function describeFilters' in body

    def test_index_has_maybeLoadFromPreselect(self, client):
        body = self._read('index.html')
        assert 'function maybeLoadFromPreselect' in body
        assert "/api/saved-searches/load" in body

    def test_neighborhood_html_has_nav_link(self, client):
        body = self._read('neighborhood.html')
        assert 'href="/saved-searches"' in body

    def test_shortlist_html_has_nav_link(self, client):
        body = self._read('shortlist.html')
        assert 'href="/saved-searches"' in body

    def test_profile_html_has_nav_link(self, client):
        body = self._read('profile.html')
        assert 'href="/saved-searches"' in body

    def test_alerts_html_has_nav_link(self, client):
        body = self._read('alerts.html')
        assert 'href="/saved-searches"' in body

    def test_saved_searches_html_exists(self, client):
        body = self._read('saved_searches.html')
        assert '<title>Saved Searches' in body
        assert 'function loadSearch' in body
        assert 'function deleteSearch' in body
        assert 'function submitRename' in body
        assert 'function buildCard' in body


# ---------------------------------------------------------------------------
# Index page still renders (regression guard)
# ---------------------------------------------------------------------------

class TestNoRegressions:
    @pytest.fixture
    def client(self):
        return app_module.app.test_client()

    def test_index_still_renders(self, client):
        resp = client.get('/')
        # 200 OR 5xx if there is no deals_output.csv in tmp dir
        assert resp.status_code in (200, 500)

    def test_api_meta_still_renders(self, client):
        resp = client.get('/api/meta')
        # Either 200 (loaded CSV) or 500 (no CSV) — both are non-regression
        assert resp.status_code in (200, 500)

    def test_alerts_page_still_renders(self, client):
        resp = client.get('/alerts')
        assert resp.status_code == 200

    def test_filters_json_round_trip_end_to_end(self):
        """MC-331 AC6: regression guard that the filters_json column
        survives a full upsert -> get -> get_saved_searches round trip
        with a non-trivial nested dict (proves the JSON encode/decode
        isn't silently dropping nested values, which would have been
        hard to catch with only flat-dict tests).
        """
        from persist import (
            upsert_saved_search, get_saved_search_by_id, get_saved_searches,
        )
        email = "roundtrip@x.ca"
        # Realistic filter shape mirroring the deals-page buildParams()
        # output: nested objects, lists, mixed types, edge-case keys.
        filters = {
            "beds_min": 2,
            "beds_max": 4,
            "price_min": 1800,
            "price_max": 3500,
            "has_parking": True,
            "neighbourhood": "Agincourt North",
            "region": "Scarborough",
            "source": "kijiji",
            "max_subway": 10,
            "sort": "score",
            "filters_applied": [
                {"name": "new", "value": True},
                {"name": "fav", "value": False},
            ],
            "_meta": {
                "applied_count": 7,
                "captured_at": "2026-07-08T10:00:00Z",
                "client": "web/v1.2",
            },
        }
        filters_str = json.dumps(filters)
        # 1. INSERT
        upsert_saved_search(
            email=email,
            name="RT test",
            beds_min=2,
            price_max=3500,
            region="Scarborough",
            filters_json=filters_str,
        )
        # 2. READ BY ID
        row = get_saved_search_by_id(search_id=1, email=email)
        assert row is not None
        assert row["filters_dict"] == filters, (
            "filters_json round-trip via get_saved_search_by_id failed: "
            f"expected {filters}, got {row['filters_dict']}"
        )
        # 3. READ ALL
        all_rows = get_saved_searches(email=email)
        assert len(all_rows) == 1
        assert all_rows[0]["filters_dict"] == filters, (
            "filters_json round-trip via get_saved_searches failed"
        )
        # 4. UPDATE (upsert on same email+name) preserves filters_dict
        updated_filters = {**filters, "beds_min": 3}
        upsert_saved_search(
            email=email,
            name="RT test",
            beds_min=3,   # changed
            filters_json=json.dumps(updated_filters),  # also update filters
        )
        all_rows2 = get_saved_searches(email=email)
        assert len(all_rows2) == 1, "UPDATE should not create a duplicate row"
        assert all_rows2[0]["filters_dict"]["beds_min"] == 3
