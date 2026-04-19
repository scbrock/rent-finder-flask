"""
MC-274: Similar listing recommendations.
Scored filter query on SQLite — no ML required.
"""
from __future__ import annotations

import os, sqlite3
from dataclasses import dataclass

DATA_DIR = os.environ.get('RENT_DATA_DIR',
                          os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
DB_PATH = os.path.join(DATA_DIR, 'listings.db')


# ── Datatypes ─────────────────────────────────────────────────────────────────

@dataclass
class SimilarListing:
    listing_id: str
    title: str
    price: float
    price_fmt: str
    beds: float
    neighborhood: str
    url: str
    score: float
    final_score: float
    similarity_explanation: str


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _profile_from_listings(listing_ids: list[str]) -> dict | None:
    """Build a similarity profile from a list of listing IDs. Returns None if no listings found."""
    if not listing_ids:
        return None
    placeholders = ','.join('?' * len(listing_ids))
    conn = _get_db()
    cur = conn.cursor()
    rows = cur.execute(f"""
        SELECT beds, price, neighborhood, score, final_score
        FROM listings
        WHERE listing_id IN ({placeholders}) AND is_active = 1
    """, listing_ids).fetchall()
    conn.close()
    if not rows:
        return None

    prices = [r['price'] for r in rows if r['price'] is not None]
    beds_vals = [r['beds'] for r in rows if r['beds'] is not None]
    hoods = {r['neighborhood'] for r in rows if r['neighborhood']}
    scores = [r['final_score'] or r['score'] or 0
              for r in rows if r['final_score'] or r['score']]

    return {
        'avg_price': sum(prices) / len(prices) if prices else 0,
        'min_beds': min(beds_vals) if beds_vals else 0,
        'max_beds': max(beds_vals) if beds_vals else 99,
        'neighborhoods': hoods,
        'avg_score': sum(scores) / len(scores) if scores else 0,
    }


def get_similar_for_shortlist(email: str, limit: int = 5) -> list[SimilarListing]:
    """
    Get up to `limit` listings similar to the user's shortlist.
    Uses scored ranking: neighborhood match (3pt) + price proximity (2pt) + score bracket (1pt).
    Excludes listings already shortlisted by this email.
    """
    # Get user's shortlisted listing IDs
    conn = _get_db()
    cur = conn.cursor()
    saved_rows = cur.execute(
        "SELECT listing_id FROM saved_listings WHERE email = ?",
        (email,)
    ).fetchall()
    conn.close()

    shortlisted_ids = [r['listing_id'] for r in saved_rows]
    if not shortlisted_ids:
        return []

    profile = _profile_from_listings(shortlisted_ids)
    if not profile:
        return []

    avg_price = profile['avg_price']
    avg_score = profile['avg_score']
    neighborhoods = profile['neighborhoods']
    mid_beds = (profile['min_beds'] + profile['max_beds']) / 2
    price_min = max(0, avg_price - 200)
    price_max = avg_price + 200
    score_min = max(0, avg_score - 0.10)

    # Build neighborhood-ranking ORDER BY inline (avoids param-count mismatch in ORDER BY)
    if neighborhoods:
        # Escape single quotes in neighborhood names for safe SQL inclusion
        escaped = [h.replace("'", "''") for h in neighborhoods]
        hood_list = ','.join(f"'{h}'" for h in escaped)
        hood_order_expr = f"CASE WHEN neighborhood IN ({hood_list}) THEN 3 ELSE 0 END"
    else:
        hood_order_expr = "0"

    order_by_clause = f"""
        {hood_order_expr}
        + CASE WHEN ABS(price - {avg_price}) <= 100 THEN 2
               WHEN ABS(price - {avg_price}) <= 200 THEN 1 ELSE 0 END
        + CASE WHEN final_score >= {score_min} AND final_score <= {avg_score + 0.20} THEN 1 ELSE 0 END
        DESC,
        ABS(price - {avg_price}) ASC
    """

    # Exclude shortlisted listings
    exclude_clause = ""
    exclude_params: list = []
    if shortlisted_ids:
        excl_placeholders = ','.join('?' * len(shortlisted_ids))
        exclude_clause = f" AND listing_id NOT IN ({excl_placeholders})"
        exclude_params = shortlisted_ids

    query = f"""
        SELECT listing_id, title, price, beds, neighborhood, url, score, final_score
        FROM listings
        WHERE is_active = 1
          AND ABS(beds - {mid_beds}) <= 0.5
          AND price >= {price_min} AND price <= {price_max}
          AND final_score >= {score_min}
          {exclude_clause}
        ORDER BY {order_by_clause}
        LIMIT ?
    """

    all_params: list = exclude_params + [limit]

    conn2 = _get_db()
    cur2 = conn2.cursor()
    rows = cur2.execute(query, all_params).fetchall()
    conn2.close()

    results = []
    for r in rows:
        parts = []
        if r['neighborhood'] and r['neighborhood'] in neighborhoods:
            parts.append(f"Same neighborhood ({r['neighborhood']})")
        price_diff = abs(r['price'] - avg_price)
        if price_diff <= 100:
            parts.append("Within $100 of your target price")
        elif price_diff <= 200:
            parts.append("Within $200 of your target price")

        explanation = f"Based on your saved listings — {' | '.join(parts[:2]) if parts else 'similar listing profile'}"

        results.append(SimilarListing(
            listing_id=r['listing_id'],
            title=r['title'] or '',
            price=r['price'],
            price_fmt=f"${r['price']:,.0f}",
            beds=r['beds'] or 0,
            neighborhood=r['neighborhood'] or '',
            url=r['url'] or '',
            score=r['score'] or 0,
            final_score=r['final_score'] or r['score'] or 0,
            similarity_explanation=explanation,
        ))

    return results


def get_similar_for_listing(listing_id: str, limit: int = 3) -> list[SimilarListing]:
    """
    Get up to `limit` listings similar to a specific listing (for detail page).
    Uses the listing's own attributes as the similarity profile:
    same bed count (±0.5), price within $200, similar neighborhood, similar score.
    """
    conn = _get_db()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT beds, price, neighborhood, score, final_score
        FROM listings
        WHERE listing_id = ? AND is_active = 1
    """, (listing_id,)).fetchall()
    conn.close()

    if not rows:
        return []

    r = rows[0]
    beds = r['beds'] if r['beds'] is not None else 0
    price = r['price']
    hood = r['neighborhood']
    avg_score = r['final_score'] or r['score'] or 0

    price_min = max(0, price - 200)
    price_max = price + 200
    score_min = max(0, avg_score - 0.10)
    score_max = avg_score + 0.20

    conn2 = _get_db()
    cur2 = conn2.cursor()

    # Inline hood escape for ORDER BY expression
    hood_escaped = hood.replace("'", "''") if hood else ''
    hood_order_expr = f"CASE WHEN neighborhood = '{hood_escaped}' THEN 3 ELSE 0 END"

    order_by_clause = f"""
        {hood_order_expr}
        + CASE WHEN ABS(price - {price}) <= 100 THEN 2
               WHEN ABS(price - {price}) <= 200 THEN 1 ELSE 0 END
        + CASE WHEN final_score >= {score_min} AND final_score <= {score_max} THEN 1 ELSE 0 END
        DESC,
        ABS(price - {price}) ASC
    """

    query = f"""
        SELECT listing_id, title, price, beds, neighborhood, url, score, final_score
        FROM listings
        WHERE is_active = 1
          AND listing_id != ?
          AND ABS(beds - {beds}) <= 0.5
          AND price >= {price_min} AND price <= {price_max}
          AND final_score >= {score_min}
        ORDER BY {order_by_clause}
        LIMIT ?
    """

    rows2 = cur2.execute(query, ([listing_id, limit])).fetchall()
    conn2.close()

    results = []
    for r2 in rows2:
        same_hood = r2['neighborhood'] == hood
        price_diff = abs(r2['price'] - price)
        price_cmp = 'more' if r2['price'] > price else 'less'

        explanation = (
            f"Based on this {int(r2['beds'])}BR listing — "
            f"{same_hood and 'same neighborhood' or 'similar neighborhood'}, "
            f"${price_diff:,.0f} {price_cmp} than this one"
        )

        results.append(SimilarListing(
            listing_id=r2['listing_id'],
            title=r2['title'] or '',
            price=r2['price'],
            price_fmt=f"${r2['price']:,.0f}",
            beds=r2['beds'] or 0,
            neighborhood=r2['neighborhood'] or '',
            url=r2['url'] or '',
            score=r2['score'] or 0,
            final_score=r2['final_score'] or r2['score'] or 0,
            similarity_explanation=explanation,
        ))

    return results