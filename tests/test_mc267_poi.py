"""
Tests for MC-267: POI proximity — nearest grocery store + walk time.
Covers: poi.py module + app.py grocery enrichment + _compute_cautions() with grocery caution.
"""

import json, os, pytest
from unittest.mock import patch, MagicMock

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, 'data')
NEIGHBOURHOODS_JSON = os.path.join(DATA_DIR, 'toronto_neighbourhoods.json')

# ── Helpers ───────────────────────────────────────────────────────────────────

def _poi_cache_path():
    return os.path.join(DATA_DIR, 'poi_cache.json')


def _sample_cache():
    return {
        "Annex|supermarket": {
            "store_name": "No Frills",
            "store_type": "supermarket",
            "distance_m": 650,
            "walk_minutes": 8,
            "store_lat": 43.6711,
            "store_lng": -79.4144,
            "source": "overpass"
        },
        "High Park-Swansea|supermarket": None,  # no store nearby
        "Downtown Toronto|supermarket": {
            "store_name": "Loblaws",
            "store_type": "supermarket",
            "distance_m": 420,
            "walk_minutes": 5,
            "store_lat": 43.6486,
            "store_lng": -79.3978,
            "source": "overpass"
        },
        "Beaches|supermarket": {
            "store_name": "Metro",
            "store_type": "supermarket",
            "distance_m": 900,
            "walk_minutes": 12,
            "store_lat": 43.6629,
            "store_lng": -79.3923,
            "source": "overpass"
        }
    }


# ── MC-267: poi.py unit tests ─────────────────────────────────────────────────

class TestPoiModule:
    """poi.py: Overpass query, cache, walk time estimation."""

    def test_haversine_m_converts_to_metres(self):
        from poi import _haversine_m
        # Toronto to itself = 0
        assert _haversine_m(43.6486, -79.3978, 43.6486, -79.3978) == 0
        # Known distance: two points ~420m apart (Bay & Front St area)
        dist = _haversine_m(43.6500, -79.4000, 43.6535, -79.4000)
        assert 300 < dist < 450  # ~390m

    def test_ors_walk_time_fallback(self):
        from poi import _walk_time_fallback
        # ~390m at 83m/min ≈ 4.7 min
        t = _walk_time_fallback(43.6500, -79.4000, 43.6535, -79.4000)
        assert 4 <= t <= 6

    @patch('requests.get')
    def test_overpass_returns_sorted_results(self, mock_get):
        from poi import _overpass_query
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "elements": [
                {"type": "node", "id": 1, "lat": 43.6486, "lon": -79.3978,
                 "tags": {"name": "Loblaws"}},
                {"type": "node", "id": 2, "lat": 43.6550, "lon": -79.4000,
                 "tags": {"name": "No Frills"}},
            ]
        }
        mock_get.return_value = mock_resp

        results = _overpass_query(43.65, -79.40, overpass_tag="amenity=supermarket")
        assert len(results) == 2
        assert results[0]['name'] == 'Loblaws'  # closer
        assert results[1]['name'] == 'No Frills'

    def test_cache_save_and_load(self, tmp_path):
        from poi import _load_cache, _save_cache
        # Use tmp_path for isolation
        test_cache_file = tmp_path.joinpath('poi_cache.json')
        import poi
        original_path = poi.CACHE_PATH
        poi.CACHE_PATH = str(test_cache_file)

        test_data = {"Annex|supermarket": {"store_name": "No Frills", "walk_minutes": 8}}
        _save_cache(test_data)
        loaded = _load_cache()
        assert loaded == test_data

        poi.CACHE_PATH = original_path

    @patch('requests.get')
    def test_overpass_strips_nodes_without_name(self, mock_get):
        from poi import _overpass_query
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "elements": [
                {"type": "node", "id": 1, "lat": 43.6486, "lon": -79.3978,
                 "tags": {}},  # no name — should be skipped
                {"type": "node", "id": 2, "lat": 43.6550, "lon": -79.4000,
                 "tags": {"name": "Metro"}},
            ]
        }
        mock_get.return_value = mock_resp
        results = _overpass_query(43.65, -79.40, overpass_tag="amenity=supermarket")
        assert len(results) == 1
        assert results[0]['name'] == 'Metro'


