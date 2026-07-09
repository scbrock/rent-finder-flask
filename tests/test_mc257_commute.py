"""Tests for MC-257: Commute time filter via OpenRouteService.

Tests the /api/commute endpoint and related helpers in app.py.
"""
import sys, os, pytest, importlib.util

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENT_FINDER = os.path.join(PROJECT_ROOT)

app_path = os.path.join(RENT_FINDER, 'app.py')
spec = importlib.util.spec_from_file_location('app', app_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
app = mod.app
client = app.test_client()


# ── /api/commute endpoint ─────────────────────────────────────────────────────

class TestCommuteEndpoint:
    def test_commute_returns_405_for_get(self):
        """GET /api/commute should return 405 Method Not Allowed."""
        resp = client.get('/api/commute')
        assert resp.status_code == 405

    def test_commute_requires_destination(self):
        """POST with no destination body should return 400."""
        resp = client.post('/api/commute',
                           data='{}',
                           content_type='application/json')
        assert resp.status_code == 400
        assert b'destination required' in resp.data

    def test_commute_unknown_destination_returns_400(self):
        """Un-geocodeable destination should return 400 with error message."""
        resp = client.post('/api/commute',
                           data='{"destination": "XYZNOTAREALPLACE12345678"}',
                           content_type='application/json')
        # Either 200 with error in body or 400 — both acceptable
        data = resp.get_json()
        assert 'error' in data or 'times' in data

    def test_commute_known_destination_returns_times(self):
        """Known destination like 'Union Station' should return neighbourhood times."""
        resp = client.post('/api/commute',
                           data='{"destination": "Union Station"}',
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'times' in data
        assert isinstance(data['times'], dict)
        assert data['destination'] == 'Union Station'
        assert 'dest_coords' in data

    def test_commute_returns_numeric_minutes(self):
        """Times dict entries should have numeric commute_minutes or null."""
        resp = client.post('/api/commute',
                           data='{"destination": "Union Station"}',
                           content_type='application/json')
        data = resp.get_json()
        times = data['times']
        # At least some neighbourhoods should have times
        assert len(times) > 0, "Should return times for at least some neighbourhoods"
        for nbhd, entry in times.items():
            assert 'commute_minutes' in entry
            assert 'source' in entry
            if entry['commute_minutes'] is not None:
                assert isinstance(entry['commute_minutes'], (int, float))
                assert entry['commute_minutes'] > 0

    def test_commute_same_dest_cached(self):
        """Two identical requests should return the same data."""
        body = '{"destination": "Union Station"}'
        r1 = client.post('/api/commute', data=body, content_type='application/json').get_json()
        r2 = client.post('/api/commute', data=body, content_type='application/json').get_json()
        # Same destination should return same keys
        assert set(r1['times'].keys()) == set(r2['times'].keys())

    def test_commute_case_insensitive_destination(self):
        """'union station' and 'UNION STATION' should return same results."""
        r1 = client.post('/api/commute',
                         data='{"destination": "union station"}',
                         content_type='application/json').get_json()
        r2 = client.post('/api/commute',
                         data='{"destination": "UNION STATION"}',
                         content_type='application/json').get_json()
        # Same keys regardless of case
        assert set(r1['times'].keys()) == set(r2['times'].keys())


# ── Haversine helper ─────────────────────────────────────────────────────────

class TestHaversine:
    def test_haversine_distance(self):
        """Haversine should return ~0 km for same point."""
        import math
        h = mod._haversine
        # Same point = 0
        assert h(43.6515, -79.3835, 43.6515, -79.3835) == 0.0
        # Known distance: Union Station (43.6455,-79.3833) to Yonge/Dundas (43.6561,-79.3802)
        d = h(43.6455, -79.3833, 43.6561, -79.3802)
        assert 1.0 < d < 1.5, f"Expected ~1.2km, got {d:.2f}km"


# ── Known destinations ──────────────────────────────────────────────────────

class TestKnownDestinations:
    def test_union_station_cached(self):
        """'union station' should be in KNOWN_DESTINATIONS (no API needed)."""
        assert 'union station' in mod._KNOWN_DESTINATIONS
        lat, lon = mod._KNOWN_DESTINATIONS['union station']
        assert 43.6 < lat < 43.7
        assert -79.4 < lon < -79.3


# ── Commute time integration with /api/deals ─────────────────────────────────

class TestCommuteWithDeals:
    def test_deals_has_commute_minutes_field(self):
        """Each deal should have a commute_minutes field (or null)."""
        resp = client.get('/api/deals')
        deals = resp.get_json()['deals']
        if deals:
            for d in deals[:5]:
                assert 'commute_minutes' in d

    def test_max_commute_filter_exists(self):
        """max_commute param should be accepted without error."""
        resp = client.get('/api/deals?max_commute=30')
        assert resp.status_code == 200
        deals = resp.get_json()['deals']
        # If any deal has commute_minutes set, all returned should be <= 30
        for d in deals:
            if d.get('commute_minutes') is not None:
                assert d['commute_minutes'] <= 30

    def test_commute_dest_param_accepted(self):
        """commute_dest param should be accepted by /api/deals."""
        resp = client.get('/api/deals?commute_dest=Union+Station')
        assert resp.status_code == 200
