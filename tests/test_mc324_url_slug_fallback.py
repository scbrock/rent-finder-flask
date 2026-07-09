"""
MC-324 — URL slug + street-pattern fallback in standardize() tests.

Verifies:
1. extract_url_slug() handles CL/Kijiji URLs correctly
2. standardize() with url_slug resolves generic 'Toronto'/'city of toronto'/'' rows
3. Street patterns (pape ave, annette st, etc.) map to correct neighbourhoods
4. standardize_neighbourhoods() passes URL slug through to standardize()
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pandas as pd
import pytest

import neighbourhood_lookup as nl
import find_deals


class TestExtractUrlSlug:
    """Test neighbourhood_lookup.extract_url_slug()."""

    def test_cl_url(self):
        url = "https://www.craigslist.org/view/d/toronto-3br-annex-large-apartment/vF5BAc7juFy9tHQ4MtEr9m"
        assert nl.extract_url_slug(url) == "toronto-3br-annex-large-apartment"

    def test_kijiji_url(self):
        url = "https://www.kijiji.ca/v-apartments-condos/city-of-toronto/condo-in-the-distillery-for-rent/1740244229"
        assert nl.extract_url_slug(url) == "condo-in-the-distillery-for-rent"

    def test_empty_url(self):
        assert nl.extract_url_slug("") == ""

    def test_none_url(self):
        assert nl.extract_url_slug(None) == ""

    def test_malformed_url(self):
        # No scheme, no path
        assert nl.extract_url_slug("not a url") == ""

    def test_cl_url_with_street(self):
        url = "https://www.craigslist.org/view/d/toronto-829-pape-ave-bsmt-junior-1bed/q8HBE6SUzNRpC4GKMT5thn"
        assert nl.extract_url_slug(url) == "toronto-829-pape-ave-bsmt-junior-1bed"


class TestStandardizeWithUrlSlug:
    """Test neighbourhood_lookup.standardize() with url_slug fallback."""

    def test_annex_in_slug(self):
        # Generic raw + slug with "annex" -> Annex
        assert nl.standardize("Toronto", "", "toronto-3br-annex-large-apartment") == "Annex"

    def test_king_west_in_slug(self):
        assert nl.standardize("Toronto", "", "1br-condo-in-king-west-furnished") == "Niagara"

    def test_distillery_in_slug(self):
        assert nl.standardize("Toronto", "", "condo-in-the-distillery-for-rent") == "St.Andrew-Windfields"

    def test_east_york_in_slug(self):
        assert nl.standardize("Toronto", "", "east-york-spacious-bedroom-apartment-at") == "Old East York"

    def test_midtown_in_slug(self):
        assert nl.standardize("Toronto", "", "toronto-lease-assignment-bed-midtown") == "Yonge-Eglinton"

    def test_scarborough_in_slug(self):
        assert nl.standardize("Toronto", "", "scarborough-clean-bright-bedroom") == "Woburn"

    def test_etobicoke_in_slug(self):
        assert nl.standardize("Toronto", "", "etobicoke-fourplex-basement-apartment") == "Etobicoke West Mall"

    def test_bloor_west_in_slug(self):
        assert nl.standardize("Toronto", "", "toronto-luxury-bedroom-bloor-west") == "Runnymede-Bloor West Village"

    def test_downsview_in_slug(self):
        assert nl.standardize("Toronto", "", "downsview-central-beautifully-bright") == "Downsview-Roding-CFB"

    def test_pape_ave_in_slug(self):
        # Street pattern: 829 Pape Ave -> Old East York
        assert nl.standardize("Toronto", "", "toronto-829-pape-ave-bsmt-junior-1bed") == "Old East York"

    def test_annette_st_in_slug(self):
        # Street pattern: 589 Annette St -> Runnymede-Bloor West Village
        assert nl.standardize("Toronto", "", "toronto-589-annette-st-bsmt-1bed-1bath") == "Runnymede-Bloor West Village"

    def test_madison_ave_in_slug(self):
        # Street pattern: 209 Madison Ave -> Annex
        assert nl.standardize("Toronto", "", "toronto-209-madison-ave-spacious-3bed") == "Annex"

    def test_scarlett_rd_in_slug(self):
        # Street pattern: 127 Scarlett Rd -> Weston-Pellam Park
        assert nl.standardize("Toronto", "", "york-127-scarlett-rd-updated-2bed-1bath") == "Weston-Pellam Park"

    def test_oconnor_dr_in_slug(self):
        # Street pattern: 79 O'Connor Dr -> Old East York
        assert nl.standardize("Toronto", "", "east-toronto-79-oconnor-dr-lower-2bed") == "Old East York"

    def test_rockvale_ave_in_slug(self):
        # Street pattern: 26 Rockvale Ave -> L'Amoreaux
        assert nl.standardize("Toronto", "", "york-26-rockvale-ave-bsmt-bed-1bath") == "L'Amoreaux"

    def test_yore_rd_in_slug(self):
        # Street pattern: 36 Yore Rd -> Newtonbrook East
        assert nl.standardize("Toronto", "", "york-36-yore-rd-main-2bed-1bath-parking") == "Newtonbrook East"

    def test_no_neighbourhood_in_slug(self):
        # No useful info -> None
        assert nl.standardize("Toronto", "", "toronto-1bed-apt-to-rent-in-toronto") is None
        assert nl.standardize("Toronto", "", "toronto-studio-apartment-for-rent") is None

    def test_empty_slug_falls_back_to_title(self):
        # No slug, but title has hint
        assert nl.standardize("Toronto", "Beautiful 2BR in King West", "") == "Niagara"

    def test_both_title_and_slug(self):
        # Title and slug both have hints — first valid wins
        result = nl.standardize("Toronto", "Lovely apartment", "toronto-2br-annex-apartment")
        assert result == "Annex"

    def test_non_toronto_slug(self):
        # Non-Toronto slug -> empty string
        assert nl.standardize("Toronto", "", "mississauga-2br-apartment-near-square-one") == ""

    def test_city_of_toronto_with_slug(self):
        # Generic raw + slug
        assert nl.standardize("city of toronto", "", "toronto-3br-annex-large-apartment") == "Annex"


class TestStandardizeNeighbourhoodsWithLinkColumn:
    """Test find_deals.standardize_neighbourhoods() with link column."""

    def test_generic_with_link_slug(self):
        df = pd.DataFrame({
            "neighborhood": ["Toronto", "Toronto", "Toronto", "Toronto"],
            "title": ["", "", "", ""],
            "link": [
                "https://www.craigslist.org/view/d/toronto-3br-annex-large-apartment/vF5BAc7juFy9tHQ4MtEr9m",
                "https://www.craigslist.org/view/d/condo-in-the-distillery-for-rent/abc123",
                "https://www.craigslist.org/view/d/east-york-spacious-bedroom-apartment-at/xyz789",
                "https://www.kijiji.ca/v-apartments-condos/city-of-toronto/1-bedroom-king-west-unfurnished-sep-1st/1740244229",
            ],
        })
        result = find_deals.standardize_neighbourhoods(df)
        assert result.at[0, "neighborhood"] == "Annex"
        assert result.at[1, "neighborhood"] == "St.Andrew-Windfields"
        assert result.at[2, "neighborhood"] == "Old East York"
        assert result.at[3, "neighborhood"] == "Niagara"

    def test_link_column_alias_url(self):
        # If only 'url' column present, should still work
        df = pd.DataFrame({
            "neighborhood": ["Toronto"],
            "url": ["https://www.craigslist.org/view/d/toronto-3br-annex-large-apartment/vF5BAc7juFy9tHQ4MtEr9m"],
        })
        result = find_deals.standardize_neighbourhoods(df)
        assert result.at[0, "neighborhood"] == "Annex"

    def test_no_link_column_does_not_crash(self):
        df = pd.DataFrame({"neighborhood": ["Toronto"]})
        result = find_deals.standardize_neighbourhoods(df)
        # Should not throw; generic + no link -> unchanged
        assert result.at[0, "neighborhood"] == "Toronto"

    def test_region_populated_via_slug(self):
        df = pd.DataFrame({
            "neighborhood": ["Toronto", "Toronto"],
            "link": [
                "https://www.craigslist.org/view/d/toronto-3br-annex-large-apartment/abc",
                "https://www.craigslist.org/view/d/scarborough-clean-bright-bedroom/xyz",
            ],
        })
        result = find_deals.standardize_neighbourhoods(df)
        # Annex -> Downtown, Scarborough -> Scarborough
        assert result.at[0, "region"] == "Downtown"
        assert result.at[1, "region"] == "Scarborough"


class TestCoverageImprovementOnRealData:
    """Apply standardize to realistic data and verify the URL slug fallback
    significantly reduces the generic rate."""

    def test_realistic_cl_data(self):
        # Simulate CL-style data where title is empty but URL has neighbourhood
        data = [
            ("Toronto", "", "https://www.craigslist.org/view/d/toronto-3br-annex-large-apartment/abc"),
            ("Toronto", "", "https://www.craigslist.org/view/d/toronto-2br-annex-apartment/abc"),
            ("Toronto", "", "https://www.craigslist.org/view/d/scarborough-clean-bright-bedroom/abc"),
            ("Toronto", "", "https://www.craigslist.org/view/d/etobicoke-fourplex-basement-apartment/abc"),
            ("Toronto", "", "https://www.craigslist.org/view/d/toronto-luxury-bedroom-bloor-west/abc"),
            ("Toronto", "", "https://www.craigslist.org/view/d/toronto-lease-assignment-bed-midtown/abc"),
            ("Toronto", "", "https://www.craigslist.org/view/d/condo-in-the-distillery-for-rent/abc"),
            ("Toronto", "", "https://www.craigslist.org/view/d/east-york-spacious-bedroom-apartment-at/abc"),
            ("Toronto", "", "https://www.craigslist.org/view/d/toronto-829-pape-ave-bsmt-junior-1bed/abc"),
            ("Toronto", "", "https://www.craigslist.org/view/d/toronto-1bed-apt-to-rent-in-toronto/abc"),  # no info
        ]
        df = pd.DataFrame([{"neighborhood": nb, "title": t, "link": l} for nb, t, l in data])
        result = find_deals.standardize_neighbourhoods(df)
        # 9 out of 10 should resolve to specific neighbourhoods
        specific = sum(1 for nb in result["neighborhood"] if nb.lower() not in ("toronto", "city of toronto", ""))
        assert specific == 9, f"Expected 9 specific, got {specific}: {result['neighborhood'].tolist()}"

    def test_street_pattern_lookups(self):
        # Verify street patterns resolve independently
        cases = [
            ("pape ave", "Old East York"),
            ("pape avenue", "Old East York"),
            ("annette st", "Runnymede-Bloor West Village"),
            ("annette street", "Runnymede-Bloor West Village"),
            ("madison ave", "Annex"),
            ("madison avenue", "Annex"),
            ("scarlett rd", "Weston-Pellam Park"),
            ("scarlett road", "Weston-Pellam Park"),
            ("rockvale ave", "L'Amoreaux"),
            ("o'connor dr", "Old East York"),
            ("oconnor drive", "Old East York"),
            ("yore rd", "Newtonbrook East"),
            ("jane st", "Downsview-Roding-CFB"),
            ("eglinton ave w", "Forest Hill South"),
            ("st clair ave e", "Mount Pleasant East"),
            ("lawrence ave", "Lawrence Park North"),
        ]
        for street, expected in cases:
            result = nl.standardize("Toronto", "", f"listing-on-{street.replace(' ', '-')}")
            assert result == expected, f"street {street!r}: expected {expected!r}, got {result!r}"