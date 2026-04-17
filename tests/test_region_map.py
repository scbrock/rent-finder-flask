"""Tests for region_map.py"""

import pytest
from region_map import neighbourhood_to_region


def test_downtown():
    assert neighbourhood_to_region("Toronto") == "Downtown"
    assert neighbourhood_to_region("City of Toronto") == "Downtown"
    assert neighbourhood_to_region("Old Town") == "Downtown"
    assert neighbourhood_to_region("Regent Park") == "Downtown"
    assert neighbourhood_to_region("North St.James Town") == "Downtown"


def test_east_end():
    assert neighbourhood_to_region("Birchcliffe-Cliffside") == "East End"
    assert neighbourhood_to_region("Guildwood") == "East End"
    assert neighbourhood_to_region("Woodbine Corridor") == "East End"


def test_west_end():
    assert neighbourhood_to_region("Junction Area") == "West End"
    assert neighbourhood_to_region("South Parkdale") == "West End"


def test_north_york():
    assert neighbourhood_to_region("North York") == "North York"
    assert neighbourhood_to_region("York University Heights") == "North York"
    assert neighbourhood_to_region("Clanton Park") == "North York"
    assert neighbourhood_to_region("Flemingdon Park") == "North York"


def test_scarborough():
    assert neighbourhood_to_region("Scarborough") == "Scarborough"


def test_etobicoke():
    assert neighbourhood_to_region("Sonoma Heights") == "Etobicoke"


def test_unknown_defaults_to_downtown():
    assert neighbourhood_to_region("Some Unknown Place") == "Downtown"