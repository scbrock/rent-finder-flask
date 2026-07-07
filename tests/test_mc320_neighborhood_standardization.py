"""
MC-320 — Neighbourhood Standardization tests.

Verifies:
1. standardize() correctly maps raw scraped neighborhoods to official names
2. Title-based fallback works for generic "Toronto"/"" inputs
3. Non-Toronto municipalities return empty string
4. standardize_neighbourhoods() in find_deals.py applies to DataFrame correctly
5. Region column is populated based on standardized neighborhood
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pandas as pd
import pytest

import neighbourhood_lookup as nl
import region_map
import find_deals


class TestStandardizeFn:
    """Test neighbourhood_lookup.standardize() directly."""

    def test_specific_neighbourhood_passes_through(self):
        # Specific names should resolve to their official name
        assert nl.standardize("Liberty Village", "") == "University"  # direct map
        assert nl.standardize("Harbourfront", "") == "Waterfront Communities-The Island"
        assert nl.standardize("Kensington market", "") == "Kensington-Chinatown"

    def test_generic_toronto_returns_none_without_title(self):
        # "Toronto" alone is too generic — we should NOT guess
        assert nl.standardize("Toronto", "") is None

    def test_generic_city_of_toronto_returns_none_without_title(self):
        # Same — keep original if no better signal
        assert nl.standardize("city of toronto", "") is None

    def test_empty_neighbourhood_with_title_hint(self):
        # Title fallback: "Studio in Yorkville" should find Yorkville
        assert nl.standardize("", "Studio in Yorkville") == "Rosedale-Moore Park"

    def test_empty_neighbourhood_with_annex_in_title(self):
        assert nl.standardize("", "Beautiful 2BR in The Annex") == "Annex"

    def test_toronto_with_king_west_in_title(self):
        assert nl.standardize("Toronto", "1BR in King West") == "Niagara"

    def test_city_of_toronto_with_annex_in_title(self):
        # Previously this returned "Agincourt North" via fuzzy noise
        assert nl.standardize("city of toronto", "Beautiful Annex Apartment") == "Annex"

    def test_mississauga_returns_empty_string(self):
        # Non-Toronto municipality → empty string (excluded from region)
        assert nl.standardize("Mississauga", "") == ""

    def test_vaughan_returns_empty_string(self):
        assert nl.standardize("Vaughan", "") == ""

    def test_brampton_returns_empty_string(self):
        assert nl.standardize("Brampton", "") == ""

    def test_empty_neighbourhood_empty_title_returns_none(self):
        assert nl.standardize("", "") is None

    def test_title_with_no_neighbourhood_hint_returns_none(self):
        # Title says "Spacious 2BR" — no neighbourhood signal anywhere
        assert nl.standardize("", "Spacious 2BR with balcony") is None

    def test_dupont_and_dufferin_resolves(self):
        # Was returning None before — added to direct map in MC-320
        assert nl.standardize("dupont and dufferin", "") == "Dufferin Grove"

    def test_king_west_resolves_to_niagara(self):
        # Was returning "Kingsway South" via fuzzy noise
        assert nl.standardize("King West", "") == "Niagara"

    def test_north_york_resolves_to_specific_neighbourhood(self):
        # "north york" is city-level but has a direct-map entry
        assert nl.standardize("North York", "") == "Lansing-Westgate"

    def test_scarborough_resolves(self):
        assert nl.standardize("Scarborough", "") == "Woburn"

    def test_etobicoke_resolves(self):
        assert nl.standardize("Etobicoke", "") == "Etobicoke West Mall"


class TestStandardizeNeighbourhoodsFn:
    """Test find_deals.standardize_neighbourhoods() on DataFrames."""

    def test_empty_dataframe(self):
        df = pd.DataFrame({"neighborhood": []})
        result = find_deals.standardize_neighbourhoods(df)
        assert "region" in result.columns
        assert len(result) == 0

    def test_specific_neighbourhood_kept(self):
        df = pd.DataFrame({
            "neighborhood": ["Liberty Village", "Harbourfront", "Kensington market"],
            "title": ["", "", ""],
        })
        result = find_deals.standardize_neighbourhoods(df)
        # Liberty Village → University (direct map)
        assert result.at[0, "neighborhood"] == "University"
        assert result.at[1, "neighborhood"] == "Waterfront Communities-The Island"
        assert result.at[2, "neighborhood"] == "Kensington-Chinatown"
        # All three are downtown-ish — region should be non-empty for all
        assert all(r for r in result["region"])

    def test_generic_with_title_hint(self):
        df = pd.DataFrame({
            "neighborhood": ["Toronto", "Toronto", "city of toronto"],
            "title": ["1BR in King West", "Studio in Yorkville", "Annex apartment"],
        })
        result = find_deals.standardize_neighbourhoods(df)
        assert result.at[0, "neighborhood"] == "Niagara"
        assert result.at[1, "neighborhood"] == "Rosedale-Moore Park"
        assert result.at[2, "neighborhood"] == "Annex"

    def test_non_toronto_marked_empty_region(self):
        df = pd.DataFrame({
            "neighborhood": ["Mississauga", "Vaughan", "Brampton"],
            "title": ["", "", ""],
        })
        result = find_deals.standardize_neighbourhoods(df)
        # Non-Toronto should have empty region
        assert all(r == "" for r in result["region"])

    def test_no_title_column_does_not_crash(self):
        df = pd.DataFrame({"neighborhood": ["Liberty Village", "Toronto"]})
        result = find_deals.standardize_neighbourhoods(df)
        # Should not throw; specific value kept, generic stays as-is
        assert result.at[0, "neighborhood"] == "University"
        assert result.at[1, "neighborhood"] == "Toronto"  # generic + no title → unchanged

    def test_missing_neighborhood_column_added(self):
        df = pd.DataFrame({"price": [1000, 2000]})
        result = find_deals.standardize_neighbourhoods(df)
        assert "neighborhood" in result.columns
        assert all(r == "" for r in result["neighborhood"])

    def test_mixed_toronto_and_non_toronto(self):
        df = pd.DataFrame({
            "neighborhood": ["Toronto", "Mississauga", "Liberty Village", "Vaughan", ""],
            "title": ["1BR in King West", "", "", "", "Studio in Yorkville"],
        })
        result = find_deals.standardize_neighbourhoods(df)
        assert result.at[0, "neighborhood"] == "Niagara"  # Toronto + title → resolved
        assert result.at[1, "neighborhood"] == "Mississauga"  # non-Toronto kept
        assert result.at[1, "region"] == ""
        assert result.at[2, "neighborhood"] == "University"  # specific via direct map
        assert result.at[3, "neighborhood"] == "Vaughan"  # non-Toronto kept
        assert result.at[3, "region"] == ""
        assert result.at[4, "neighborhood"] == "Rosedale-Moore Park"  # empty + title

    def test_returns_modified_dataframe(self):
        df = pd.DataFrame({"neighborhood": ["Liberty Village"]})
        result = find_deals.standardize_neighbourhoods(df)
        # Should return the same df (modified in-place)
        assert result is df
        assert "region" in result.columns

    def test_region_column_overrides_existing(self):
        df = pd.DataFrame({
            "neighborhood": ["Liberty Village", "Mississauga"],
            "region": ["OLD_VALUE", "OLD_VALUE"],
        })
        result = find_deals.standardize_neighbourhoods(df)
        # Old region values should be overwritten
        assert result.at[0, "region"] != "OLD_VALUE"
        assert result.at[1, "region"] == ""  # Missisauga → empty region


class TestRegionMapping:
    """Verify standardized neighborhoods map to correct regions."""

    def test_downtown_neighbourhoods(self):
        # Standardized Toronto-downtown neighborhoods should map to Downtown
        for nbhd in ["Bay Street Corridor", "Waterfront Communities-The Island", "Church-Yonge Corridor"]:
            r = region_map.neighbourhood_to_region(nbhd)
            assert r == "Downtown", f"{nbhd} should be Downtown, got {r!r}"

    def test_west_end_neighbourhoods(self):
        # Niagara is classified as West End per region_map's internal logic
        for nbhd in ["Niagara"]:
            r = region_map.neighbourhood_to_region(nbhd)
            assert r == "West End", f"{nbhd} should be West End, got {r!r}"

    def test_university_is_downtown_per_region_map(self):
        # "University" maps to Downtown per region_map (covers Queen West area)
        assert region_map.neighbourhood_to_region("University") == "Downtown"

    def test_kensington_is_downtown_per_region_map(self):
        assert region_map.neighbourhood_to_region("Kensington-Chinatown") == "Downtown"

    def test_annex_is_downtown_per_region_map(self):
        assert region_map.neighbourhood_to_region("Annex") == "Downtown"

    def test_non_toronto_returns_empty(self):
        for nbhd in ["Mississauga", "Vaughan", "Brampton", "Markham"]:
            r = region_map.neighbourhood_to_region(nbhd)
            assert r == "", f"{nbhd} should return empty, got {r!r}"


class TestIntegrationWithExistingData:
    """Apply standardize to real scraped data and verify improvements."""

    def test_realistic_kijiji_style_data(self):
        # Simulate what Kijiji scraper returns — often neighborhood is "Toronto"
        # with title hinting at actual neighborhood
        df = pd.DataFrame({
            "source": ["Kijiji"] * 6,
            "price": [2000, 2500, 1800, 2200, 1900, 2100],
            "beds": [1, 2, 1, 2, 1, 1],
            "sqft": [None, 800, 550, None, 600, None],
            "neighborhood": ["Toronto", "Toronto", "city of toronto", "Liberty Village", "Mississauga", "Toronto"],
            "title": [
                "1BR Condo in King West",
                "Beautiful 2BR in The Annex",
                "Studio in Yorkville",
                "1BR Loft",
                "2BR House",
                "1BR in Cabbagetown",
            ],
            "days_ago": [2, 5, 1, 10, 3, 4],
            "link": [f"http://example.com/{i}" for i in range(6)],
        })
        result = find_deals.standardize_neighbourhoods(df)
        # Toronto + King West → Niagara (West End per region_map)
        assert result.at[0, "neighborhood"] == "Niagara"
        assert result.at[0, "region"] == "West End"
        # Toronto + Annex → Annex (Downtown per region_map)
        assert result.at[1, "neighborhood"] == "Annex"
        assert result.at[1, "region"] == "Downtown"
        # city of toronto + Yorkville → Rosedale-Moore Park (Downtown per region_map)
        assert result.at[2, "neighborhood"] == "Rosedale-Moore Park"
        assert result.at[2, "region"] == "Downtown"
        # Liberty Village → University (Downtown per region_map)
        assert result.at[3, "neighborhood"] == "University"
        # Mississauga → kept, region empty
        assert result.at[4, "neighborhood"] == "Mississauga"
        assert result.at[4, "region"] == ""
        # Toronto + Cabbagetown → Cabbagetown-South St.James Town (Downtown)
        assert result.at[5, "neighborhood"] == "Cabbagetown-South St.James Town"
        assert result.at[5, "region"] == "Downtown"

    def test_coverage_improves_over_unstandardized(self):
        # With standardization, region coverage should improve
        # over unstandardized "Toronto" bucketing
        raw_df = pd.DataFrame({
            "neighborhood": ["Toronto"] * 10 + ["Liberty Village", "Harbourfront", "Mississauga"],
            "title": (
                ["1BR in " + nb for nb in ["King West", "Annex", "Yorkville", "Cabbagetown",
                                            "Leslieville", "Roncesvalles", "Liberty Village",
                                            "The Beaches", "Parkdale", "Corktown"]] +
                ["", "", ""]
            ),
        })
        standardized = find_deals.standardize_neighbourhoods(raw_df)
        # Of the 13 rows, 10 are Toronto-with-title (should resolve to neighborhoods)
        # 1 is Liberty Village (resolves via direct map)
        # 1 is Harbourfront (resolves via direct map)
        # 1 is Mississauga (non-Toronto, empty region)
        non_empty_regions = sum(1 for r in standardized["region"] if r)
        assert non_empty_regions == 12, f"Expected 12 non-empty regions, got {non_empty_regions}"