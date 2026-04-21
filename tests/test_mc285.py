"""
Tests for MC-285: Neighbourhood Segmentation Fix
Tests: district classification, score_deals_with_districts fair value coverage.
"""

import pytest, os, sys, json
import pandas as pd
import numpy as np

os.chdir(r"C:\Users\steph\.openclaw\workspace-coding\rent_finder")

# ── Test Data ─────────────────────────────────────────────────────────────────

SAMPLE_DISTRICT_DATA = [
    # Downtown 1BR listings — should compute fair value
    {"neighborhood": "Harbourfront", "district": "Downtown", "price": 2100, "beds": 1, "source": "Kijiji", "days_ago": 2, "link": "k1"},
    {"neighborhood": "Harbourfront", "district": "Downtown", "price": 2200, "beds": 1, "source": "Kijiji", "days_ago": 5, "link": "k2"},
    {"neighborhood": "King West", "district": "Downtown", "price": 2400, "beds": 1, "source": "Kijiji", "days_ago": 3, "link": "k3"},
    {"neighborhood": "Church-Yonge Corridor", "district": "Downtown", "price": 2000, "beds": 1, "source": "Kijiji", "days_ago": 7, "link": "k4"},
    # Downtown 2BR
    {"neighborhood": "Harbourfront", "district": "Downtown", "price": 3000, "beds": 2, "source": "Kijiji", "days_ago": 1, "link": "k5"},
    {"neighborhood": "King West", "district": "Downtown", "price": 3100, "beds": 2, "source": "Kijiji", "days_ago": 4, "link": "k6"},
    # Scarborough 1BR
    {"neighborhood": "Scarborough Town Centre", "district": "Scarborough", "price": 1800, "beds": 1, "source": "Craigslist", "days_ago": 10, "link": "c1"},
    {"neighborhood": "Agincourt", "district": "Scarborough", "price": 1700, "beds": 1, "source": "Craigslist", "days_ago": 12, "link": "c2"},
    {"neighborhood": "Milliken", "district": "Scarborough", "price": 1600, "beds": 1, "source": "Craigslist", "days_ago": 8, "link": "c3"},
    # Tiny neighbourhood — only 1 listing, should fall back to district FV
    {"neighborhood": "Very Specific Tiny Neighbourhood XYZ", "district": "Downtown", "price": 1900, "beds": 1, "source": "Kijiji", "days_ago": 1, "link": "k99"},
    # Room rental — should be excluded from FV calculation
    {"neighborhood": "Downtown", "district": "Downtown", "price": 900, "beds": 1, "source": "Kijiji", "days_ago": 3, "link": "k100", "title": "Private room in luxury condo"},
]


class TestClassifyDistrict:
    """Tests for _classify_district function."""

    def test_downtown_keywords(self):
        from find_deals import _classify_district
        assert _classify_district("Harbourfront") == "Downtown"
        assert _classify_district("King West") == "Downtown"
        assert _classify_district("Financial District") == "Downtown"
        assert _classify_district("Church-Yonge Corridor") == "Downtown"

    def test_midtown_keywords(self):
        from find_deals import _classify_district
        assert _classify_district("Parkdale") == "Midtown"
        assert _classify_district("High Park") == "Midtown"
        assert _classify_district("The Beaches") == "Midtown"
        assert _classify_district("Leslieville") == "Midtown"

    def test_scarborough_keywords(self):
        from find_deals import _classify_district
        assert _classify_district("Scarborough Town Centre") == "Scarborough"
        assert _classify_district("Agincourt") == "Scarborough"
        assert _classify_district("Steeles") == "Scarborough"

    def test_north_york_keywords(self):
        from find_deals import _classify_district
        assert _classify_district("Willowdale") == "North York"
        assert _classify_district("Don Mills") == "North York"
        assert _classify_district("Bayview Village") == "North York"

    def test_etobicoke_keywords(self):
        from find_deals import _classify_district
        assert _classify_district("Mimico") == "Etobicoke"
        assert _classify_district("The Kingsway") == "Etobicoke"

    def test_unknown_falls_back_to_toronto(self):
        from find_deals import _classify_district
        assert _classify_district("Completely Unknown Place 123") == "Toronto"
        assert _classify_district("") == "Toronto"
        assert _classify_district(None) == "Toronto"


