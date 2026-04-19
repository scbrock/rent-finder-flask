"""
Tests for MC-268: POI proximity — nearest gym when listing has no in-building gym.
Covers: poi.py gym query (leisure=fitness_centre), app.py gym enrichment + conditional display,
_caution when gym > 30 min walk.

MC-268 success criteria:
  - Gym proximity only shown when listing has no in-building gym (has_gym=False)
  - Overpass query uses leisure=fitness_centre tag
  - station_name and station_walk_min added to deal dict by _normalize_row
  - Caution "No gym nearby (none in building)" when gym_walk_min > 30
  - index.html renders gym walk time only for listings with has_gym=False
"""

import json, os, pytest
from unittest.mock import patch, MagicMock

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, 'data')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sample_gym_cache():
    return {
        "Annex|fitness_centre": {
            "store_name": "GoodLife Fitness Toronto Annex",
            "poi_type": "fitness_centre",
            "distance_m": 650,
            "walk_minutes": 8,
            "store_lat": 43.6711,
            "store_lng": -79.4144,
            "source": "overpass"
        },
        "High Park-Swansea|fitness_centre": None,  # no gym within threshold
        "Downtown Toronto|fitness_centre": {
            "store_name": "Planet Fitness Toronto",
            "poi_type": "fitness_centre",
            "distance_m": 420,
            "walk_minutes": 5,
            "store_lat": 43.6486,
            "store_lng": -79.3978,
            "source": "overpass"
        },
        "Beaches|fitness_centre": {
            "store_name": "Beaches Gym",
            "poi_type": "fitness_centre",
            "distance_m": 1100,
            "walk_minutes": 14,
            "store_lat": 43.6629,
            "store_lng": -79.3923,
            "source": "overpass"
        }
    }


# ── MC-268: poi.py gym query ───────────────────────────────────────────────────

class TestGymQuery:
    """poi.py: Overpass query uses leisure=fitness_centre tag for gyms."""

    @patch('requests.get')
    def test_overpass_uses_leisure_fitness_tag(self, mock_get):
        from poi import _overpass_query
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "elements": [
                {"type": "node", "id": 1, "lat": 43.6711, "lon": -79.4144,
                 "tags": {"name": "GoodLife Fitness Toronto Annex", "leisure": "fitness_centre"}},
            ]
        }
        mock_get.return_value = mock_resp

        results = _overpass_query(43.65, -79.40, overpass_tag="leisure=fitness_centre")
        assert len(results) == 1
        assert results[0]['name'] == 'GoodLife Fitness Toronto Annex'

        call_args = mock_get.call_args
        query = call_args.kwargs['params']['data']
        # Overpass QL for leisure=fitness_centre
        assert 'leisure' in query
        assert 'amenity=' not in query

    @patch('requests.get')
    def test_overpass_gym_skips_unnamed(self, mock_get):
        from poi import _overpass_query
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "elements": [
                {"type": "node", "id": 1, "lat": 43.6711, "lon": -79.4144,
                 "tags": {}},  # no name — skip
                {"type": "node", "id": 2, "lat": 43.6700, "lon": -79.4100,
                 "tags": {"name": "Fit4Less"}},
            ]
        }
        mock_get.return_value = mock_resp
        results = _overpass_query(43.65, -79.40, overpass_tag="leisure=fitness_centre")
        assert len(results) == 1
        assert results[0]['name'] == 'Fit4Less'

    @patch('requests.get')
    def test_overpass_gym_returns_sorted_by_distance(self, mock_get):
        from poi import _overpass_query
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "elements": [
                {"type": "node", "id": 1, "lat": 43.6700, "lon": -79.4050,
                 "tags": {"name": "GoodLife Yonge"}},
                {"type": "node", "id": 2, "lat": 43.6400, "lon": -79.4200,
                 "tags": {"name": "Planet Fitness Dundas"}},
            ]
        }
        mock_get.return_value = mock_resp
        results = _overpass_query(43.65, -79.40, overpass_tag="leisure=fitness_centre")
        assert len(results) == 2
        # Sorted by distance to (43.65, -79.40): Planet Fitness is ~1.68km, GoodLife is ~2.23km
        assert results[0]['name'] == 'Planet Fitness Dundas'