# ── MC-267: app.py grocery enrichment ─────────────────────────────────────────

class TestGroceryEnrichment:
    """_normalize_row enriches deal with grocery_* fields from poi_cache."""

    @pytest.fixture(autouse=True)
    def setup_cache(self, tmp_path):
        self.cache_path = tmp_path.joinpath('poi_cache.json')
        test_cache = _sample_cache()
        with open(self.cache_path, 'w', encoding='utf-8') as f:
            json.dump(test_cache, f)
        # Patch DATA_DIR in app module so _load_poi_cache() reads our temp cache
        import app
        self._orig_data_dir = app.DATA_DIR
        app.DATA_DIR = str(tmp_path)
        yield
        app.DATA_DIR = self._orig_data_dir

    def test_normalize_row_includes_grocery_fields(self):
        from app import _normalize_row
        row = {
            'neighborhood': 'Annex',
            'region': 'Downtown',
            'price': 1800,
            'beds': 1,
            'baths': 1,
            'url': 'http://example.com/1',
        }
        d = _normalize_row(row)
        assert d['grocery_name'] == 'No Frills'
        assert d['grocery_walk_min'] == 8
        assert d['grocery_dist_m'] == 650

    def test_normalize_row_grocery_none_for_unknown_neighbourhood(self):
        from app import _normalize_row
        row = {
            'neighborhood': 'UnknownNeighbourhoodXYZ',
            'region': 'Downtown',
            'price': 1800,
            'beds': 1,
            'baths': 1,
            'url': 'http://example.com/1',
        }
        d = _normalize_row(row)
        assert d['grocery_name'] is None
        assert d['grocery_walk_min'] is None
        assert d['grocery_dist_m'] is None

    def test_normalize_row_grocery_null_for_no_store(self):
        from app import _normalize_row
        row = {
            'neighborhood': 'High Park-Swansea',
            'region': 'West End',
            'price': 2000,
            'beds': 2,
            'baths': 1,
            'url': 'http://example.com/2',
        }
        d = _normalize_row(row)
        assert d['grocery_name'] is None
        assert d['grocery_walk_min'] is None


# ── MC-267: grocery caution ────────────────────────────────────────────────────

class TestGroceryCaution:
    """Listings with no grocery within 20 min walk get a caution."""

    def test_caution_when_walk_time_over_threshold(self):
        from app import _compute_cautions, MAX_GROCERY_WALK_MIN
        d = {
            'pct_under': 10,
            'days_ago': 5,
            'sqft': '650',
            'price': 2000,
            'beds': 2,
            'region': 'Downtown',
            'grocery_name': 'Food Basics',
            'grocery_walk_min': 25,  # > 20 min
        }
        cautions = _compute_cautions(d)
        assert any('No grocery store nearby' in c for c in cautions)

    def test_no_caution_when_store_nearby(self):
        from app import _compute_cautions
        d = {
            'pct_under': 10,
            'days_ago': 5,
            'sqft': '650',
            'price': 2000,
            'beds': 2,
            'region': 'Downtown',
            'grocery_name': 'Loblaws',
            'grocery_walk_min': 5,
        }
        cautions = _compute_cautions(d)
        assert not any('No grocery store nearby' in c for c in cautions)

    def test_no_caution_when_no_grocery_field(self):
        from app import _compute_cautions
        d = {
            'pct_under': 10,
            'days_ago': 5,
            'sqft': '650',
            'price': 2000,
            'beds': 2,
            'region': 'Downtown',
        }
        cautions = _compute_cautions(d)
        assert not any('No grocery store nearby' in c for c in cautions)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
