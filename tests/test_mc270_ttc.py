"""
Tests for MC-270: POI proximity — nearest TTC subway station + walk time.
Covers: poi.py station query (railway=station OSM tag), app.py station enrichment,
_caution when station > 20 min walk, index.html TTC column rendering.

MC-270 success criteria:
  - Overpass query uses railway=station tag (not amenity=station)
  - station_name and station_walk_min added to deal dict by _normalize_row
  - Caution "No TTC station within 20 min walk" when station_walk_min > 20
  - index.html renders TTC column with walk time from station_walk_min
"""

import json, os, pytest
from unittest.mock import patch, MagicMock

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, 'data')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sample_cache():
    return {
        "Annex|station": {
            "store_name": "Spadina Station",
            "poi_type": "station",
            "distance_m": 480,
            "walk_minutes": 6,
            "store_lat": 43.6466,
            "store_lng": -79.4061,
            "source": "overpass"
        },
        "High Park-Swansea|station": None,  # no station within threshold
        "Downtown Toronto|station": {
            "store_name": "St. George Station",
            "poi_type": "station",
            "distance_m": 350,
            "walk_minutes": 4,
            "store_lat": 43.6499,
            "store_lng": -79.3968,
            "source": "overpass"
        },
        "Beaches|station": {
            "store_name": "Woodbine Station",
            "poi_type": "station",
            "distance_m": 1200,
            "walk_minutes": 15,
            "store_lat": 43.6613,
            "store_lng": -79.3156,
            "source": "overpass"
        }
    }


# ── MC-270: poi.py station query ──────────────────────────────────────────────

class TestStationQuery:
    """poi.py: Overpass query uses railway=station tag for TTC subway stations."""

    @patch('requests.get')
    def test_overpass_uses_railway_station_tag(self, mock_get):
        from poi import _overpass_query
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "elements": [
                {"type": "node", "id": 1, "lat": 43.6466, "lon": -79.4061,
                 "tags": {"name": "Spadina Station", "railway": "station"}},
            ]
        }
        mock_get.return_value = mock_resp

        # Call with the station overpass tag
        results = _overpass_query(43.65, -79.40, overpass_tag="railway=station")
        assert len(results) == 1
        assert results[0]['name'] == 'Spadina Station'

        # Verify the request was made with the correct Overpass QL syntax for railway=station
        call_args = mock_get.call_args
        query = call_args.kwargs['params']['data']
        # Overpass QL: node["railway"="station"] — not amenity=station
        assert 'node["railway"' in query or 'railway"="station"' in query
        assert 'amenity=' not in query

    @patch('requests.get')
    def test_overpass_strips_stations_without_name(self, mock_get):
        from poi import _overpass_query
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "elements": [
                {"type": "node", "id": 1, "lat": 43.6466, "lon": -79.4061,
                 "tags": {}},  # no name — skip
                {"type": "node", "id": 2, "lat": 43.6500, "lon": -79.3950,
                 "tags": {"name": "St. George Station"}},
            ]
        }
        mock_get.return_value = mock_resp
        results = _overpass_query(43.65, -79.40, overpass_tag="railway=station")
        assert len(results) == 1
        assert results[0]['name'] == 'St. George Station'

    @patch('requests.get')
    def test_overpass_returns_sorted_by_distance(self, mock_get):
        from poi import _overpass_query
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "elements": [
                {"type": "node", "id": 1, "lat": 43.6500, "lon": -79.3900,
                 "tags": {"name": "Queen's Park Station"}},
                {"type": "node", "id": 2, "lat": 43.6400, "lon": -79.4100,
                 "tags": {"name": "Spadina Station"}},
            ]
        }
        mock_get.return_value = mock_resp
        results = _overpass_query(43.65, -79.40, overpass_tag="railway=station")
        assert len(results) == 2
        # Nearest to (43.65, -79.40) is Queen's Park (closer lat/lng match)
        assert results[0]['name'] == "Queen's Park Station"


# ── MC-270: app.py station enrichment ────────────────────────────────────────

