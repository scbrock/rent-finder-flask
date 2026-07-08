"""
Price drop alert emails via SendGrid.

MC-272: When a shortlisted listing drops in price, send an email notification.
"""
Price drop alert emails via SendGrid.

MC-272: When a shortlisted listing drops in price, send an email notification.
MC-326: Saved-search notify-on-match digest emails (one per opted-in search,
       listing the new listings that match the user's filter combo).
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


# ── Saved-Search Match Digest (MC-326) ──────────────────────────────────────

def _esc(s):
    """HTML-escape a string for safe inclusion in email bodies."""
    if s is None:
        return ''
    return (str(s)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def _build_saved_search_match_html(search_name: str, matches: list[dict]) -> str:
    """
    HTML body for a saved-search-match digest email. Each match is a listing
    row with: thumbnail (if image_url), address (price/beds/baths/neighborhood
    inline), % under market, deal score, link.
    """
    rows_html = []
    for m in matches:
        address = m.get('address') or m.get('neighborhood') or m.get('title') or 'Listing'
        price = m.get('price') or 0
        beds = m.get('beds')
        baths = m.get('baths')
        neighborhood = m.get('neighborhood') or ''
        url = m.get('url') or m.get('link') or '#'
        pct = m.get('pct_under')
        score = m.get('score')
        image = m.get('image_url') or ''
        row = f"""
        <tr>
          <td style=\"padding:14px 16px;border-bottom:1px solid #eee;\">
            <table style=\"width:100%;border-collapse:collapse;\">
              <tr>
                {('<td style=\"width:96px;padding-right:12px;vertical-align:top;\"><img src=\"' + _esc(image) + '\" alt=\"\" style=\"width:96px;height:72px;object-fit:cover;border-radius:4px;\"></td>') if image else ''}
                <td style=\"vertical-align:top;\">
                  <div style=\"font-weight:600;color:#222;font-size:1rem;margin-bottom:4px;\">{_esc(address)}</div>
                  <div style=\"font-size:0.85rem;color:#555;margin-bottom:6px;\">
                    ${price:,.0f}/mo
                    {(' · ' + _esc(str(beds)) + ' bd') if beds is not None else ''}
                    {(' · ' + _esc(str(baths)) + ' ba') if baths is not None else ''}
                    {(' · ' + _esc(neighborhood)) if neighborhood else ''}
                  </div>
                  <div style=\"font-size:0.78rem;color:#888;\">
                    {('Under market: ' + _esc(f\"{pct:.0%}\")) if pct is not None else ''}
                    {(' · Deal score: ' + _esc(f\"{score:.0%}\")) if score is not None else ''}
                  </div>
                </td>
              </tr>
            </table>
            <div style=\"margin-top:8px;text-align:right;\">
              <a href=\"{_esc(url)}\" style=\"color:#2d6a4f;font-weight:600;font-size:0.85rem;text-decoration:none;\">View listing →</a>
            </div>
          </td>
        </tr>"""
        rows_html.append(row)

    rows_joined = '\n'.join(rows_html) if rows_html else '<tr><td style="padding:20px;color:#888;">No new matches yet — we\'ll keep watching.</td></tr>'
    n = len(matches)
    return f"""<!DOCTYPE html>
<html>
<head><meta charset=\"utf-8\"><title>New matches for {search_name}</title></head>
<body style=\"font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#222;\">
  <div style=\"background:#2d6a4f;color:white;padding:20px 24px;border-radius:8px 8px 0 0;\">
    <h2 style=\"margin:0\">🔔 New matches for your search</h2>
    <p style=\"margin:8px 0 0;\">{n} new {'listing' if n == 1 else 'listings'} match \"{_esc(search_name)}\"</p>
  </div>
  <table style=\"width:100%;border:1px solid #ddd;border-top:none;border-collapse:collapse;\">
    {rows_joined}
  </table>
  <div style=\"background:#f8f9fa;padding:16px 24px;font-size:0.78rem;color:#888;border-radius:0 0 8px 8px;border:1px solid #ddd;border-top:none;\">
    You're receiving this because you saved this search on the Rent Finder
    dashboard. Manage your saved searches or turn off notifications on the
    <a href=\"https://rent-finder-flask.onrender.com/saved-searches\" style=\"color:#2d6a4f;\">Saved Searches</a> page.
  </div>
</body>
</html>"""


def _build_saved_search_match_text(search_name: str, matches: list[dict]) -> str:
    """Plain-text fallback for the same digest (used by older clients)."""
    lines = [f"New matches for your saved search \"{search_name}\" ({len(matches)} found):", ""]
    for m in matches:
        address = m.get('address') or m.get('neighborhood') or m.get('title') or 'Listing'
        price = m.get('price') or 0
        beds = m.get('beds')
        neighborhood = m.get('neighborhood') or ''
        url = m.get('url') or m.get('link') or '#'
        lines.append(f"- {address}  |  ${price:,.0f}/mo  |  {beds or '?'} bd  |  {neighborhood}")
        lines.append(f"  {url}")
    lines.append("")
    lines.append("Manage your saved searches on https://rent-finder-flask.onrender.com/saved-searches")
    return "\n".join(lines)


def send_saved_search_alert_email(to_email: str, search_name: str, matches: list[dict], unsub_url: str = "") -> bool:
    """
    Send a saved-search-match digest email. Returns True if SendGrid accepted
    the request, False otherwise (including missing API key / malformed input
    / SendGrid API error).

    MC-326: invoked from persist.check_and_send_saved_search_alerts() for each
    saved search with notify_on_match=1 and at least one new matching listing.
    """
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail

    if not to_email or '@' not in to_email:
        return False
    if not matches:
        return False

    html = _build_saved_search_match_html(search_name, matches)
    text = _build_saved_search_match_text(search_name, matches)
    n = len(matches)
    subject = f"\U0001F514 {n} new {'listing matches' if n != 1 else 'listing matches'} your search: {search_name}"

    try:
        sg = _get_sg_client()
    except Exception:
        return False
    try:
        mail = Mail(
            from_email=os.environ.get('FROM_EMAIL', 'alerts@rentfinder.com'),
            to_emails=to_email,
            subject=subject,
            plain_text_content=text,
            html_content=html,
        )
        response = sg.send(mail)
        return bool(response) and 200 <= response.status_code < 300
    except Exception:
        return False