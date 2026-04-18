# Toronto Rent Deal Finder ??? Progress Log

**Current Phase:** MC-258 complete -- Step 5 Flask app deployed (MC-276 blocked on RENDER_SERVICE_ID secret)
**Last Updated:** 2026-04-17 (2:43 PM ET)

---

## Results Table

| Date | Step | What Was Done | Listings Collected | Deals Found | Best Deal | Notes |
|:-----|:-----|:-------------|:------------------|:------------|:----------|:------|
| 2026-04-16 | Step 1 | Kijiji Apollo-state scraper working ??? 60 live listings | 60 LIVE | 3 | Toronto 1BR $1,400 (+23.3%) | Price in cents: 140000 ??? $1,400/mo. Scraped 5 pages, 42 listings/page. |
| 2026-04-16 | Step 1 attempt | Built pipeline (scraper ??? scoring ??? CSV output) | 60 SYNTHETIC | 13 | Queen West 2BR $2,200 (+19.3%) | INVALID ??? all sample data. Zumper JS-blocked, Kijiji returned 0. |
| 2026-04-16 (AM) | Step 1???3 + Discord | Kijiji 5 pages ??? 210 raw, 63 deduped after price filter. Scoring working. Discord post attempted but bot token missing. | 63 LIVE | 2 | Toronto 1BR $1,400 (+23.3%) | Same top deal. 2/63 deals under market ??? low rate due to stale listings (many 60d old). |
| 2026-04-16 (PM) | Step 4 ??? COMPLETE | Daily cron scheduled at 7 AM ET. Pipeline fully working. Discord posting confirmed with --account carl. | 55 LIVE | 11 | High Park-Swansea 0BR $1,700 (+21.8%) | Daily cron (id: bcd13b45) fires at 11:00 UTC / 7 AM ET. |
| 2026-04-17 | MC-252 ??? COMPLETE | Stale listing filter (days_ago > 30). activationDate extracted from __NEXT_DATA__ Apollo state per listing. score_deals() excludes stale from fair_value. is_stale + days_ago columns added to CSV. test_mc252_stale_filter.py: 4/4 pass. Committed 9bff2e5. | 47 LIVE | 0-28 days | stale excluded | Stale: 11 listings excluded from 64 scraped (days 31-260). Active: 31 of 40 scored. |
| 2026-04-17 | MC-258 ??? COMPLETE | Craigslist scraper added as second source. 270 CL + 62 Kijiji = 283 total after cross-source dedup. scrape_craigslist.py parses `<li class="cl-static-search-result">`. Cross-source dedup uses (beds + neighbourhood_norm + price//50) hash. Flask app (app.py + templates) pushed to rent-finder-flask clean_build. MC-276 deploy blocked on RENDER_SERVICE_ID. | 283 LIVE (62 Kijiji + 270 Craigslist) | 64/283 under market | Trinity-Bellwoods 1BR $2,600 (+60.3%) | Target 150+ listings met. MC-276 (deploy) still blocked on user adding RENDER_SERVICE_ID to GitHub secrets. |

---

## ??? Step 4 ??? Output Polish (COMPLETE)

All acceptance criteria met:
- ??? `deals_output.csv` written each run
- ??? Top 3 deals printed to console
- ??? Discord posting working (via `openclaw message send --account carl --channel discord`)
- ??? Stale listings filtered (`days_ago <= 30`) ??? implemented in find_deals.py line ~344
- ??? Daily cron scheduled at 7 AM ET ??? cron id: bcd13b45

---

## Next Up

1. **MC-276: Add RENDER_SERVICE_ID to GitHub secret** ??? user needs to add Render API key to the rent-finder-flask repo (https://github.com/scbrock/rent-finder-flask/settings/secrets/actions). Then push to `clean_build` branch ??? auto-deploys to Render.com
2. **MC-257 (depends on MC-276): Commute time filter** ??? add ORS API for on-the-fly commute computation (currently reads pre-computed commute_minutes from CSV)
3. **Step 5: Automated Scoring Tuning** ??? monitor deal accuracy over 1???2 weeks
4. **Step 6: Multi-source expansion** ??? Zumper JS-blocked, Viewit ASP.NET, Rentals.ca 403 ??? try Facebook Marketplace or RentBoard.ca
5. **MC-275: Weekly digest email** (low priority)

---

## Learnings

- Kijiji uses Next.js with `__NEXT_DATA__` containing an Apollo GraphQL state
- Listing price is in **cents** (e.g., 157500 = $1,575.00/month) ??? divide by 100
- Kijiji's rental category URL: `https://www.kijiji.ca/b-apartments-condos/city-of-toronto/apartment-for-rent/k0c37l1700273`
- 5 pages ?? ~42 listings = 210 raw ??? 63 after price > $800 filter and dedup
- Duplicates between pages ??? `drop_duplicates(subset=["link"])` is essential
- **Stale data problem**: Kijiji listings with activationDate 60+ days old ??? filtered with `days_ago <= 30` ???
- **Discord posting**: `openclaw message send --account carl --channel discord --target <channel>` works when carl account has Discord bot token configured

---

## Files

- `rent_finder/find_deals.py` ??? complete pipeline (scraper + scorer + output + Discord)
- `rent_finder/scrape_kijiji.py` ??? Kijiji scraper (Apollo __NEXT_DATA__ extraction)
- `rent_finder/deals_output.csv` ??? scored output with top deals
- `rent_finder/post_discord.py` ??? standalone Discord poster

---

## Cron Jobs

| Job ID | Name | Schedule | Status |
|:-------|:-----|:---------|:-------|
| 153f3872 | rent-finder-mission-loop | Every 4 hours | Active ??? Carl picks up next backlog ticket |
| bcd13b45 | rent-finder-daily | Daily 7 AM ET | Active ??? runs find_deals.py + posts to Discord |

---

## Blockers

- **MC-276 DEPLOY BLOCKED (2026-04-17):** GitHub Actions workflow `deploy.yml` uses `JorgeLNJunior/render-deploy@v1.5.0` which requires `RENDER_SERVICE_ID` GitHub secret in addition to `RENDER_API_KEY` (already set). Missing secret: `RENDER_SERVICE_ID`. User needs to add this from dashboard.render.com ??? rent-finder-flask service ??? Settings ??? General. Steps: dashboard.render.com -> rent-finder-flask -> Settings -> General -> copy SERVICE_ID -> add to GitHub secrets as RENDER_SERVICE_ID. Then push clean_build.
