def update_telegram_last_alerted(telegram_chat_id: str):
    conn = _get_conn()
    try:
        conn.execute("""
            UPDATE telegram_subscriptions
            SET last_alerted = strftime('%Y-%m-%dT%H:%M:%SZ','now')
            WHERE telegram_chat_id = ?
        """, (telegram_chat_id,))
        conn.commit()
    finally:
        conn.close()


# ── SMS Subscriptions ─────────────────────────────────────────────────────────

def upsert_sms_subscription(phone: str, email: str,
                              max_price: float = None,
                              min_beds: float = None,
                              neighbourhood: str = None) -> int:
    """
    Create or update an SMS subscription.

    Returns the sub_id.
    Raises if Twilio credentials not configured.
    """
    import os as _os
    if not _os.environ.get('TWILIO_ACCOUNT_SID') or not _os.environ.get('TWILIO_AUTH_TOKEN'):
        raise RuntimeError("Twilio credentials not configured")

    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO sms_subscriptions (phone, email, max_price, min_beds, neighbourhood)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                email         = excluded.email,
                max_price     = excluded.max_price,
                min_beds      = excluded.min_beds,
                neighbourhood = excluded.neighbourhood,
                active        = 1
        """, (phone, email, max_price, min_beds, neighbourhood))
        conn.commit()
        row = conn.execute(
            "SELECT sub_id FROM sms_subscriptions WHERE phone = ?", (phone,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_sms_subscription(phone: str) -> Optional[dict]:
    """Return SMS subscription dict or None."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM sms_subscriptions WHERE phone = ? AND active = 1",
            (phone,)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in conn.execute(
            "SELECT * FROM sms_subscriptions WHERE 1=0"
        ).description]
        return dict(zip(cols, row))
    finally:
        conn.close()


def get_active_sms_subscriptions() -> list[dict]:
    """Return all active SMS subscriptions."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM sms_subscriptions WHERE active = 1"
        ).fetchall()
        cols = [d[0] for d in conn.execute(
            "SELECT * FROM sms_subscriptions WHERE 1=0"
        ).description]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def deactivate_sms_subscription(phone: str):
    """Deactivate an SMS subscription."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE sms_subscriptions SET active = 0 WHERE phone = ?",
            (phone,)
        )
        conn.commit()
    finally:
        conn.close()


def update_sms_last_alerted(phone: str):
    """Update last_alerted timestamp for an SMS subscription."""
    conn = _get_conn()
    try:
        conn.execute("""
            UPDATE sms_subscriptions
            SET last_alerted = strftime('%Y-%m-%dT%H:%M:%SZ','now')
            WHERE phone = ?
        """, (phone,))
        conn.commit()
    finally:
        conn.close()


# Import helper from this module for use in check_and_send_sms_alerts
def _get_pending_sms_subscriptions(min_score: float = 0.0) -> list[dict]:
    """
    Return SMS subscriptions that are due for an alert.
    A subscription is due when:
      - active = 1
      - last_alerted IS NULL OR last_alerted < (now - 1 hour ago)
    """
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT s.*, l.neighborhood, l.price, l.beds, l.score, l.pct_under, l.url,
                   l.listing_id
            FROM sms_subscriptions s
            LEFT JOIN listings l ON l.listing_id = (
                SELECT listing_id FROM listings
                WHERE score IS NOT NULL AND score >= ?
                ORDER BY score DESC LIMIT 1
            )
            WHERE s.active = 1
              AND (s.last_alerted IS NULL
                   OR s.last_alerted < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 hour'))
        """, (min_score,)).fetchall()
        cols = [d[0] for d in conn.execute(
            "SELECT * FROM sms_subscriptions WHERE 1=0"
        ).description]
        # Add joined columns
        extra = ['neighborhood', 'price', 'beds', 'score', 'pct_under', 'url', 'listing_id']
        all_cols = cols + extra
        return [dict(zip(all_cols, r)) for r in rows]
    finally:
        conn.close()