# Toronto Rent Deal Finder — Progress Log

**Current Phase:** 🚧 Step 5 — Web App DEPLOY BLOCKED — switched to Render.com
**Last Updated:** 2026-04-16 (6:45 PM ET)

---

## Results Table

| Date | Step | What Was Done | Listings Collected | Deals Found | Best Deal | Notes |
|:-----|:-----|:-------------|:------------------|:------------|:----------|:------|
| 2026-04-16 | Step 1 | Kijiji Apollo-state scraper working — 60 live listings | 60 LIVE | 3 | Toronto 1BR $1,400 (+23.3%) | Price in cents: 140000 → $1,400/mo. Scraped 5 pages, 42 listings/page. |
| 2026-04-16 | Step 1 attempt | Built pipeline (scraper → scoring → CSV output) | 60 SYNTHETIC | 13 | Queen West 2BR $2,200 (+19.3%) | INVALID — all sample data. Zumper JS-blocked, Kijiji returned 0. |
| 2026-04-16 (AM) | Step 1–3 + Discord | Kijiji 5 pages → 210 raw, 63 deduped after price filter. Scoring working. Discord post attempted but bot token missing. | 63 LIVE | 2 | Toronto 1BR $1,400 (+23.3%) | Same top deal. 2/63 deals under market — low rate due to stale listings (many 60d old). |
| 2026-04-16 (PM) | Step 4 — COMPLETE | Daily cron scheduled at 7 AM ET. Pipeline fully working. Discord posting confirmed with --account carl. | 55 LIVE | 11 | High Park-Swansea 0BR $1,700 (+21.8%) | Daily cron (id: bcd13b45) fires at 11:00 UTC / 7 AM ET. |
| 2026-04-16 (PM) | Step 5 — IN PROGRESS | Flask web app built (app.py + templates/index.html). 10/10 tests pass. Files: app.py, templates/index.html, requirements.txt, Procfile. Next: deploy to Railway. | — | — | — | MC-277 in_progress (deploy to Railway) |

---

## ✅ Step 4 — Output Polish (COMPLETE)

All acceptance criteria met:
- ✅ `deals_output.csv` written each run
- ✅ Top 3 deals printed to console
- ✅ Discord posting working (via `openclaw message send --account carl --channel discord`)
- ✅ Stale listings filtered (`days_ago <= 30`) — implemented in find_deals.py line ~344
- ✅ Daily cron scheduled at 7 AM ET → cron id: bcd13b45

---

## Next Up

1. **MC-279: Add RENDER_API_KEY to GitHub secret** — user needs to add Render API key to the rent-finder-flask repo (https://github.com/scbrock/rent-finder-flask/settings/secrets/actions). Then push to `clean_build` branch → auto-deploys to Render.com
2. **MC-278: Commute time filter** — add ORS API for commute filter (depends on deploy succeeding)
3. **Step 5: Automated Scoring Tuning** — monitor deal accuracy over 1–2 weeks
4. **Step 6: Multi-source expansion** — add Zumper, Viewit, Padmapper beyond Kijiji-only
5. **MC-275: Weekly digest email** (low priority)

---

## Learnings

- Kijiji uses Next.js with `__NEXT_DATA__` containing an Apollo GraphQL state
- Listing price is in **cents** (e.g., 157500 = $1,575.00/month) — divide by 100
- Kijiji's rental category URL: `https://www.kijiji.ca/b-apartments-condos/city-of-toronto/apartment-for-rent/k0c37l1700273`
- 5 pages × ~42 listings = 210 raw → 63 after price > $800 filter and dedup
- Duplicates between pages — `drop_duplicates(subset=["link"])` is essential
- **Stale data problem**: Kijiji listings with activationDate 60+ days old — filtered with `days_ago <= 30` ✅
- **Discord posting**: `openclaw message send --account carl --channel discord --target <channel>` works when carl account has Discord bot token configured

---

## Files

- `rent_finder/find_deals.py` — complete pipeline (scraper + scorer + output + Discord)
- `rent_finder/scrape_kijiji.py` — Kijiji scraper (Apollo __NEXT_DATA__ extraction)
- `rent_finder/deals_output.csv` — scored output with top deals
- `rent_finder/post_discord.py` — standalone Discord poster

---

## Cron Jobs

| Job ID | Name | Schedule | Status |
|:-------|:-----|:---------|:-------|
| 153f3872 | rent-finder-mission-loop | Every 4 hours | Active — Carl picks up next backlog ticket |
| bcd13b45 | rent-finder-daily | Daily 7 AM ET | Active — runs find_deals.py + posts to Discord |

---

## Blockers

- None — all Step 4 blockers resolved as of 2026-04-16 PM session.