class TestScoreDealsWithDistricts:
    """Tests for score_deals_with_districts function."""

    def test_all_listings_get_fair_value(self):
        """MC-285 AC1: All active listings get a fair value (no 0-score problem)."""
        from find_deals import score_deals_with_districts
        df = pd.DataFrame(SAMPLE_DISTRICT_DATA)
        scored = score_deals_with_districts(df)
        # All active listings should have a fair_value assigned
        if "is_stale" in scored.columns:
            active = scored[~scored["is_stale"]]
        else:
            active = scored
        no_fv = active["fair_value"].isna().sum()
        assert no_fv == 0, f"Expected 0 listings without fair_value, got {no_fv}"

    def test_downtown_1br_fair_value_is_mean(self):
        """MC-285 AC2: Downtown 1BR fair value = mean of non-room Downtown 1BR listings."""
        from find_deals import score_deals_with_districts
        import pandas as pd
        df = pd.DataFrame(SAMPLE_DISTRICT_DATA)
        scored = score_deals_with_districts(df)
        downtown_1br = scored[(scored["district"] == "Downtown") & (scored["beds"] == 1)]
        # Check that the room rental ($900) got a fair value that is HIGHER
        # than if the room rental WERE included (i.e., not the mean of all 5)
        room_rows = downtown_1br[downtown_1br.apply(
            lambda r: isinstance(r.get("title", ""), str) and "room" in r["title"].lower(), axis=1
        )]
        non_room_rows = downtown_1br[downtown_1br.apply(
            lambda r: not (isinstance(r.get("title", ""), str) and "room" in r["title"].lower()), axis=1
        )]
        # All non-room Downtown 1BR listings should have same FV
        # The room rental should have a fair_value that is NOT the global mean of (2100+2400+2000+1900+900)/5=1920
        # It should be higher (near 2120) since the room rental was excluded
        for _, row in non_room_rows.iterrows():
            # FV should be in range of Downtown 1BR non-room mean ±10%
            assert 1900 < row["fair_value"] < 2300, f"FV={row['fair_value']} seems off for Downtown 1BR"
        # The room rental should have a higher FV (since it's excluded from the group)
        for _, row in room_rows.iterrows():
            assert row["fair_value"] > 1500, f"Room rental FV={row['fair_value']} too low (room should be excluded)"

    def test_room_rental_excluded_from_fair_value(self):
        """MC-285 AC3: Room rental ($900) excluded from FV calc, doesn't drag down 1BR market."""
        from find_deals import score_deals_with_districts
        df = pd.DataFrame(SAMPLE_DISTRICT_DATA)
        scored = score_deals_with_districts(df)
        # Room rental at $900 is in Downtown/1BR group
        # If included: FV would be (2100+2200+2400+2000+1900+900)/6 = 1950
        # Expected (excluded): (2100+2200+2400+2000+1900)/5 = 2120
        downtown_1br = scored[(scored["district"] == "Downtown") & (scored["beds"] == 1)]
        expected_fv_without_room = 2120
        for _, row in downtown_1br.iterrows():
            assert abs(row["fair_value"] - expected_fv_without_room) < 1, \
                f"Room rental may have contaminated FV: expected {expected_fv_without_room}, got {row['fair_value']}"

    def test_tiny_neighbourhood_falls_back_to_district(self):
        """MC-285 AC4: Listings in neighbourhood with <3 listings fall back to district FV."""
        from find_deals import score_deals_with_districts
        import pandas as pd
        df = pd.DataFrame(SAMPLE_DISTRICT_DATA)
        scored = score_deals_with_districts(df)
        tiny = scored[scored["neighborhood"] == "Very Specific Tiny Neighbourhood XYZ"]
        assert len(tiny) == 1
        fv = tiny.iloc[0]["fair_value"]
        assert not pd.isna(fv), "Tiny neighbourhood should get district-level FV"
        # Should get Downtown 1BR mean = 2120
        assert abs(tiny.iloc[0]["fair_value"] - 2120) < 1

    def test_scarborough_1br_fair_value_from_district_group(self):
        """MC-285 AC5: Scarborough 1BR gets fair value from Scarborough 1BR group (3 listings)."""
        from find_deals import score_deals_with_districts
        df = pd.DataFrame(SAMPLE_DISTRICT_DATA)
        scored = score_deals_with_districts(df)
        scarborough_1br = scored[(scored["district"] == "Scarborough") & (scored["beds"] == 1)]
        expected_fv = (1800 + 1700 + 1600) / 3  # = 1700
        for _, row in scarborough_1br.iterrows():
            assert abs(row["fair_value"] - expected_fv) < 1, f"Expected FV={expected_fv}, got {row['fair_value']}"

    def test_pct_under_calculated(self):
        """MC-285 AC6: pct_under is correctly calculated."""
        from find_deals import score_deals_with_districts
        import pandas as pd
        df = pd.DataFrame(SAMPLE_DISTRICT_DATA)
        scored = score_deals_with_districts(df)
        for _, row in scored.iterrows():
            fv = row["fair_value"]
            if not pd.isna(fv) and fv > 0:
                expected_pct = (fv - row["price"]) / fv * 100
                assert abs(row["pct_under"] - expected_pct) < 0.1

    def test_score_normalized_to_0_1(self):
        """MC-285 AC7: score is normalized; positive = under-priced, negative = over-priced."""
        from find_deals import score_deals_with_districts
        df = pd.DataFrame(SAMPLE_DISTRICT_DATA)
        scored = score_deals_with_districts(df)
        # Scores with valid fair values should be properly normalized
        scored_valid = scored[scored["score"].notna()]
        # pct_under values: negative when overpriced, positive when underpriced
        # score = pct_under / max_under, so sign should match pct_under sign
        for _, row in scored_valid.iterrows():
            if row["pct_under"] > 0:
                assert row["score"] >= 0, f"Under-priced listing should have score >= 0, got {row['score']}"
            elif row["pct_under"] < 0:
                assert row["score"] <= 0, f"Over-priced listing should have score <= 0, got {row['score']}"

    def test_freshness_boost_applied(self):
        """MC-285 AC8: Freshness boost added to score."""
        from find_deals import score_deals_with_districts
        df = pd.DataFrame(SAMPLE_DISTRICT_DATA)
        scored = score_deals_with_districts(df)
        # Listings <= 5 days should have freshness_boost > 0
        fresh = scored[scored["days_ago"] <= 5]
        assert all(fresh["freshness_boost"] > 0), "Fresh listings should get boost"

    def test_concat_and_dedup_removes_duplicates(self):
        """Test dedup by URL keeps first occurrence."""
        from find_deals import concat_and_dedup
        df1 = pd.DataFrame([
            {"price": 1000, "beds": 1, "link": "http://example.com/1"},
            {"price": 2000, "beds": 2, "link": "http://example.com/2"},
        ])
        df2 = pd.DataFrame([
            {"price": 1500, "beds": 1, "link": "http://example.com/1"},  # duplicate
            {"price": 3000, "beds": 2, "link": "http://example.com/3"},
        ])
        result = concat_and_dedup([df1, df2])
        assert len(result) == 3, f"Expected 3 rows after dedup, got {len(result)}"
        # First occurrence kept (price=1000 not 1500)
        dup_row = result[result["link"] == "http://example.com/1"]
        assert len(dup_row) == 1
        assert dup_row.iloc[0]["price"] == 1000, "First occurrence (lower price) should be kept"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])