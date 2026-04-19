"""
Weekly digest email for rent finder users.

MC-275: Every Sunday at 8am, send digest to all users with status
"Open to moving" or "Actively looking".

Digest contains:
  - Top 5 deals this week matching their preference profile
  - Market summary (avg price by bed count vs last week)
  - New listings since last digest

No digest sent if 0 matching deals.
"""
from __future__ import annotations

import os, sqlite3, json
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

DATA_DIR = os.environ.get('RENT_DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
DB_PATH = os.path.join(DATA_DIR, 'listings.db')
LAST_DIGEST_FILE = os.path.join(DATA_DIR, 'last_digest_ts.txt')


# ── Datatypes ─────────────────────────────────────────────────────────────────

@dataclass
class DigestUser:
    profile_id: int
    email: str
    preferred_beds: str       # e.g. "2,3" or "" for any
    max_price: float
    neighbourhoods: str       # JSON list string
    status: str


@dataclass
class DigestDeal:
    listing_id: str
    title: str
    price: float
    beds: float
    neighborhood: str
    url: str
    score: float
    days_ago: int


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_eligible_users() -> list[DigestUser]:
    """Return users with status Open to moving or Actively looking."""
    conn = _get_db()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT profile_id, email, preferred_beds, max_price, neighbourhoods, status
        FROM user_profiles
        WHERE status IN ('Open to moving', 'Actively looking')
        AND email IS NOT NULL AND email != ''
    """).fetchall()
    conn.close()
    return [DigestUser(**dict(r)) for r in rows]


def get_last_digest_ts() -> datetime | None:
    """Return the timestamp of the last digest run, or None if never."""
    if not os.path.exists(LAST_DIGEST_FILE):
        return None
    try:
        with open(LAST_DIGEST_FILE, encoding='utf-8') as f:
            ts_str = f.read().strip()
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def save_digest_ts(ts: datetime) -> None:
    """Record the digest run timestamp."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LAST_DIGEST_FILE, 'w', encoding='utf-8') as f:
        f.write(ts.isoformat().replace('+00:00', 'Z'))


# ── Deal matching ──────────────────────────────────────────────────────────────

def get_top_deals(profile: DigestUser, limit: int = 5) -> list[DigestDeal]:
    """Return top-scoring active listings matching user preferences."""
    conn = _get_db()
    cur = conn.cursor()

    query = """
        SELECT listing_id, title, price, beds, neighborhood, url, score, days_ago
        FROM listings
        WHERE is_active = 1 AND score IS NOT NULL
    """
    params = []

    if profile.max_price and profile.max_price > 0:
        query += " AND price <= ?"
        params.append(profile.max_price)

    if profile.preferred_beds:
        bed_parts = [b.strip() for b in profile.preferred_beds.split(',') if b.strip()]
        if bed_parts:
            bed_list = ','.join('?' * len(bed_parts))
            query += f" AND CAST(beds AS INTEGER) IN ({bed_list})"
            params.extend(bed_parts)

    # Filter by neighbourhood if set
    if profile.neighbourhoods:
        try:
            neighbourhoods = json.loads(profile.neighbourhoods)
            if isinstance(neighbourhoods, list) and neighbourhoods:
                placeholders = ','.join('?' * len(neighbourhoods))
                query += f" AND neighborhood IN ({placeholders})"
                params.extend(neighbourhoods)
        except Exception:
            pass

    query += " ORDER BY score DESC LIMIT ?"
    params.append(limit)

    rows = cur.execute(query, params).fetchall()
    conn.close()
    return [
        DigestDeal(
            listing_id=r['listing_id'],
            title=r['title'] or '',
            price=r['price'],
            beds=r['beds'] or 0,
            neighborhood=r['neighborhood'] or '',
            url=r['url'] or '',
            score=r['score'] or 0,
            days_ago=r['days_ago'] or 0,
        )
        for r in rows
    ]


def get_new_listings_since(since_dt: datetime) -> list[DigestDeal]:
    """Return listings first_seen after since_dt (new this week)."""
    conn = _get_db()
    cur = conn.cursor()
    since_str = since_dt.isoformat().replace('+00:00', 'Z')
    rows = cur.execute("""
        SELECT listing_id, title, price, beds, neighborhood, url, score, days_ago
        FROM listings
        WHERE first_seen >= ? AND is_active = 1
        ORDER BY first_seen DESC
        LIMIT 20
    """, (since_str,)).fetchall()
    conn.close()
    return [
        DigestDeal(
            listing_id=r['listing_id'],
            title=r['title'] or '',
            price=r['price'],
            beds=r['beds'] or 0,
            neighborhood=r['neighborhood'] or '',
            url=r['url'] or '',
            score=r['score'] or 0,
            days_ago=r['days_ago'] or 0,
        )
        for r in rows
    ]


# ── Market summary ────────────────────────────────────────────────────────────

def get_market_summary() -> dict:
    """
    Return {bed_count: {'current_avg': float, 'prev_avg': float, 'count': int}}
    comparing this week vs last week from price_history.
    """
    conn = _get_db()
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    cur.execute("""
        SELECT
            CAST(p.beds AS INTEGER) as bed_count,
            AVG(p.price) as avg_price,
            COUNT(*) as cnt
        FROM price_history p
        JOIN listings l ON l.listing_id = p.listing_id
        WHERE p.ts >= ? AND l.is_active = 1
        GROUP BY CAST(p.beds AS INTEGER)
    """, (week_ago.isoformat().replace('+00:00', 'Z'),))
    current = {r['bed_count']: {'avg': r['avg_price'], 'cnt': r['cnt']} for r in cur.fetchall()}

    cur.execute("""
        SELECT
            CAST(p.beds AS INTEGER) as bed_count,
            AVG(p.price) as avg_price,
            COUNT(*) as cnt
        FROM price_history p
        JOIN listings l ON l.listing_id = p.listing_id
        WHERE p.ts >= ? AND p.ts < ?
        GROUP BY CAST(p.beds AS INTEGER)
    """, (two_weeks_ago.isoformat().replace('+00:00', 'Z'), week_ago.isoformat().replace('+00:00', 'Z')))
    prev = {r['bed_count']: {'avg': r['avg_price'], 'cnt': r['cnt']} for r in cur.fetchall()}

    conn.close()

    result = {}
    for bc in set(list(current.keys()) + list(prev.keys())):
        result[bc] = {
            'current_avg': current.get(bc, {}).get('avg', 0),
            'prev_avg': prev.get(bc, {}).get('avg', 0),
            'count': current.get(bc, {}).get('cnt', 0),
        }
    return result


# ── Email building ─────────────────────────────────────────────────────────────

def build_digest_html(
    email: str,
    deals: list[DigestDeal],
    market_summary: dict,
    new_listings: list[DigestDeal],
    base_url: str = 'https://rentfinder.com',
) -> str:
    """Build HTML digest email body."""
    deal_rows = ''
    for d in deals:
        beds_label = f"{int(d.beds)}" if d.beds else "?"
        deal_rows += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;">
            <a href="{d.url}" style="color:#2d6a4f;font-weight:600;text-decoration:none;">{d.title[:60]}</a>
          </td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{beds_label}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;color:#2d6a4f;font-weight:700;">${d.price:,.0f}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">
            <span style="background:#d4edda;color:#155724;padding:2px 8px;border-radius:12px;font-size:0.8rem;font-weight:700;">{d.score:.0%}</span>
          </td>
        </tr>"""

    market_rows = ''
    for bc in sorted(market_summary.keys()):
        s = market_summary[bc]
        diff = s['current_avg'] - s['prev_avg']
        diff_pct = (diff / s['prev_avg'] * 100) if s['prev_avg'] else 0
        arrow = '↑' if diff > 0 else ('↓' if diff < 0 else '→')
        market_rows = ''
    for bc in sorted(market_summary.keys()):
        s = market_summary[bc]
        diff = s['current_avg'] - s['prev_avg']
        diff_pct = (diff / s['prev_avg'] * 100) if s['prev_avg'] else 0
        arrow = '↑' if diff > 0 else ('↓' if diff < 0 else '→')
        diff_color = '#d32f2f' if diff > 0 else ('#2d6a4f' if diff < 0 else '#888')
        market_rows += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;">{int(bc)} bed</td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;font-weight:600;">${s['current_avg']:,.0f}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;color:{diff_color};">{arrow} {abs(diff_pct):.1f}%</td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;font-size:0.8rem;color:#888;">{s['count']} listings</td>
        </tr>"""

    new_rows = ''
    for n in new_listings[:10]:
        new_rows += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;">
            <a href="{n.url}" style="color:#2d6a4f;text-decoration:none;">{n.title[:50]}</a>
          </td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;">${n.price:,.0f}</td>
        </tr>"""

    deal_count = len(deals)
    unsubscribe_url = f"{base_url}/alerts?email={email}"

    market_section = ""
    if market_rows:
        market_section = f"""
    <h3 style="color:#2d6a4f;margin:0 0 12px;font-size:1rem;">📊 Market Summary vs Last Week</h3>
    <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
      <thead>
        <tr style="background:#f8f9fa;">
          <th style="padding:8px;text-align:left;font-size:0.75rem;color:#888;text-transform:uppercase;">Type</th>
          <th style="padding:8px;font-size:0.75rem;color:#888;text-transform:uppercase;text-align:right;">Avg Now</th>
          <th style="padding:8px;font-size:0.75rem;color:#888;text-transform:uppercase;text-align:right;">Change</th>
          <th style="padding:8px;font-size:0.75rem;color:#888;text-transform:uppercase;text-align:right;">Listings</th>
        </tr>
      </thead>
      <tbody>{market_rows}</tbody>
    </table>"""

    new_section = ""
    if new_rows:
        new_section = f"""
    <h3 style="color:#2d6a4f;margin:0 0 12px;font-size:1rem;">🆕 New Listings This Week</h3>
    <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
      <thead>
        <tr style="background:#f8f9fa;">
          <th style="padding:8px;text-align:left;font-size:0.75rem;color:#888;text-transform:uppercase;">Listing</th>
          <th style="padding:8px;font-size:0.75rem;color:#888;text-transform:uppercase;text-align:right;">Price</th>
        </tr>
      </thead>
      <tbody>{new_rows}</tbody>
    </table>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Your Toronto Rent Digest</title></head>
<body style="font-family:-apple-system,sans-serif;max-width:640px;margin:0 auto;padding:20px;color:#222;">
  <div style="background:#2d6a4f;color:white;padding:20px 24px;border-radius:8px 8px 0 0;">
    <h2 style="margin:0">📬 Your Toronto Rent Digest</h2>
    <p style="margin:8px 0 0;font-size:0.95rem;">{deal_count} deal{'s' if deal_count != 1 else ''} found matching your criteria this week.</p>
  </div>
  <div style="border:1px solid #ddd;border-top:none;padding:20px 24px;border-radius:0 0 8px 8px;">

    <!-- Top Deals -->
    <h3 style="color:#2d6a4f;margin:0 0 12px;font-size:1rem;">🏆 Top Deals This Week</h3>
    <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
      <thead>
        <tr style="background:#f8f9fa;">
          <th style="padding:8px;text-align:left;font-size:0.75rem;color:#888;text-transform:uppercase;">Listing</th>
          <th style="padding:8px;font-size:0.75rem;color:#888;text-transform:uppercase;text-align:center;">Beds</th>
          <th style="padding:8px;font-size:0.75rem;color:#888;text-transform:uppercase;text-align:right;">Price</th>
          <th style="padding:8px;font-size:0.75rem;color:#888;text-transform:uppercase;text-align:center;">Score</th>
        </tr>
      </thead>
      <tbody>{deal_rows}</tbody>
    </table>

    <!-- Market Summary -->
    {market_section}

    <!-- New Listings -->
    {new_section}

    <div style="margin-top:24px;padding-top:16px;border-top:1px solid #eee;text-align:center;">
      <a href="{base_url}/shortlist" style="display:inline-block;background:#2d6a4f;color:white;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;margin-right:8px;">View Shortlist →</a>
      <a href="{base_url}/profile" style="display:inline-block;background:#f8f9fa;color:#555;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;margin-right:8px;">Update Profile</a>
      <br><br>
      <a href="{unsubscribe_url}" style="color:#888;font-size:0.8rem;text-decoration:underline;">Unsubscribe from digest emails</a>
    </div>
  </div>
</body>
</html>"""


def build_digest_subject(deal_count: int) -> str:
    """Build the digest email subject line."""
    return f"Your Toronto rent digest — {deal_count} deals found matching your criteria"


# ── Send ─────────────────────────────────────────────────────────────────────

def _get_sg_client():
    from sendgrid import SendGridAPIClient
    api_key = os.environ.get('SENDGRID_API_KEY', '')
    if not api_key:
        raise RuntimeError("SENDGRID_API_KEY environment variable not set")
    return SendGridAPIClient(api_key)


def send_digest_email(to_email: str, html_body: str, subject: str) -> None:
    """Send digest email via SendGrid."""
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail

    sg = _get_sg_client()
    mail = Mail(
        from_email=os.environ.get('FROM_EMAIL', 'alerts@rentfinder.com'),
        to_emails=to_email,
        subject=subject,
        plain_text_content='Your Toronto Rent Digest is available — view in your browser.',
        html_content=html_body,
    )
    sg.send(mail)


# ── Main digest runner ────────────────────────────────────────────────────────

def send_weekly_digest(base_url: str = 'https://rentfinder.com') -> dict:
    """
    Run the weekly digest for all eligible users.

    Returns dict with stats: users_processed, emails_sent, skipped_no_deals, errors
    """
    eligible = get_eligible_users()
    last_digest = get_last_digest_ts()
    # Use Monday of this week as proxy for "since last week" if no prior digest
    if last_digest:
        since_dt = last_digest
    else:
        now = datetime.now(timezone.utc)
        since_dt = now - timedelta(days=7)

    stats = {'users_processed': 0, 'emails_sent': 0, 'skipped_no_deals': 0, 'errors': []}
    new_listings = get_new_listings_since(since_dt)
    market_summary = get_market_summary()

    for user in eligible:
        try:
            deals = get_top_deals(user, limit=5)
            if not deals:
                stats['skipped_no_deals'] += 1
                continue

            html = build_digest_html(
                email=user.email,
                deals=deals,
                market_summary=market_summary,
                new_listings=new_listings,
                base_url=base_url,
            )
            subject = build_digest_subject(len(deals))
            send_digest_email(user.email, html, subject)
            stats['emails_sent'] += 1

        except Exception as e:
            stats['errors'].append(f"{user.email}: {str(e)}")

        stats['users_processed'] += 1

    # Record digest run
    save_digest_ts(datetime.now(timezone.utc))
    return stats