# ── MC-268: app.py gym enrichment ─────────────────────────────────────────────

class TestGymEnrichment:
    """_normalize_row enriches deal with gym_* fields from poi_cache."""

    @pytest.fixture(autouse=True)
    def setup_cache(self, tmp_path):
        self.cache_path = tmp_path.joinpath('poi_cache.json')
        test_cache = _sample_gym_cache()
        with open(self.cache_path, 'w', encoding='utf-8') as f:
            json.dump(test_cache, f)
        import app
        self._orig_data_dir = app.DATA_DIR
        app.DATA_DIR = str(tmp_path)
        yield
        app.DATA_DIR = self._orig_data_dir

    def test_normalize_row_includes_gym_fields(self):
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
        assert d['gym_name'] == 'GoodLife Fitness Toronto Annex'
        assert d['gym_walk_min'] == 8

    def test_normalize_row_gym_none_for_unknown_neighbourhood(self):
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
        assert d['gym_name'] is None
        assert d['gym_walk_min'] is None

    def test_normalize_row_gym_null_when_no_gym_cached(self):
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
        # cached None means no gym found within threshold
        assert d['gym_name'] is None
        assert d['gym_walk_min'] is None


# ── MC-268: gym caution ───────────────────────────────────────────────────────

class TestGymCaution:
    """Listings with no gym within 30 min walk get a caution."""

    def test_caution_when_gym_walk_over_30_min(self):
        from app import _compute_cautions, MAX_GYM_WALK_MIN
        d = {
            'pct_under': 10,
            'days_ago': 5,
            'sqft': '650',
            'price': 2000,
            'beds': 2,
            'region': 'Downtown',
            'has_gym': False,
            'gym_name': 'GoodLife',
            'gym_walk_min': 35,  # > 30 min threshold
        }
        cautions = _compute_cautions(d)
        assert any('No gym nearby (none in building)' in c for c in cautions)

    def test_no_caution_when_gym_nearby(self):
        from app import _compute_cautions
        d = {
            'pct_under': 10,
            'days_ago': 5,
            'sqft': '650',
            'price': 2000,
            'beds': 2,
            'region': 'Downtown',
            'has_gym': False,
            'gym_name': 'GoodLife',
            'gym_walk_min': 8,  # within 30 min
        }
        cautions = _compute_cautions(d)
        assert not any('No gym nearby (none in building)' in c for c in cautions)

    def test_no_caution_when_building_has_gym(self):
        from app import _compute_cautions
        d = {
            'pct_under': 10,
            'days_ago': 5,
            'sqft': '650',
            'price': 2000,
            'beds': 2,
            'region': 'Downtown',
            'has_gym': True,  # has in-building gym
            'gym_name': None,
            'gym_walk_min': None,
        }
        cautions = _compute_cautions(d)
        assert not any('No gym nearby (none in building)' in c for c in cautions)

    def test_no_caution_when_no_gym_field(self):
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
        assert not any('No gym nearby (none in building)' in c for c in cautions)

    def test_caution_only_when_listing_has_no_inbuilding_gym(self):
        from app import _compute_cautions, MAX_GYM_WALK_MIN
        d = {
            'pct_under': 10,
            'days_ago': 5,
            'sqft': '650',
            'price': 2000,
            'beds': 2,
            'region': 'Downtown',
            'has_gym': True,  # has in-building gym
            'gym_walk_min': 35,  # far from nearest gym — should still NOT trigger
                                 # because conditional on has_gym=False
        }
        cautions = _compute_cautions(d)
        assert not any('No gym nearby (none in building)' in c for c in cautions)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])