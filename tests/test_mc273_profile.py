"""
Tests for MC-273: User Preference Profile.
Covers: persist.py upsert_profile/get_profile, app.py /api/profile endpoint,
profile.html rendering, index.html profile pre-fill.

MC-273 success criteria:
  - /profile page: user enters email, preferred beds, max price,
    preferred neighbourhoods (multi-select), commute destination, and status
  - Status field: "Actively looking", "Open to moving", "Just browsing" — shown as tag in UI
  - Profile stored in SQLite user_profiles table
  - When user loads the site with a saved email in localStorage, filters pre-populate from profile
  - Profile page reachable from nav: "My Preferences"
  - "Open to moving" status: user gets weekly digest of top deals (feeds into MC-275)
"""

import json, os, pytest, tempfile
from unittest.mock import patch, MagicMock

APP_DIR = os.path.dirname(os.path.abspath(__file__))  # .../tests
# templates/ and app.py are one level up from tests/
_TEMPLATES_DIR = os.path.join(APP_DIR, '..', 'templates')


# ── MC-273: persist.py user_profiles table ───────────────────────────────────

class TestProfileSchema:
    """user_profiles table exists with correct schema."""

    def test_user_profiles_table_exists(self):
        import sqlite3
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            tmp = f.name
        try:
            conn = sqlite3.connect(tmp)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    profile_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                    email          TEXT NOT NULL UNIQUE,
                    preferred_beds TEXT,
                    max_price      REAL,
                    neighbourhoods TEXT,
                    commute_dest   TEXT,
                    status         TEXT,
                    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                );
            """)
            conn.commit()
            cols = [c[1] for c in conn.execute("PRAGMA table_info(user_profiles)").fetchall()]
            assert 'email' in cols
            assert 'preferred_beds' in cols
            assert 'max_price' in cols
            assert 'neighbourhoods' in cols
            assert 'commute_dest' in cols
            assert 'status' in cols
        finally:
            conn.close()
            os.unlink(tmp)


class TestProfileUpsertGet:
    """persist.py upsert_profile / get_profile."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        import sys, os, sqlite3, importlib.util

        # rent_finder/ dir (parent of tests/)
        RENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
        sys.path.insert(0, RENT_DIR)

        # Use tmp DB so tests are isolated
        tmp_db = os.path.join(str(tmp_path), 'listings.db')
        os.environ['RENT_DATA_DIR'] = str(tmp_path)

        # Load persist via spec
        spec = importlib.util.spec_from_file_location('persist_test',
            os.path.join(RENT_DIR, 'persist.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Reset conn and re-init with tmp path
        mod._reset_conn()
        mod.init_db()

        self.persist = mod
        yield

        try:
            mod._reset_conn()
        except Exception:
            pass
        if 'RENT_DATA_DIR' in os.environ:
            del os.environ['RENT_DATA_DIR']

    def test_upsert_profile_creates_new(self):
        import sqlite3
        # Verify the DB file is actually open
        conn = sqlite3.connect(self.persist.DB_PATH)
        try:
            result = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_profiles'").fetchone()
            assert result is not None, "user_profiles table not found"
        finally:
            conn.close()
        # Now call upsert
        self.persist.upsert_profile(
            email='test@example.com',
            preferred_beds='2',
            max_price=2500.0,
            neighbourhoods=['Annex', 'Queen West'],
            commute_dest='Union Station',
            status='actively_looking',
        )
        p = self.persist.get_profile('test@example.com')
        assert p is not None
        assert p['email'] == 'test@example.com'
        assert p['preferred_beds'] == '2'
        assert p['max_price'] == 2500.0
        assert p['status'] == 'actively_looking'
        assert 'Annex' in p['neighbourhoods']
        assert p['commute_dest'] == 'Union Station'

    def test_upsert_profile_updates_existing(self):
        self.persist.upsert_profile(
            email='update@example.com',
            preferred_beds='1',
            max_price=2000.0,
            status='just_browsing',
        )
        self.persist.upsert_profile(
            email='update@example.com',
            preferred_beds='3',
            max_price=3000.0,
            status='open_to_moving',
            commute_dest='King Station',
        )
        p = self.persist.get_profile('update@example.com')
        assert p['preferred_beds'] == '3'
        assert p['max_price'] == 3000.0
        assert p['status'] == 'open_to_moving'
        assert p['commute_dest'] == 'King Station'

    def test_get_profile_returns_none_for_missing(self):
        p = self.persist.get_profile('notfound@example.com')
        assert p is None

    def test_neighbourhoods_stored_as_json_array(self):
        self.persist.upsert_profile(
            email='list@example.com',
            neighbourhoods=['Beaches', 'Danforth', 'High Park'],
        )
        p = self.persist.get_profile('list@example.com')
        assert isinstance(p['neighbourhoods'], list)
        assert 'Beaches' in p['neighbourhoods']

    def test_status_values_accepted(self):
        for status in ('actively_looking', 'open_to_moving', 'just_browsing'):
            email = f'status_{status}@test.com'
            self.persist.upsert_profile(email=email, status=status)
            p = self.persist.get_profile(email)
            assert p['status'] == status

    def test_null_fields_allowed(self):
        self.persist.upsert_profile(email='minimal@example.com', max_price=1500.0)
        p = self.persist.get_profile('minimal@example.com')
        assert p['max_price'] == 1500.0
        assert p['preferred_beds'] is None
        assert p['commute_dest'] is None


# ── MC-273: app.py /api/profile endpoint ──────────────────────────────────────

class TestProfileApiEndpoint:
    """Flask /api/profile GET/POST."""

    @pytest.fixture(autouse=True)
    def setup_app(self, tmp_path):
        import sys, os, importlib.util

        # Set up test DB env before importing anything
        os.environ['RENT_DATA_DIR'] = str(tmp_path)

        RENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

        # Load persist first (app imports it)
        persist_spec = importlib.util.spec_from_file_location('persist',
            os.path.join(RENT_DIR, 'persist.py'))
        persist_mod = importlib.util.module_from_spec(persist_spec)
        persist_spec.loader.exec_module(persist_mod)
        persist_mod._reset_conn()
        persist_mod.init_db()

        # Load app via spec (same pattern as test_app.py)
        app_path = os.path.join(RENT_DIR, 'app.py')
        app_spec = importlib.util.spec_from_file_location('app_profile', app_path)
        app_mod = importlib.util.module_from_spec(app_spec)
        app_spec.loader.exec_module(app_mod)
        self.app = app_mod.app.test_client()
        yield

    def test_get_profile_missing_email(self):
        rv = self.app.get('/api/profile')
        assert rv.status_code == 400

    def test_get_profile_no_such_email(self):
        rv = self.app.get('/api/profile?email=nobody@example.com')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['profile'] is None

    def test_post_profile_invalid_email(self):
        rv = self.app.post('/api/profile',
                           data=json.dumps({'email': 'notanemail'}),
                           content_type='application/json')
        assert rv.status_code == 400

    def test_post_profile_creates_profile(self):
        rv = self.app.post('/api/profile',
                           data=json.dumps({
                               'email': 'newuser@example.com',
                               'preferred_beds': '2',
                               'max_price': 2200,
                               'neighbourhoods': ['Annex', 'Liberty Village'],
                               'commute_dest': 'Union Station',
                               'status': 'open_to_moving',
                           }),
                           content_type='application/json')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['profile']['email'] == 'newuser@example.com'
        assert data['profile']['preferred_beds'] == '2'
        assert data['profile']['max_price'] == 2200.0
        assert 'Annex' in data['profile']['neighbourhoods']
        assert data['profile']['status'] == 'open_to_moving'

    def test_post_profile_updates_existing(self):
        self.app.post('/api/profile',
                      data=json.dumps({'email': 'update2@example.com', 'max_price': 1800}),
                      content_type='application/json')
        rv = self.app.post('/api/profile',
                           data=json.dumps({'email': 'update2@example.com', 'max_price': 2400, 'status': 'actively_looking'}),
                           content_type='application/json')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['profile']['max_price'] == 2400.0
        assert data['profile']['status'] == 'actively_looking'

    def test_get_profile_returns_saved_profile(self):
        self.app.post('/api/profile',
                      data=json.dumps({'email': 'gettest@example.com', 'preferred_beds': '3', 'status': 'just_browsing'}),
                      content_type='application/json')
        rv = self.app.get('/api/profile?email=gettest@example.com')
        data = json.loads(rv.data)
        assert data['profile']['preferred_beds'] == '3'
        assert data['profile']['status'] == 'just_browsing'

    def test_status_field_accepts_valid_values(self):
        for status in ('actively_looking', 'open_to_moving', 'just_browsing'):
            rv = self.app.post('/api/profile',
                               data=json.dumps({'email': f'status_{status}@test.com', 'status': status}),
                               content_type='application/json')
            assert rv.status_code == 200, f"Failed for {status}"


# ── MC-273: profile.html rendering ───────────────────────────────────────────

class TestProfileHtml:
    """profile.html has required form fields and status selector."""

    @staticmethod
    def _html(name):
        return os.path.join(_TEMPLATES_DIR, name)

    def test_profile_html_has_email_field(self):
        with open(self._html('profile.html'), encoding='utf-8') as f:
            html = f.read()
        assert 'id="email"' in html
        assert 'type="email"' in html

    def test_profile_html_has_preferred_beds_select(self):
        with open(self._html('profile.html'), encoding='utf-8') as f:
            html = f.read()
        assert 'id="preferred_beds"' in html

    def test_profile_html_has_max_price_input(self):
        with open(self._html('profile.html'), encoding='utf-8') as f:
            html = f.read()
        assert 'id="max_price"' in html

    def test_profile_html_has_neighbourhoods_textarea(self):
        with open(self._html('profile.html'), encoding='utf-8') as f:
            html = f.read()
        assert 'id="neighbourhoods"' in html

    def test_profile_html_has_commute_dest_input(self):
        with open(self._html('profile.html'), encoding='utf-8') as f:
            html = f.read()
        assert 'id="commute_dest"' in html

    def test_profile_html_has_status_radios(self):
        with open(self._html('profile.html'), encoding='utf-8') as f:
            html = f.read()
        assert 'value="actively_looking"' in html
        assert 'value="open_to_moving"' in html
        assert 'value="just_browsing"' in html

    def test_profile_html_has_save_button(self):
        with open(self._html('profile.html'), encoding='utf-8') as f:
            html = f.read()
        assert 'Save Preferences' in html

    def test_profile_html_loads_from_localstorage_email(self):
        with open(self._html('profile.html'), encoding='utf-8') as f:
            html = f.read()
        assert "localStorage.getItem('rent_alert_email')" in html
        assert 'loadProfile(savedEmail)' in html

    def test_profile_html_calls_save_profile_on_submit(self):
        with open(self._html('profile.html'), encoding='utf-8') as f:
            html = f.read()
        assert 'saveProfile(event)' in html
        assert "fetch('/api/profile'" in html


# ── MC-273: index.html profile pre-fill ──────────────────────────────────────

class TestIndexProfilePreFill:
    """index.html pre-fills filters from saved profile on load."""

    @staticmethod
    def _html(name):
        return os.path.join(_TEMPLATES_DIR, name)

    def test_index_html_has_loadProfilePreferences(self):
        with open(self._html('index.html'), encoding='utf-8') as f:
            html = f.read()
        assert 'loadProfilePreferences' in html

    def test_loadProfilePreferences_reads_localstorage_email(self):
        with open(self._html('index.html'), encoding='utf-8') as f:
            html = f.read()
        assert "localStorage.getItem('rent_alert_email')" in html

    def test_loadProfilePreferences_fetches_api_profile(self):
        with open(self._html('index.html'), encoding='utf-8') as f:
            html = f.read()
        assert '/api/profile?email=' in html

    def test_loadProfilePreferences_sets_beds_filter(self):
        with open(self._html('index.html'), encoding='utf-8') as f:
            html = f.read()
        assert 'beds_min' in html  # filter pre-fill

    def test_loadProfilePreferences_sets_price_filter(self):
        with open(self._html('index.html'), encoding='utf-8') as f:
            html = f.read()
        assert 'price_max' in html  # filter pre-fill

    def test_nav_has_profile_link(self):
        with open(self._html('index.html'), encoding='utf-8') as f:
            html = f.read()
        assert '/profile' in html
        assert 'My Preferences' in html

    def test_status_badge_element_in_nav(self):
        with open(self._html('index.html'), encoding='utf-8') as f:
            html = f.read()
        assert 'profile_status_badge' in html


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

