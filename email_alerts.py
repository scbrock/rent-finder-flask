"""
Price drop alert emails via SendGrid.

MC-272: When a shortlisted listing drops in price, send an email notification.
"""

import os
from datetime import datetime, timezone

# ── SendGrid Client ─────────────────────────────────────────────────────────

def _get_sg_client():
    from sendgrid import SendGridAPIClient
    api_key = os.environ.get('SENDGRID_API_KEY', '')
    if not api_key:
        raise RuntimeError("SENDGRID_API_KEY environment variable not set")
    return SendGridAPIClient(api_key)


# ── Email Templates ─────────────────────────────────────────────────────────

def _build_price_drop_html(address: str, old_price: float, new_price: float,
                           pct_under: float, score: float, listing_url: str) -> str:
    drop = old_price - new_price
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Price Drop Alert</title></head>
<body style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#222;">
  <div style="background:#2d6a4f;color:white;padding:20px 24px;border-radius:8px 8px 0 0;">
    <h2 style="margin:0">📉 Price Drop Alert</h2>
    <p style="margin:8px 0 0">One of your shortlisted listings just got cheaper.</p>
  </div>
  <div style="border:1px solid #ddd;border-top:none;padding:20px 24px;border-radius:0 0 8px 8px;">
    <h3 style="margin:0 0 8px">{address}</h3>
    <div style="display:flex;align-items:baseline;gap:16px;margin-bottom:16px;">
      <span style="font-size:2rem;font-weight:700;color:#2d6a4f;">${new_price:,.0f}<span style="font-size:1rem;font-weight:400;color:#555;">/mo</span></span>
      <span style="text-decoration:line-through;color:#999;font-size:1.1rem;">${old_price:,.0f}/mo</span>
      <span style="background:#d4edda;color:#155724;padding:2px 8px;border-radius:12px;font-size:0.8rem;font-weight:700;">↓ ${drop:,.0f}</span>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px;">
      <div style="background:#f8f9fa;padding:12px;border-radius:6px;text-align:center;">
        <div style="font-size:0.7rem;color:#888;text-transform:uppercase;letter-spacing:0.05em;">Deal Score</div>
        <div style="font-size:1.4rem;font-weight:700;color:#2d6a4f;">{score:.0%}</div>
      </div>
      <div style="background:#f8f9fa;padding:12px;border-radius:6px;text-align:center;">
        <div style="font-size:0.7rem;color:#888;text-transform:uppercase;letter-spacing:0.05em;">Under Market</div>
        <div style="font-size:1.4rem;font-weight:700;color:#2d6a4f;">{pct_under:.0f}%</div>
      </div>
    </div>
    <a href="{listing_url}" style="display:block;text-align:center;background:#2d6a4f;color:white;padding:14px;border-radius:6px;text-decoration:none;font-weight:600;font-size:0.95rem;margin-bottom:16px;">View Listing →</a>
    <p style="font-size:0.8rem;color:#888;margin:0;text-align:center;">You subscribed to price drop alerts for this listing.</p>
  </div>
</body>
</html>"""


def _build_price_drop_text(address: str, old_price: float, new_price: float,
                           pct_under: float, score: float, listing_url: str) -> str:
    drop = old_price - new_price
    return f"""Price Drop Alert — {address}

{address} is now ${new_price:,.0f}/mo (was ${old_price:,.0f}/mo — down ${drop:,.0f})

Deal Score: {score:.0%} | Under Market: {pct_under:.0f}%
Link: {listing_url}

You subscribed to price drop alerts for this listing.
"""


# ── Send ───────────────────────────────────────────────────────────────────

def send_price_drop_email(to_email: str,
                           listing_address: str,
                           old_price: float,
                           new_price: float,
                           pct_under: float,
                           score: float,
                           listing_url: str) -> None:
    """
    Send a price drop notification for a shortlisted listing.
    Uses SendGrid API (SENDGRID_API_KEY env var).
    """
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail

    html = _build_price_drop_html(listing_address, old_price, new_price, pct_under, score, listing_url)
    text = _build_price_drop_text(listing_address, old_price, new_price, pct_under, score, listing_url)

    sg = _get_sg_client()
    mail = Mail(
        from_email=os.environ.get('FROM_EMAIL', 'alerts@rentfinder.com'),
        to_emails=to_email,
        subject=f"📉 Price drop: {listing_address} is now ${new_price:,.0f}/mo",
        plain_text_content=text,
        html_content=html
    )
    sg.send(mail)


# ── Check & Send Price Drops (called after each scrape) ────────────────────

def check_and_send_price_drops(listings: list[dict], saved_email: str) -> list[str]:
    """
    After a scrape, check shortlisted listings for price drops.
    For each listing with current_price < price_at_save and no prior alert,
    send a price drop email and record the alert.

    listings: list of deal dicts from app.py load_deals (must include price, listing_id)
    saved_email: email of the user whose shortlist to check

    Returns list of listing_ids that had drop alerts sent.
    """
    from persist import (
        get_shortlisted_listings_with_prices,
        has_price_drop_alert,
        record_price_drop_alert,
    )

    sent = []
    shortlisted = {s['listing_id']: s for s in get_shortlisted_listings_with_prices(saved_email)}

    for deal in listings:
        lid = deal.get('listing_id')
        if lid not in shortlisted:
            continue
        saved = shortlisted[lid]
        price_at_save = saved.get('price_at_save')
        if price_at_save is None:
            continue
        current_price = deal.get('price')
        if current_price is None:
            continue
        if current_price >= price_at_save:
            continue  # no drop
        if has_price_drop_alert(saved_email, lid):
            continue  # already alerted

        # Send the alert
        send_price_drop_email(
            to_email=saved_email,
            listing_address=deal.get('neighborhood', deal.get('region', 'Unknown')),
            old_price=price_at_save,
            new_price=current_price,
            pct_under=deal.get('pct_under', 0),
            score=deal.get('score', 0),
            listing_url=deal.get('url', ''),
        )
        record_price_drop_alert(saved_email, lid, price_at_save, current_price)
        sent.append(lid)

    return sent