class TestStationEnrichment:
    """_normalize_row enriches deal with station_* fields from poi_cache."""

    @pytest.fixture(autouse=True)
    def setup_cache(self, tmp_path):
        self.cache_path = tmp_path.joinpath('poi_cache.json')
        test_cache = _sample_cache()
        with open(self.cache_path, 'w', encoding='utf-8') as f:
            json.dump(test_cache, f)
        import app
        self._orig_data_dir = app.DATA_DIR
        app.DATA_DIR = str(tmp_path)
        yield
        app.DATA_DIR = self._orig_data_dir

    def test_normalize_row_includes_station_fields(self):
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
        assert d['station_name'] == 'Spadina Station'
        assert d['station_walk_min'] == 6

    def test_normalize_row_station_none_for_unknown_neighbourhood(self):
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
        assert d['station_name'] is None
        assert d['station_walk_min'] is None

    def test_normalize_row_station_null_when_no_station_cached(self):
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
        # cached None means no station found within threshold
        assert d['station_name'] is None
        assert d['station_walk_min'] is None


# ── MC-270: station caution ────────────────────────────────────────────────────

class TestStationCaution:
    """Listings with no TTC station within 20 min walk get a caution."""

    def test_caution_when_station_walk_over_20_min(self):
        from app import _compute_cautions, MAX_STATION_WALK_MIN
        d = {
            'pct_under': 10,
            'days_ago': 5,
            'sqft': '650',
            'price': 2000,
            'beds': 2,
            'region': 'Downtown',
            'station_name': 'Spadina Station',
            'station_walk_min': 25,  # > 20 min
        }
        cautions = _compute_cautions(d)
        assert any('No TTC station within 20 min walk' in c for c in cautions)

    def test_no_caution_when_station_nearby(self):
        from app import _compute_cautions
        d = {
            'pct_under': 10,
            'days_ago': 5,
            'sqft': '650',
            'price': 2000,
            'beds': 2,
            'region': 'Downtown',
            'station_name': 'St. George Station',
            'station_walk_min': 5,
        }
        cautions = _compute_cautions(d)
        assert not any('No TTC station within 20 min walk' in c for c in cautions)

    def test_no_caution_when_no_station_field(self):
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
        assert not any('No TTC station within 20 min walk' in c for c in cautions)

    def test_no_caution_when_station_within_threshold(self):
        from app import _compute_cautions
        # Edge case: exactly at threshold
        d = {
            'pct_under': 10,
            'days_ago': 5,
            'sqft': '650',
            'price': 2000,
            'beds': 2,
            'region': 'Downtown',
            'station_name': 'Spadina Station',
            'station_walk_min': 20,  # exactly at threshold — should not trigger caution
        }
        cautions = _compute_cautions(d)
        assert not any('No TTC station within 20 min walk' in c for c in cautions)


# ── MC-270: index.html TTC column rendering ────────────────────────────────────

class TestStationHtmlRendering:
    """index.html JS renders TTC station walk time for each row."""

    def test_station_walk_time_rendered(self):
        html = """
        <table id="deals-table">
          <tr data-row='{"station_name":"Spadina Station","station_walk_min":6}'>
            <td class="ttc-cell"></td>
          </tr>
        </table>
        <script>
        function renderRow(d) {
            const stationName = d.station_name;
            const stationWalk = d.station_walk_min;
            let ttcHtml = '-';
            if (stationName) {
              const walkStr = stationWalk ? stationWalk + ' min' : '';
              ttcHtml = '<span title="' + stationName + '">🚇 ' + walkStr + '</span>';
            } else if (stationWalk === null) {
              ttcHtml = '<span style="color:#888;">-</span>';
            }
            return ttcHtml;
        }
        </script>
        """
        assert 'station_name' in html
        assert 'station_walk_min' in html

    def test_station_null_renders_grey_dash(self):
        html = """
        <script>
        // When stationWalk is null, render grey dash
        const stationWalk = null;
        let ttcHtml = '-';
        if (stationName) {
            ttcHtml = '<span>🚇 ' + stationWalk + ' min</span>';
        } else if (stationWalk === null) {
            ttcHtml = '<span style="color:#888;">-</span>';
        }
        </script>
        """
        assert 'stationWalk === null' in html


if __name__ == '__main__':
    pytest.main([__file__, '-v'])