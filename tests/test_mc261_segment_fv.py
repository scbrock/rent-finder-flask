"""
Tests for compute_segment_fv.py — MC-261 context-aware fair value.
"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from compute_segment_fv import (
    compute_segment_fair_value,
    compute_fair_value_with_fallback,
    _norm_neighbourhood,
    _norm_beds,
    MIN_COMPS,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_deal(neighbourhood, beds, price):
    return {
        "neighbourhood": neighbourhood,
        "beds": beds,
        "price": price,
        "price_fmt": f"${price:,}",
        "pct_under": 0,
        "final_score": 0,
    }


class TestNormHelpers:
    def test_norm_neighbourhood(self):
        assert _norm_neighbourhood("Downtown Toronto") == "downtown toronto"
        assert _norm_neighbourhood("  Queen West  ") == "queen west"
        assert _norm_neighbourhood("") == ""
        assert _norm_neighbourhood(None) == ""

    def test_norm_beds(self):
        assert _norm_beds(1) == 1
        assert _norm_beds(2.0) == 2.0
        assert _norm_beds("1") == 1.0
        assert _norm_beds(None) is None
        assert _norm_beds("") is None
        assert _norm_beds(-1) is None


class TestSegmentFairValue:
    def test_single_deal_no_segment(self):
        """1 deal with 0 comps → no fair_value computed."""
        deals = [make_deal("Downtown", 1, 2000)]
        result = compute_segment_fair_value(deals)
        assert result[0]["segment_fair_value"] is None
        assert result[0]["comp_message"] == "Too few comps"

    def test_five_comps_exact_segment(self):
        """5+ deals in same (neighbourhood, beds) → fair_value computed."""
        deals = [
            make_deal("Queen West", 1, 2000),
            make_deal("Queen West", 1, 2100),
            make_deal("Queen West", 1, 2050),
            make_deal("Queen West", 1, 2150),
            make_deal("Queen West", 1, 2000),
        ]
        result = compute_segment_fair_value(deals)
        # Median of [2000,2100,2050,2150,2000] sorted = [2000,2000,2050,2100,2150] → 2050
        assert result[0]["segment_fair_value"] == 2050
        assert result[0]["comp_count"] == 5
        assert result[0]["segment_pct_under"] is not None

    def test_four_comps_insufficient(self):
        """4 comps (< 5) → no fair_value, 'Too few comps' message."""
        deals = [make_deal("Yorkville", 1, 2000 + i * 50) for i in range(4)]
        result = compute_segment_fair_value(deals)
        for d in result:
            assert d["segment_fair_value"] is None
            assert d["comp_message"] == "Too few comps"

    def test_multiple_segments_isolated(self):
        """Different neighbourhood/beds groups each get own fair_value."""
        deals = (
            [make_deal("Liberty Village", 1, 2000 + i * 50) for i in range(5)] +
            [make_deal("Liberty Village", 2, 3000 + i * 100) for i in range(5)] +
            [make_deal("Queen West", 1, 2200 + i * 50) for i in range(5)]
        )
        result = compute_segment_fair_value(deals)
        # Each 1BR Liberty Village deal: median of 5 prices → same fv
        lv_1br = [d for d in result if d["neighbourhood"] == "Liberty Village" and d["beds"] == 1]
        qw_1br = [d for d in result if d["neighbourhood"] == "Queen West" and d["beds"] == 1]
        lv_2br = [d for d in result if d["neighbourhood"] == "Liberty Village" and d["beds"] == 2]
        assert lv_1br[0]["segment_fair_value"] == lv_1br[1]["segment_fair_value"]
        assert lv_1br[0]["segment_fair_value"] != qw_1br[0]["segment_fair_value"]
        assert lv_1br[0]["segment_fair_value"] != lv_2br[0]["segment_fair_value"]

    def test_pct_under_calculated(self):
        """pct_under is computed from segment fair_value, not global."""
        deals = [
            make_deal("King West", 1, 1900),
            make_deal("King West", 1, 2000),
            make_deal("King West", 1, 2100),
            make_deal("King West", 1, 2000),
            make_deal("King West", 1, 2000),
        ]
        result = compute_segment_fair_value(deals)
        # median = 2000, first deal priced 1900 → (2000-1900)/2000*100 = 5.0%
        assert result[0]["segment_pct_under"] == 5.0

    def test_empty_list(self):
        result = compute_segment_fair_value([])
        assert result == []


class TestFairValueWithFallback:
    def test_exact_segment_no_fallback_needed(self):
        """When exact segment has 5+ comps, fallback not used."""
        deals = [make_deal("Distillery", 1, 2000 + i * 50) for i in range(5)]
        result = compute_fair_value_with_fallback(deals)
        for d in result:
            assert d["segment_fair_value"] is not None
            assert "nearby" not in d.get("comp_message", "")

    def test_narrow_segment_falls_back_to_beds_only(self):
        """Single neighbourhood with < 5 comps falls back to broader beds-only segment."""
        # 3 Queen West 1BRs + 7 King West 1BRs (same beds)
        deals = (
            [make_deal("Queen West", 1, 2000 + i * 50) for i in range(3)] +
            [make_deal("King West", 1, 2000 + i * 50) for i in range(7)]
        )
        result = compute_fair_value_with_fallback(deals)
        qw_deals = [d for d in result if d["neighbourhood"] == "Queen West"]
        # All 10 1BRs in beds segment → median computed
        # First Queen West deal should get beds-level fair_value
        assert qw_deals[0]["segment_fair_value"] is not None
        assert "nearby" in qw_deals[0]["comp_message"]

    def test_no_comps_at_all(self):
        """No neighbourhood/beds combinations meet threshold → all 'Too few comps'."""
        deals = [make_deal("Unknown Hood", 1, 2000)]
        result = compute_fair_value_with_fallback(deals)
        assert result[0]["segment_fair_value"] is None
        assert result[0]["comp_message"] == "Too few comps"

    def test_2br_segment(self):
        """2BR listings scored separately from 1BR."""
        deals = (
            [make_deal("Downtown", 1, 2000 + i * 50) for i in range(5)] +
            [make_deal("Downtown", 2, 3000 + i * 50) for i in range(5)]
        )
        result = compute_fair_value_with_fallback(deals)
        one_br = [d for d in result if d["beds"] == 1]
        two_br = [d for d in result if d["beds"] == 2]
        assert one_br[0]["segment_fair_value"] != two_br[0]["segment_fair_value"]


class TestCompCount:
    def test_comp_count_reflects_segment_size(self):
        """comp_count is the number of listings in the segment (including self)."""
        deals = [make_deal("Annex", 1, 2000 + i * 50) for i in range(6)]
        result = compute_segment_fair_value(deals)
        for d in result:
            assert d["comp_count"] == 6
