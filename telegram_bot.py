"""
Telegram bot for Toronto Rent Deal Finder.
MC-283: Real-time deal alerts via Telegram.

Commands:
  /start       — greet user, ask for email to link
  /deals       — show top 5 deals right now
  /alerts      — show current alert settings
  /alert <n>   — set max price threshold (e.g. /alert 2500)
  /stop        — unsubscribe
  /help        — show help
"""

from __future__ import annotations

import os, sys, logging
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

# Ensure DATA_DIR for tests
os.environ.setdefault('RENT_DATA_DIR', os.path.join(os.path.dirname(__file__), 'data'))

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Deal Fetching (delegates to persist.DB_PATH at call time) ────────────────
def _fetch_top_deals(limit: int = 5, max_price = None,
                     min_beds = None) -> list[dict]:
    """Load active listings from SQLite, return top deals by score."""
    import sqlite3
    from persist import DB_PATH as _DB
    conn = sqlite3.connect(_DB)
    conn.row_factory = sqlite3.Row
    try:
        query = """
            SELECT listing_id, title, price, beds, baths, sqft, neighborhood,
                   region, url, fair_value, score, pct_under, days_ago
            FROM listings
            WHERE is_active = 1 AND score IS NOT NULL AND score > 0
        """
        params = []
        if max_price is not None:
            query += " AND price <= ?"
            params.append(max_price)
        if min_beds is not None:
            query += " AND beds >= ?"
            params.append(min_beds)
        query += " ORDER BY score DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _format_deal(deal: dict, rank: int) -> str:
    score_pct = (deal.get('score') or 0) * 100
    pct_under = deal.get('pct_under') or 0
    price = deal.get('price', 0)
    beds  = deal.get('beds', '?')
    nbhd  = deal.get('neighborhood') or 'Toronto'
    fv    = deal.get('fair_value') or 0
    url   = deal.get('url') or ''
    days  = deal.get('days_ago', 0)
    sqft  = deal.get('sqft')
    baths = deal.get('baths', '?')

    line1 = (f"#{rank} {nbhd} {beds}BR"
             + (f" {baths}Ba" if baths not in ('?', None) else '')
             + (f" {sqft:.0f}ft2" if sqft else ''))
    line2 = f"   💰 ${price:,.0f}/mo  (FV ${fv:,.0f})"
    line3 = f"   📉 {pct_under:.1f}% under market  |  Score {score_pct:.0f}/100"
    line4 = f"   📅 {days}d ago" + (f"  🔗 {url}" if url else "")
    return '\n'.join([line1, line2, line3, line4])


# ── Alert Matching ─────────────────────────────────────────────────────────────

def get_matching_deals_for_telegram(sub: dict, limit: int = 3) -> list[dict]:
    """Return deals matching a Telegram subscription's criteria."""
    return _fetch_top_deals(
        limit=limit,
        max_price=sub.get('max_price'),
        min_beds=sub.get('min_beds')
    )


# ── Telegram Message Builders ─────────────────────────────────────────────────

def build_alert_message(deals: list[dict]) -> str:
    if not deals:
        return "🎉 No new deals matching your criteria right now. Check back in a few hours!"
    header = f"🔔 *New Deals Found!* ({len(deals)} matching)\n"
    lines = [_format_deal(d, i+1) for i, d in enumerate(deals)]
    footer = ("\n_Sent by @TorRentDealsBot — /deals /alerts /stop_")
    return header + '\n\n'.join(lines) + footer


def build_deals_message(deals: list[dict]) -> str:
    if not deals:
        return "😕 No deals found right now. Try adjusting your filters."
    header = "🏠 *Top Toronto Deals Right Now*\n"
    lines  = [_format_deal(d, i+1) for i, d in enumerate(deals)]
    footer = ("\n_Limit 5 most recent. /alert <price> to set a max price alert._"
              "\n_/deals /alerts /stop_")
    return header + '\n\n'.join(lines) + footer


# ── Bot Handlers ──────────────────────────────────────────────────────────────

