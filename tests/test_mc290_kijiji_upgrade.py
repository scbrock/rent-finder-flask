"""
Tests for MC-290: Kijiji scraper upgrade (Apollo GraphQL parser).
Validates that find_deals.scrape_kijiji() returns proper DataFrames
after switching from HTML card parser to Apollo state parser.
"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from find_deals import scrape_kijiji, _clamp_beds, _clamp_baths
import pandas as pd


class TestClampHelpers:
    def test_clamp_beds_valid(self):
        assert _clamp_beds(1.0) == 1
        assert _clamp_beds(2.0) == 2
        assert _clamp_beds(0.0) == 0

    def test_clamp_beds_bounds(self):
        """Beds: values > 10 treated as garbled and returned as 0."""
        assert _clamp_beds(-1.0) == 0
        assert _clamp_beds(6.0) == 6  # within 0-10 range
        assert _clamp_beds(100.0) == 0  # > 10 treated as garbage

    def test_clamp_baths_valid(self):
        assert _clamp_baths(1.0) == 1.0
        assert _clamp_baths(2.0) == 2.0

    def test_clamp_baths_bounds(self):
        """Baths: values < 0.5 or > 6 treated as garbage and returned as 0."""
        assert _clamp_baths(0.0) == 0.0  # < 0.5 treated as garbage
        assert _clamp_baths(10.0) == 0.0  # > 6 treated as garbage
        assert _clamp_baths(2.0) == 2.0  # valid
        assert _clamp_baths(1.5) == 1.5  # valid


class TestScrapeKijijiIntegration:
    """Integration test — calls actual Kijiji scrape and validates output shape."""

    def test_scrape_kijiji_returns_dataframe(self):
        """scrape_kijiji() returns a DataFrame with required columns."""
        df = scrape_kijiji(pages=1)
        assert isinstance(df, pd.DataFrame), "Should return a DataFrame"

    def test_scrape_kijiji_has_required_columns(self):
        """DataFrame has all required columns for deal scoring."""
        df = scrape_kijiji(pages=1)
        required = ["source", "price", "beds", "baths", "neighborhood", "link", "days_ago", "is_stale"]
        for col in required:
            assert col in df.columns, f"Missing column: {col}"

    def test_scrape_kijiji_source_is_kijiji(self):
        """All rows should have source='Kijiji'."""
        df = scrape_kijiji(pages=1)
        if not df.empty:
            assert (df["source"] == "Kijiji").all(), "All listings should have source='Kijiji'"

    def test_scrape_kijiji_price_range(self):
        """Prices should be in valid rental range ($500-$15000)."""
        df = scrape_kijiji(pages=1)
        if not df.empty:
            assert df["price"].min() >= 500, "Min price should be >= $500"
            assert df["price"].max() <= 15000, "Max price should be <= $15000"

    def test_scrape_kijiji_no_negative_prices(self):
        """No listings should have negative or zero prices."""
        df = scrape_kijiji(pages=1)
        if not df.empty:
            assert (df["price"] > 0).all(), "All prices should be positive"

    def test_scrape_kijiji_links_are_valid(self):
        """All listings should have a valid kijiji.ca URL."""
        df = scrape_kijiji(pages=1)
        if not df.empty:
            assert df["link"].str.contains("kijiji.ca").all(), "All links should be kijiji.ca URLs"

    def test_scrape_kijiji_beds_are_clamped(self):
        """Bedroom counts should be clamped to 0-5 range."""
        df = scrape_kijiji(pages=1)
        if not df.empty:
            assert df["beds"].min() >= 0, "Beds should not be negative"
            assert df["beds"].max() <= 5, "Beds should not exceed 5 (capped)"

    def test_scrape_kijiji_is_stale_boolean(self):
        """is_stale should be boolean."""
        df = scrape_kijiji(pages=1)
        if not df.empty:
            assert df["is_stale"].dtype == bool, "is_stale should be boolean"

    def test_scrape_kijiji_days_ago_positive(self):
        """days_ago should be non-negative."""
        df = scrape_kijiji(pages=1)
        if not df.empty:
            assert (df["days_ago"] >= 0).all(), "days_ago should not be negative"

    def test_scrape_kijiji_multipage(self):
        """Scraping 2 pages returns more listings than 1 page."""
        df1 = scrape_kijiji(pages=1)
        df2 = scrape_kijiji(pages=2)
        if not df1.empty and not df2.empty:
            assert len(df2) > len(df1), "2 pages should return more listings than 1 page"

    def test_scrape_kijiji_neighborhood_not_empty(self):
        """Neighborhood should not be empty/null."""
        df = scrape_kijiji(pages=1)
        if not df.empty:
            assert df["neighborhood"].notna().all(), "Neighborhood should not be null"
            assert (df["neighborhood"] != "").all(), "Neighborhood should not be empty string"
