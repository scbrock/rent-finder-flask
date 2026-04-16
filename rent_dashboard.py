"""
MC-245: Rent Deal Finder — Streamlit Dashboard

Usage:
    streamlit run rent_dashboard.py

Or:
    python rent_dashboard.py
"""

import streamlit as st
import pandas as pd
import re
from pathlib import Path

st.set_page_config(
    page_title="Rent Deal Finder — Toronto",
    page_icon="🏠",
    layout="wide",
)

ROOT = Path(__file__).resolve().parent
DEALS_CSV = ROOT / "output" / "deals_output.csv"
SCRAPER_PY = ROOT / "scrape_kijiji.py"


# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=10 * 60)
def load_deals() -> pd.DataFrame:
    if not DEALS_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(DEALS_CSV)
    # Normalize column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    # Parse price
    if "price" in df.columns:
        df["price_num"] = (
            df["price"]
            .astype(str)
            .str.replace(r"[^0-9.]", "", regex=True)
            .replace("", "0")
            .astype(float)
        )
    # Parse beds
    if "beds" in df.columns:
        df["beds_num"] = (
            df["beds"]
            .astype(str)
            .str.extract(r"(\d+)")[0]
            .replace("", "0")
            .astype(float)
        )
    return df





def deal_score(row: pd.Series) -> float:
    """
    Score a deal: higher = better.
    Based on: price vs neighbourhood median, price/bed, amenities.
    """
    score = 0.0
    price = float(row.get("price_num", 0) or 0)
    beds = float(row.get("beds_num", 0) or 1)

    if price <= 0:
        return 0.0

    # Price-per-bed: lower is better (normalized)
    ppb = price / max(beds, 1)
    # Assume market avg ~$2000/bed → score penalizes expensive ppb
    ppp_score = max(0, 1 - (ppb / 4000)) * 40  # up to 40 pts

    # Base score for being under market
    under_market = float(row.get("under_market_pct", 0) or 0)
    market_score = min(under_market * 2, 40)  # up to 40 pts

    # Amenities bonus (has image, has location)
    amenity = 0
    if row.get("image_url"):
        amenity += 10
    if row.get("location"):
        amenity += 10

    score = ppp_score + market_score + amenity
    return round(score, 1)


def grade(score: float) -> str:
    if score >= 80:
        return "A"
    elif score >= 60:
        return "B"
    elif score >= 40:
        return "C"
    elif score >= 20:
        return "D"
    else:
        return "F"


# ── Sidebar ──────────────────────────────────────────────────────────────────

st.sidebar.header("Filters")

max_price = st.sidebar.slider(
    "Max Price ($/month)",
    min_value=500,
    max_value=8000,
    value=3500,
    step=100,
    help="Filter listings above this price",
)

min_beds = st.sidebar.selectbox(
    "Min Bedrooms",
    options=[0, 1, 2, 3, 4],
    index=0,
    format_func=lambda x: {0: "Studio / Bachelor", 1: "1+", 2: "2+", 3: "3+", 4: "4+"}[x],
)

neighborhood_filter = st.sidebar.text_input(
    "Neighborhood",
    value="",
    placeholder="e.g. North York, Etobicoke...",
    help="Filter by neighborhood name (partial match)",
)

grade_filter = st.sidebar.multiselect(
    "Min Grade",
    options=["A", "B", "C", "D", "F"],
    default=["A", "B", "C"],
)

sort_by = st.sidebar.radio(
    "Sort By",
    options=["Score ↓", "Price ↑", "Price ↓", "Beds ↑", "Neighborhood"],
)

refresh = st.sidebar.button("🔄 Refresh Data")

if refresh:
    st.cache_data.clear()
    st.rerun()


# ── Main ──────────────────────────────────────────────────────────────────────

st.title("🏠 Toronto Rental Deal Finder")
st.caption(f"Data source: Kijiji.ca · Last updated: {pd.read_csv(DEALS_CSV).iloc[0]['scraped_at'][:10] if DEALS_CSV.exists() and not pd.read_csv(DEALS_CSV).empty else 'unknown'}")

df = load_deals()

if df.empty:
    st.error("No deals found. Run `find_deals.py` first to scrape listings.")
    st.stop()

# Apply filters
mask = df["price_num"] <= max_price
if min_beds > 0:
    mask &= df["beds_num"] >= min_beds
if neighborhood_filter:
    mask &= df.get("location", pd.Series([""] * len(df))).str.contains(
        neighborhood_filter, case=False, na=False
    )
df_filt = df[mask].copy()

# Compute scores
df_filt["score"] = df_filt.apply(deal_score, axis=1)
df_filt["grade"] = df_filt["score"].apply(grade)

# Apply grade filter
if grade_filter:
    df_filt = df_filt[df_filt["grade"].isin(grade_filter)]

# Sort
sort_col = {
    "Score ↓": "score",
    "Price ↑": "price_num",
    "Price ↓": "price_num",
    "Beds ↑": "beds_num",
    "Neighborhood": "location",
}.get(sort_by, "score")
asc = sort_by in ("Price ↑", "Beds ↑")
df_filt = df_filt.sort_values(sort_col, ascending=asc)

# ── Stats row ────────────────────────────────────────────────────────────────

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Listings", len(df))
col2.metric("Filtered", len(df_filt))
col3.metric("Under-Market Deals", int(df_filt.get("is_deal", pd.Series([0] * len(df_filt))).sum()))
avg_price = int(df_filt["price_num"].mean()) if len(df_filt) else 0
col4.metric("Avg Price (filtered)", f"${avg_price:,}")

st.divider()

# ── Deal cards ─────────────────────────────────────────────────────────────

if df_filt.empty:
    st.warning("No listings match your filters. Try increasing max price or changing neighborhood.")
else:
    for i, row in df_filt.iterrows():
        col_grade, col_info, col_action = st.columns([1, 6, 2])

        g = row.get("grade", "F")
        grade_color = {"A": "🟢", "B": "🔵", "C": "⚪", "D": "🟡", "F": "🔴"}.get(g, "⚪")

        with col_grade:
            st.markdown(f"### {grade_color} `{g}`")
            st.caption(f"Score: {row.get('score', 0)}")

        with col_info:
            price = row.get("price_str") or row.get("price") or "$?"
            beds = row.get("beds") or "?"
            baths = row.get("baths") or "?"
            loc = get_neighborhood(df_filt, df_filt.index.get_loc(i))

            st.markdown(f"### {price} /month · {beds} bed {baths} bath")

            title = row.get("title", "")[:100]
            st.text(title)

            under_pct = row.get("under_market_pct", 0)
            if under_pct:
                st.success(f"💰 {under_pct:.0f}% below market")

        with col_action:
            url = row.get("url", "")
            if url:
                st.link_button("View on Kijiji →", url)
            st.caption(f"ID: {row.get('listing_id', '?')}")

        st.divider()