def start_bot():
    """Run the bot with polling (for standalone use)."""
    if not BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set in .env")
        return

    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, CommandHandler, MessageHandler,
        ContextTypes, filters,
    )
    from telegram.constants import ParseMode

    from persist import (
        upsert_telegram_subscription,
        get_telegram_subscription,
        deactivate_telegram_subscription,
        get_active_telegram_subscriptions,
        update_telegram_last_alerted,
    )

    app = Application.builder().token(BOT_TOKEN).build()

    async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        sub = get_telegram_subscription(chat_id)
        if sub and sub.get('email'):
            await update.message.reply_text(
                f"👋 Welcome back! You're linked to {sub['email']}.\n"
                "Your subscription is active.\n\n"
                "/deals — see top deals\n"
                "/alerts — your alert settings\n"
                "/alert <price> — set max price\n"
                "/stop — unsubscribe"
            )
        else:
            await update.message.reply_text(
                "🏠 *Toronto Rent Deal Finder*\n\n"
                "Get alerts when great deals match your criteria.\n\n"
                "To subscribe, send your email address:\n"
                "`myemail@example.com`\n\n"
                "/deals — preview top deals now\n"
                "/help — all commands"
            )
            ctx.user_data['awaiting_email'] = True

    async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "*Toronto Rent Deal Finder — Commands*\n\n"
            "/start — subscribe / resume\n"
            "/deals — top 5 deals right now\n"
            "/alerts — your alert settings\n"
            "/alert <max_price> — set max price (e.g. /alert 2500)\n"
            "/stop — unsubscribe\n"
            "/help — show this message"
        )

    async def deals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        sub = get_telegram_subscription(chat_id)
        max_price = sub.get('max_price') if sub else None
        deals_list = _fetch_top_deals(limit=5, max_price=max_price)
        text = build_deals_message(deals_list)
        await update.message.reply_text(text, parse_mode='Markdown')

    async def alerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        sub = get_telegram_subscription(chat_id)
        if not sub or not sub.get('email'):
            await update.message.reply_text(
                "📋 You don't have an active subscription.\n"
                "Send your email to get started."
            )
            return
        lines = [
            f"📧 Email: `{sub['email']}`",
            f"💰 Max price: ${sub['max_price']:,.0f}/mo" if sub.get('max_price') else "💰 Max price: any",
            f"🛏️  Min beds: {sub['min_beds']}" if sub.get('min_beds') else "🛏️  Min beds: any",
            f"📍 Neighbourhood: {sub['neighbourhood']}" if sub.get('neighbourhood') else "📍 Neighbourhood: any",
            f"✅ Active: yes" if sub.get('active') else "❌ Active: no",
        ]
        if sub.get('last_alerted'):
            lines.append(f"🕐 Last alert: {sub['last_alerted']}")
        await update.message.reply_text('\n'.join(lines))

    async def set_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        sub = get_telegram_subscription(chat_id)
        if not sub or not sub.get('email'):
            await update.message.reply_text(
                "Please /start first and enter your email to subscribe."
            )
            return

        if not ctx.args:
            await update.message.reply_text(
                "Usage: /alert <max_price>\n"
                "Example: /alert 2500"
            )
            return

        try:
            max_price = float(ctx.args[0])
            if max_price < 100:
                await update.message.reply_text("Max price must be at least $100.")
                return
        except ValueError:
            await update.message.reply_text("Please enter a valid number.\nExample: /alert 2500")
            return

        upsert_telegram_subscription(
            chat_id,
            sub['email'],
            max_price=max_price,
            min_beds=sub.get('min_beds'),
            neighbourhood=sub.get('neighbourhood'),
        )
        await update.message.reply_text(
            f"✅ Alert updated! I'll notify you when listings drop below ${max_price:,.0f}/mo.\n\n"
            "/alerts — check your settings\n"
            "/deals — see current deals"
        )

    async def stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        deactivate_telegram_subscription(chat_id)
        await update.message.reply_text(
            "❌ Unsubscribed. You'll no longer receive deal alerts.\n"
            "/start to subscribe again."
        )

    async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        email = update.message.text.strip()

        import re
        email_pattern = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
        if not email_pattern.match(email):
            await update.message.reply_text(
                "That doesn't look like a valid email. Please try again:\n"
                "`myemail@example.com`"
            )
            return

        upsert_telegram_subscription(chat_id, email)
        await update.message.reply_text(
            f"✅ Subscribed! You'll get deal alerts at `{email}`.\n\n"
            "Now set your alert criteria:\n"
            "/alert <max_price>  (e.g. /alert 2500)\n"
            "/deals — see what's available now\n"
            "/stop — unsubscribe"
        )
        ctx.user_data['awaiting_email'] = False

    # Wire up handlers
    app.add_handler(CommandHandler('start',  start))
    app.add_handler(CommandHandler('help',   help_cmd))
    app.add_handler(CommandHandler('deals',  deals))
    app.add_handler(CommandHandler('alerts', alerts))
    app.add_handler(CommandHandler('alert',  set_alert))
    app.add_handler(CommandHandler('stop',   stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    log.info("Telegram bot starting polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    start_bot()
