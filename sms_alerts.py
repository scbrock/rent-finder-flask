"""
SMS alerts via Twilio for Toronto Rent Deal Finder.

MC-284: Send SMS when a deal matches user's SMS subscription criteria.
"""

from __future__ import annotations
import os
from datetime import datetime, timezone

TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN  = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER', '')


def _require_creds():
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_FROM_NUMBER:
        raise RuntimeError(
            "Twilio credentials not configured. Set TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER in .env"
        )


def _get_client():
    _require_creds()
    from twilio.rest import Client
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def _build_sms_text(neighbourhood: str, price: float, beds: float,
                    pct_under: float, score: float, url: str) -> str:
    return (
        f"📉 Toronto Rent Deal!\n"
        f"{neighbourhood} {beds:.0f}BR ${price:,.0f}/mo "
        f"({pct_under:.0f}% under market, score {score:.0%})\n"
        f"Link: {url}"
    )


def send_sms_alert(to_number: str,
                   neighbourhood: str,
                   price: float,
                   beds: float,
                   pct_under: float,
                   score: float,
                   url: str) -> str:
    """
    Send an SMS alert for a deal via Twilio.
    Returns the Twilio message SID.
    Raises RuntimeError if Twilio credentials not configured.
    Raises Exception (Twilio errors) on failure.
    """
    body = _build_sms_text(neighbourhood, price, beds, pct_under, score, url)
    client = _get_client()
    message = client.messages.create(
        body=body,
        from_=TWILIO_FROM_NUMBER,
        to=to_number
    )
    return message.sid


def normalize_phone(phone: str) -> str:
    """Strip all non-digit characters, return E.164 format."""
    digits = ''.join(c for c in phone if c.isdigit())
    if len(digits) < 10:
        raise ValueError(f"Phone number must have at least 10 digits: {phone!r}")
    if len(digits) == 10:
        return f"+1{digits}"
    if digits.startswith('1') and len(digits) == 11:
        return f"+{digits}"
    return f"+{digits}"


def check_and_send_sms_alerts(min_score: float = 0.15) -> dict:
    """
    Check all active SMS subscriptions, find matching deals, send SMS alerts.
    Called by the cron job every 2 hours (via find_deals.py).

    A deal matches a subscription when:
      - listing score >= min_score (default 15%)
      - listing price <= subscription max_price (if set)
      - listing beds >= subscription min_beds (if set)
      - listing neighbourhood contains subscription neighbourhood (if set, case-insensitive)
      - subscription last_alerted IS NULL or > 1 hour ago

    Returns: {'sent': int, 'skipped': int, 'errors': list[str]}
    """
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_FROM_NUMBER:
        return {'sent': 0, 'skipped': 0, 'errors': ['Twilio not configured']}

    # Import from persist (avoids circular import)
    from persist import (
        get_active_sms_subscriptions,
        get_active_listings,
        update_sms_last_alerted,
    )
    import pandas as pd

    subs = get_active_sms_subscriptions()
    if not subs:
        return {'sent': 0, 'skipped': 0, 'errors': []}

    listings_df = get_active_listings(region=None)
    # Filter to deals: score >= min_score and score is not null
    deals_df = listings_df[
        listings_df['score'].notna() &
        (listings_df['score'] >= min_score)
    ]
    if deals_df.empty:
        return {'sent': 0, 'skipped': len(subs), 'errors': []}

    sent = 0
    skipped = 0
    errors = []

    for sub in subs:
        phone = sub['phone']
        max_price = sub.get('max_price')
        min_beds  = sub.get('min_beds')
        neighbourhood_filter = sub.get('neighbourhood') or ''

        # Filter deals by subscription criteria
        mask = pd.Series([True] * len(deals_df), index=deals_df.index)
        if max_price:
            mask &= (deals_df['price'] <= max_price)
        if min_beds:
            mask &= (deals_df['beds'] >= min_beds)
        if neighbourhood_filter:
            mask &= deals_df['neighborhood'].str.lower().str.contains(
                neighbourhood_filter.lower(), na=False
            )

        if mask.sum() == 0:
            skipped += 1
            continue

        matching = deals_df[mask].iloc[0]  # best (highest score) match

        try:
            send_sms_alert(
                to_number=normalize_phone(phone),
                neighbourhood=str(matching.get('neighborhood', 'Toronto')),
                price=float(matching['price']),
                beds=float(matching['beds']),
                pct_under=float(matching.get('pct_under', 0)),
                score=float(matching['score']),
                url=str(matching.get('url', ''))
            )
            update_sms_last_alerted(phone)
            sent += 1
        except Exception as exc:
            errors.append(f"SMS to {phone}: {exc}")

    return {'sent': sent, 'skipped': skipped, 'errors': errors}