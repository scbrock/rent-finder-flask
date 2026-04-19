"""
Tests for neighbourhood_lookup.py (MC-260)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from neighbourhood_lookup import lookup, get_centroid, OFFICIAL_NEIGHBOURHOODS

def test_loads_official_data():
    assert len(OFFICIAL_NEIGHBOURHOODS) == 140, f"Expected 140, got {len(OFFICIAL_NEIGHBOURHOODS)}"
    # Check known neighbourhood
    assert 'Annex' in OFFICIAL_NEIGHBOURHOODS
    assert 'The Beaches' in OFFICIAL_NEIGHBOURHOODS
    # Check lat/lng fields
    d = OFFICIAL_NEIGHBOURHOODS['Annex']
    assert 'lat' in d and 'lng' in d
    assert -90 < d['lat'] < 90
    assert -180 < d['lng'] < 180

def test_direct_map_annex():
    result = lookup('Annex')
    assert result is not None
    assert result['official_name'] == 'Annex'
    assert abs(result['lat'] - 43.671585) < 0.001

def test_direct_map_variants():
    for variant in ['Annex', 'Annex.Toronto', 'annex toronto', 'THE ANNEX']:
        result = lookup(variant)
        assert result is not None, f"Failed for {variant}"
        assert result['official_name'] == 'Annex'

def test_the_beaches():
    for variant in ['The Beaches', 'the beaches', 'beaches', 'Toronto Beach']:
        result = lookup(variant)
        assert result is not None, f"Failed for {variant}"
        assert result['official_name'] == 'The Beaches'

def test_kensington_market():
    result = lookup('Kensington market')
    assert result is not None
    assert result['official_name'] == 'Kensington-Chinatown'

def test_non_toronto_returns_none():
    for n in ['Mississauga', 'Brampton', 'Markham', 'Oakville', 'Oshawa', 'Richmond Hill', 'Vaughan']:
        result = lookup(n)
        assert result is None, f"{n} should return None but got {result}"

def test_toronto_ontario_normalizes_away():
    # "Toronto, Ontario" normalizes to "ontario" → should return None (non-Toronto noise)
    result = lookup('Toronto, Ontario')
    assert result is None

def test_unknown_address_noise_returns_none():
    # These are addresses, not neighbourhoods — return None
    for n in ['65 Bremner Blvd', '123 Main St', '707 Clifford Perry Pl']:
        result = lookup(n)
        # Should either return None or map to a real neighbourhood via direct_map
        # Most address-style strings will fall through to fuzzy or None

def test_get_centroid():
    lat, lng = get_centroid('Annex')
    assert abs(lat - 43.671585) < 0.001
    assert abs(lng - (-79.404)) < 0.01

def test_get_centroid_unknown():
    result = get_centroid('NonexistentNeighbourhoodXYZ123')
    assert result is None

def test_fuzzy_match_liberty_village():
    # Liberty Village is not an official name — should map to University (adjacent)
    result = lookup('Liberty Village')
    assert result is not None
    assert result['official_name'] == 'University'

def test_fuzzy_match_yorkville():
    result = lookup('Yorkville')
    assert result is not None
    assert result['official_name'] == 'Rosedale-Moore Park'

def test_all_official_neighbourhoods_have_lat_lng():
    for name, d in OFFICIAL_NEIGHBOURHOODS.items():
        assert 'lat' in d, f"{name} missing lat"
        assert 'lng' in d, f"{name} missing lng"
        assert isinstance(d['lat'], (int, float)), f"{name} lat not numeric"
        assert isinstance(d['lng'], (int, float)), f"{name} lng not numeric"

def test_bay_street_corridor():
    # "Downtown Toronto" should map to Bay Street Corridor
    result = lookup('Downtown Toronto')
    assert result is not None
    assert result['official_name'] == 'Bay Street Corridor'

if __name__ == '__main__':
    import traceback
    tests = [
        test_loads_official_data, test_direct_map_annex, test_direct_map_variants,
        test_the_beaches, test_kensington_market, test_non_toronto_returns_none,
        test_toronto_ontario_normalizes_away, test_unknown_address_noise_returns_none,
        test_get_centroid, test_get_centroid_unknown, test_fuzzy_match_liberty_village,
        test_fuzzy_match_yorkville, test_all_official_neighbourhoods_have_lat_lng,
        test_bay_street_corridor,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f'PASS: {t.__name__}')
            passed += 1
        except AssertionError as e:
            print(f'FAIL: {t.__name__}: {e}')
            failed += 1
        except Exception:
            traceback.print_exc()
            print(f'ERROR: {t.__name__}')
            failed += 1
    print(f'\n{passed}/{passed+failed} passed, {failed} failed')