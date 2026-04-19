"""
Context-aware fair value computation for Toronto Rent Deal Finder.
MC-261: Fair value is relative to the segment the user is searching,
not a global average.

compute_segment_fair_value(deals: list[dict]) -> list[dict]
  Each deal gets a segment-aware fair_value computed from listings that
  share the same (neighbourhood, beds) combination in the CURRENT
  filtered result set.

  Rules:
  - Group filtered listings by (neighbourhood, beds).
  - Require >= 5 listings in a segment to compute a valid fair_value.
  - Fewer than 5 listings → "Too few comps" shown instead.
  - % under market is recomputed from the segment fair_value.
  - Comp count is included in each deal dict.
"""

from __future__ import annotations
from collections import defaultdict
import math


MIN_COMPS = 5


def compute_segment_fair_value(deals: list[dict]) -> list[dict]:
    """
    For each deal in the filtered list, compute a segment-aware fair_value
    from the other listings in the same (neighbourhood, beds) group.

    Adds / overwrites in each deal dict:
      segment_fair_value  (float or None)
      segment_pct_under   (float or None)
      segment_score       (float or None)
      comp_count          (int)
      comp_message        (str, human-readable)
    """
    if not deals:
        return deals

    # Build segments: (neighbourhood, beds) -> list of prices
    segments: dict[tuple, list[dict]] = defaultdict(list)
    for d in deals:
        key = (_norm_neighbourhood(d.get("neighbourhood", "")), _norm_beds(d.get("beds")))
        if key[0] and key[1] is not None:
            segments[key].append(d)

    # Compute median price per segment
    segment_fv: dict[tuple, float] = {}
    for key, members in segments.items():
        prices = [m["price"] for m in members if isinstance(m.get("price"), (int, float)) and m["price"] > 0]
        if len(prices) >= MIN_COMPS:
            sorted_prices = sorted(prices)
            n = len(sorted_prices)
            if n % 2 == 0:
                segment_fv[key] = (sorted_prices[n // 2 - 1] + sorted_prices[n // 2]) / 2
            else:
                segment_fv[key] = sorted_prices[n // 2]

    # Map each deal to its segment fair_value
    for d in deals:
        key = (_norm_neighbourhood(d.get("neighbourhood", "")), _norm_beds(d.get("beds")))
        fv = segment_fv.get(key)
        comps = len(segments.get(key, []))

        if fv is not None and comps >= MIN_COMPS:
            d["segment_fair_value"] = fv
            pct_under = (fv - d["price"]) / fv * 100
            d["segment_pct_under"] = round(pct_under, 1)
            # Normalised score: 0–1 where 1 = best deal in segment
            max_pct = max((segment_fv.get(k) - p) / segment_fv.get(k) * 100
                          for k, members in segments.items()
                          for p in [m["price"] for m in members
                                    if isinstance(m.get("price"), (int, float))]
                          if segment_fv.get(k) and p > 0) or 1
            d["segment_score"] = round(pct_under / max_pct, 3) if pct_under > 0 else 0
            d["comp_count"] = comps
            d["comp_message"] = f"{pct_under:.1f}% under market ({comps} comps)"
        else:
            d["segment_fair_value"] = None
            d["segment_pct_under"] = None
            d["segment_score"] = None
            d["comp_count"] = comps
            d["comp_message"] = "Too few comps" if comps < MIN_COMPS else "—"

    return deals


def _norm_neighbourhood(n: str) -> str:
    """Normalise neighbourhood key for grouping."""
    if not n:
        return ""
    return n.strip()[:80].lower()


def _norm_beds(beds) -> float | None:
    """Normalise beds to a numeric value."""
    if beds is None:
        return None
    try:
        v = float(beds)
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None


# ── Broader-segment fallback ────────────────────────────────────────────────────

def _broader_key(key: tuple) -> tuple | None:
    """Return a broader segment key: drop neighbourhood, keep beds only."""
    _, beds = key
    if beds is not None:
        return ("_all_downtown", beds)
    return None


def compute_fair_value_with_fallback(deals: list[dict]) -> list[dict]:
    """
    Two-pass fair value:
    Pass 1 — exact (neighbourhood, beds) segment, min 5 comps
    Pass 2 — broader (beds only) segment, min 5 comps
    Listings with no valid segment get "Too few comps" message.
    """
    if not deals:
        return deals

    # Pass 1: exact segments
    deals = compute_segment_fair_value(deals)
    unmet = [d for d in deals if d.get("segment_fair_value") is None]

    if not unmet:
        return deals

    # Pass 2: build beds-only segments from original deal list
    beds_segments: dict[tuple, list[dict]] = defaultdict(list)
    for d in deals:
        beds = _norm_beds(d.get("beds"))
        if beds is not None:
            beds_segments[(beds,)].append(d)

    beds_fv: dict[tuple, float] = {}
    for key, members in beds_segments.items():
        beds = key[0]
        prices = [m["price"] for m in members
                  if isinstance(m.get("price"), (int, float)) and m["price"] > 0]
        if len(prices) >= MIN_COMPS:
            sorted_prices = sorted(prices)
            n = len(sorted_prices)
            if n % 2 == 0:
                beds_fv[key] = (sorted_prices[n // 2 - 1] + sorted_prices[n // 2]) / 2
            else:
                beds_fv[key] = sorted_prices[n // 2]

    # Fill fallback for unmet listings
    for d in unmet:
        beds = _norm_beds(d.get("beds"))
        if beds is not None:
            key = (beds,)
            fv = beds_fv.get(key)
            comps = len(beds_segments.get(key, []))
            if fv is not None and comps >= MIN_COMPS:
                pct_under = (fv - d["price"]) / fv * 100
                d["segment_fair_value"] = fv
                d["segment_pct_under"] = round(pct_under, 1)
                d["comp_count"] = comps
                d["comp_message"] = (
                    f"{pct_under:.1f}% under market ({comps} nearby 1BRs used)"
                )
            else:
                d["segment_fair_value"] = None
                d["segment_pct_under"] = None
                d["comp_count"] = comps
                d["comp_message"] = "Too few comps"
        else:
            d["comp_message"] = "—"

    return deals
