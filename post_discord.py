"""
Discord deal poster for Toronto Rent Finder.
Posts top deals to Discord channel 1485371628538822898.
Can be called standalone or integrated into the main pipeline.
"""

import os, json, requests
from datetime import datetime

# ── Discord Webhook ────────────────────────────────────────────────────────────
# Channel 1485371628538822898 — rent-finder-dev (configured in OpenClaw)

DISCORD_WEBHOOK_URL = os.environ.get(
    "DISCORD_RENT_WEBHOOK",
    "https://discord.com/api/webhooks/your-webhook-here"
)

def post_deals_to_discord(scored_df, limit=5):
    """
    Format and post top deals to Discord.
    scored_df must have: rank, price, beds, neighborhood, pct_under, days_ago, link, fair_value
    """
    if DISCORD_WEBHOOK_URL == "https://discord.com/api/webhooks/your-webhook-here":
        print("[Discord] No DISCORD_RENT_WEBHOOK set — skipping post.")
        return

    deals = scored_df.head(limit).copy()
    deals["pct_under"] = deals["pct_under"].round(1)

    lines = [
        f"🏠 **Toronto Rent Deals** — {datetime.now().strftime('%B %d, %Y')}",
        f"📊 *{len(scored_df)} listings scanned | {len(deals)} deals found*",
        "",
    ]

    medal_emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for _, row in deals.iterrows():
        emoji = medal_emoji[row["rank"] - 1] if row["rank"] <= 5 else f"#{row['rank']}"
        pct = f"+{row['pct_under']:.1f}%" if row["pct_under"] > 0 else f"{row['pct_under']:.1f}%"
        bed_str = f"{row['beds']}BR" if row["beds"] > 0 else "Studio"
        sqft_str = f" | {int(row['sqft']):,}ft²" if pd.notna(row["sqft"]) and row["sqft"] > 10 else ""
        link_short = row["link"][:60] + "..." if len(row["link"]) > 60 else row["link"]
        age_str = f" ({row['days_ago']}d ago)" if row.get("days_ago", 0) <= 7 else ""

        lines.append(
            f"{emoji} **{row['neighborhood']}** {bed_str} @ **${row['price']:,}/mo**"
            f" | {pct} under market | FV: ${int(row['fair_value']):,}{sqft_str}{age_str}"
        )
        lines.append(f"   🔗 {row['link']}")
        lines.append("")

    payload = {"content": "\n".join(lines)}
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if resp.status_code in (200, 204):
            print(f"[Discord] Posted {len(deals)} deals successfully.")
        else:
            print(f"[Discord] Post failed: HTTP {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        print(f"[Discord] Post error: {e}")


if __name__ == "__main__":
    import pandas as pd
    import sys

    csv_path = sys.argv[1] if len(sys.argv) > 1 else "deals_output.csv"
    if not os.path.isabs(csv_path):
        csv_path = os.path.join(os.path.dirname(__file__), "..", csv_path)

    df = pd.read_csv(csv_path)
    post_deals_to_discord(df, limit=5)