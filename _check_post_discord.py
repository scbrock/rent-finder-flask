import post_discord
import inspect

# Check what functions exist
print("post_discord functions:", [n for n in dir(post_discord) if not n.startswith('_')])

# Try to build a message manually
results = {
    "total": 366,
    "deals": 202,
    "best": {"neighborhood": "Toronto", "beds": 2, "price": 700, "fv": 2632, "pct": 73.4, "score": 1.0},
    "kijiji": {"listings": 53, "errors": 0, "duration_secs": 5.2},
    "craigslist": {"listings": 314, "errors": 0, "duration_secs": 0.8},
    "alert_fired": False,
}

# Check post function signature
print("\npost function:", inspect.signature(post_discord.post) if hasattr(post_discord, 'post') else "not found")
print("post_deals function:", inspect.signature(post_discord.post_deals) if hasattr(post_discord, 'post_deals') else "not found")