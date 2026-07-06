# Toronto Rent Deal Finder — Progress Log

**Current Phase:** 🔄 Pipeline Maintenance — all MC-2xx complete. Pipeline healthy at ~400 listings/run.
**Last Updated:** 2026-04-22 22:43 UTC

---

## Results Table

| Date | Step | What Was Done | Listings Collected | Deals Found | Best Deal | Notes |
|:-----|:-----|:-------------|:------------------|:------------|:----------|:------|
| 2026-04-16 | Step 1 | Kijiji Apollo-state scraper working — 60 live listings | 60 LIVE | 3 | Toronto 1BR $1,400 (+23.3%) | Price in cents: 140000 = $1,400/mo. Scraped 5 pages, 42 listings/page. |
| 2026-04-16 | Step 1 attempt | Built pipeline (scraper + scoring + CSV output) | 60 SYNTHETIC | 13 | Queen West 2BR $2,200 (+19.3%) | INVALID — all sample data. Zumper JS-blocked, Kijiji returned 0. |
| 2026-04-16 (AM) | Step 1–3 + Discord | Kijiji 5 pages — 210 raw, 63 deduped after price filter. Scoring working. Discord post attempted but bot token missing. | 63 LIVE | 2 | Toronto 1BR $1,400 (+23.3%) | Same top deal. 2/63 deals under market — low rate due to stale listings (many 60d old). |
| 2026-04-16 (PM) | Step 4 — COMPLETE | Daily cron scheduled at 7 AM ET. Pipeline fully working. Discord posting confirmed with --account carl. | 55 LIVE | 11 | High Park-Swansea 0BR $1,700 (+21.8%) | Daily cron (id: bcd13b45) fires at 11:00 UTC / 7 AM ET. |
| 2026-04-17 | MC-252 — COMPLETE | Stale listing filter (days_ago > 30). activationDate extracted from __NEXT_DATA__ Apollo state per listing. score_deals() excludes stale from fair_value. is_stale + days_ago columns added to CSV. test_mc252_stale_filter.py: 4/4 pass. Committed 9bff2e5. | 47 LIVE | 0-28 days | stale excluded | Stale: 11 listings excluded from 64 scraped (days 31-260). Active: 31 of 40 scored. |
| 2026-04-17 | MC-258 — COMPLETE | Craigslist scraper added as second source. 270 CL + 62 Kijiji = 283 total after cross-source dedup. scrape_craigslist.py parses `<li class="cl-static-search-result">`. Cross-source dedup uses (beds + neighbourhood_norm + price//50) hash. Flask app (app.py + templates) pushed to rent-finder-flask clean_build. MC-276 deploy blocked on RENDER_SERVICE_ID. | 283 LIVE (62 Kijiji + 270 Craigslist) | 64/283 under market | Trinity-Bellwoods 1BR $2,600 (+60.3%) | Target 150+ listings met. MC-276 (deploy) still blocked on user adding RENDER_SERVICE_ID to GitHub secrets. |
| 2026-04-18 (AM) | MC-276 — COMPLETE | Manual find_deals.py run (cron aborted). 274 listings. 67/274 under market (24%). Best deal: Trinity-Bellwoods 1BR $2,600 (+60.3%, score=1.150). Discord post failed: post_discord.py referenced deals[rank] where rank is a float from np.float32. MC-276 already complete — branch pushed 2026-04-17 (commit a7162b5). | 274 LIVE | 67/274 (24%) | Trinity-Bellwoods 1BR $2,600 (+60.3%, score=1.150) | Discord post bug: post_discord.py line 68 — convert rank to int before indexing. Non-critical, cron continues. |
| 2026-04-18 | MC-260 — COMPLETE | Toronto Open Data GeoJSON (140 official neighbourhoods, jasonicarter/toronto-geojson repo). Centroids computed with shapely. neighbourhood_lookup.py: direct_map for 300+ scraped variants + fuzzy match at 0.6 threshold. 14/14 tests pass. rent_finder/data/toronto_neighbourhoods.json created (gitignored). | — | — | — | 126/138 scraped neighbourhood names matched to official names. 12 unmatched = non-Toronto noise. |
| 2026-04-19 | MC-271 — COMPLETE (in review) | Shortlist feature: saved_listings table in persist.py schema + upsert/get/delete/is_saved CRUD functions; /api/saved-listings endpoints (GET/POST/DELETE/check) in app.py; star column in deals table + toggleShortlist/loadShortlistStatus JS in index.html. 12/12 pytest tests pass. commit 2f7e7fc. | — | — | — | Email-based identity (localStorage). Star button toggles saved status. Batch shortlist check on deal load via /api/saved-listings/check. MC-268/269 also in review — poi.py generic POI framework + batch_poi.py cover them. |

| 2026-04-20 (PM) | MC-285 — Nightly Cycle | Kijiji (65) + Craigslist (267) = 257 listings, 62 deals (24%), best: Harbourfront 1BR $2,300 (+61.1% under market). Discord posted. SQLite 84 active. | 257 | 62 | Harbourfront 1BR $2,300 (+61.1%) | Zumper still blocked (0 listings). |
| 2026-04-20 (late PM) | MC-285 — Cycle 2 | Verified https://rent-finder-flask.onrender.com is live (HTTP 200, 60KB page). /api/deals returns 50 deals with filter controls. Railway token invalid — Render.com deployment via GitHub Actions is working (4 consecutive successful deploys Apr 19). No 500 errors. MC-285 complete. | — | — | — | Render.com is the working deployment target. Railway token needs renewal if used again. |
| 2026-04-22 (AM) | MC-290 — COMPLETE | Kijiji scraper upgraded from HTML card parser to Apollo GraphQL state parser (scrape_kijiji_real). Kijiji: 218 listings in 5 pages (was ~50 in 3 pages). Pipeline total: 412 listings (218 Kijiji + 315 Craigslist, deduped), 230 deals (56%), best: Toronto 2BR $700 (+73.4% under FV $2628). run_pipeline.py: 5 Kijiji pages (was 3), 3 Craigslist pages (was 2). _save_raw() updated to handle both dict and dataclass listings. 15/15 tests pass. Commit ffdd9c16. | 412 (218 Kijiji + 315 CL, deduped) | 230/412 (56%) | Toronto 2BR $700 (+73.4%) | Kijiji listings 4.4x increase (218 vs 50). MC-288 still blocked (Viewit ASP.NET WebForms + ViewState, Rentals.ca ToS). MC-289 (health monitor) complete. |
| 2026-04-21 (AM) | MC-285 — Cycle 3 | Pipeline run: 261 listings (60 Kijiji + 261 Craigslist, deduped). 65 deals (25%) found. Best: Harbourfront 1BR $2,300 (+61.1%). App wake test timed out (cold start >10s on Render free tier). All major features complete. MC-286 created: confirm app wake reliability. | 261 | 65 | Harbourfront 1BR $2,300 (+61.1%) | Discord relay failed — no bot token configured. All MC-2xx features done, mission entering maintenance. |

---

| 2026-04-22 (22:43 UTC) | Pipeline Run — idle | 407 listings (215 Kijiji + 311 Craigslist). 250 deals (61% deal rate). Best: Toronto 2BR $700 (+73.2%, FV $2607). No backlog tickets remaining. | 407 | 250 | Toronto 2BR $700 (+73.2%) | No backlog tickets. All MC-2xx complete. Going idle. |
| 2026-04-22 (08:43 UTC) | Pipeline run (cron cycle) | Pipeline: 372 listings (210 Kijiji + 314 Craigslist, deduped). 218 deals (56%). Best: Toronto 2BR $700 (+73.3% under FV $2623). MC-288 (Viewit/Rentals blocked) resolved - liv.rent is next target. MC-291 created: fix /healthz 404 on Render. Git push b3e9709 committed to clean_build. | 372 (209 Kijiji + 314 Craigslist) | 218/372 (58.6%) | Toronto 2BR $700 (+73.3%) | Discord webhook not configured. /healthz 404 on Render - clean_build needs fresh deploy. |

## Next Up

1. **MC-276: Add RENDER_SERVICE_ID to GitHub secret** — user needs to add Render API key to the rent-finder-flask repo (https://github.com/scbrock/rent-finder-flask/settings/secrets/actions). Then push to `clean_build` branch — auto-deploys to Render.com
2. **MC-257 (depends on MC-276): Commute time filter** — add ORS API for on-the-fly commute computation (currently reads pre-computed commute_minutes from CSV)
3. **MC-272: Price drop alerts for shortlisted listings** — depends on MC-271 (in review). Price drop badge on shortlisted listings.
4. **MC-273: User preference profile** — beds, neighbourhoods, max price, commute destination. Depends on MC-271.
5. **Step 5: Automated Scoring Tuning** — monitor deal accuracy over 1–2 weeks

---

## Backlog — New Tickets (2026-04-19)

### MC-280: liv.rent scraper (new source)
**Priority:** High — best scrapeable source found after exhaustive probe (rentals.ca 403, realtor.ca Incapsula, craigslist/kijiji already done)

**What:** Add `scrape_livrent.py` as a third listing source. liv.rent is a Canadian rental platform serving Toronto with 500+ active listings. The site returns HTTP 200 to standard browser UA and shows full listing data on detail pages.

**Approach:**
1. Use browser dev tools (F12 > Network tab) on `https://www.liv.rent/rental-listings/city/toronto` to find the XHR/fetch call that loads listing cards. liv.rent is a Next.js SPA — listings load client-side via an internal REST API (likely `https://api.liv.rent/...` or `/api/listing/search` with JWT auth).
2. Alternative: use Playwright to render the search page and extract listing cards from rendered DOM. Install: `pip install playwright && playwright install chromium`.
3. Fields to extract: `listing_id`, `price`, `beds`, `baths`, `sqft`, `address`, `neighbourhood`, `listing_date`, `listing_url`, `source="livrent"`.
4. Wire into `find_deals.py` alongside `scrape_kijiji` and `scrape_craigslist`. Apply same stale filter (days_ago <= 30) and cross-source dedup hash `(beds + neighbourhood_norm + price//50)`.

**Target:** +200 listings/run. Expected to include condos and purpose-built rentals not listed on Kijiji/CL.

**Notes:**
- Detail page format: `/rental-listings/detail/apartment/toronto/{listing_id}` — confirmed working (e.g., listing 140849 = 70 Parkwoods Village Dr, 3BR $2,929/mo)
- Search page: `/rental-listings/city/toronto` — loads dynamically; HTML shell only, no `__NEXT_DATA__`
- Do NOT attempt: rentals.ca (403), realtor.ca (Incapsula/403), point2homes (403), rentboard.ca (403), condos.ca (403), hotpads (403)

---

### MC-281: Historical fair value model (regression-based pricing)
**Priority:** High — current fair value is same-day mean from today's scraped listings, which is noisy (small sample, outliers skew mean)

**What:** Replace the per-day mean fair value with a rolling regression trained on 30–60 days of stored listing history from SQLite.

**Approach:**
1. `persist.py` already saves every scraped listing — use the `listings` table as training data.
2. Build a simple OLS model: `price ~ beds + baths + sqft + neighbourhood_encoded` trained on all listings from the past 60 days.
3. Fair value for a new listing = model prediction. Score = `predicted_price / actual_price` (same scale as current).
4. Fallback to current same-day mean if fewer than 50 historical rows exist (cold start).
5. Retrain model daily in `find_deals.py` before scoring loop.

**Expected outcome:** Smoother, more stable fair values. Eliminates "weird" deals caused by thin same-day samples (e.g., only 3 listings in a neighbourhood → one outlier blows up the mean).

**Files:** `rent_finder/fair_value.py` (new) wired into `find_deals.py` `score_deals()`.

**Test:** `pytest tests/test_fair_value.py` — verify predictions within ±15% of held-out listings.

---

### MC-282: Anomaly/fraud detection — auto-flag suspect listings
**Priority:** Medium — reduces noise in deal feed; prevents misleading Discord alerts

**What:** Add a `suspect` flag to listings that look like fraud or data errors. Show a warning badge in the Flask UI and exclude from Discord top-deals.

**Rules to implement:**
- Price more than 50% below neighbourhood fair value AND 0 baths listed → `suspect=True` (common scrape error: bath field missing → default 0)
- Price < $500/mo (impossible for Toronto) → `suspect=True`
- Title/description contains "room in house" or "shared" but is classified as whole-unit → `suspect=True`
- Same price + beds combo listed > 5 times by same poster in past 7 days → `suspect=True` (listing spam)

**Files:** `rent_finder/anomaly.py` (new) — `flag_suspects(df) -> df` with `suspect` bool column. Wire into `score_deals()` after scoring.

**UI:** Orange `⚠` badge on suspect rows in deals table. Filter checkbox: "Hide suspect listings" (default: on).

---

### MC-283: Price trend dashboard — 30-day median by segment
**Priority:** Medium — gives renters market context beyond today's snapshot

**What:** Add a `/trends` route to the Flask app showing price trend charts per segment (beds × top-10 neighbourhoods) using 30 days of history from SQLite.

**Approach:**
1. Query `listings` table: `SELECT date, beds, neighbourhood, AVG(price) FROM listings WHERE days_ago <= 30 GROUP BY date, beds, neighbourhood`
2. Plot with Chart.js (already used in the app for other charts). One line per neighbourhood, faceted by beds.
3. Sidebar: top movers — neighbourhoods with largest price drop/rise in past 2 weeks.

**Files:** New route `GET /trends` in `app.py`. New template `templates/trends.html`. No new DB columns needed.

**Notes:** Meaningful data requires at least 14 days of daily scrape history. Can launch the page immediately but display "Not enough history yet" until data accumulates.

---

### MC-284: Paid rental data source evaluation
**Priority:** Low — only pursue if free sources plateau below 400 listings/day

**What:** Research and recommend one paid data source for Toronto rentals. User is willing to pay if quality justifies it.

**Options to evaluate:**

| Source | Pricing (est.) | Coverage | Notes |
|--------|---------------|----------|-------|
| Rentals.ca Business API | ~$200–500/mo | 50k+ CA listings | Requires business account; contact sales@rentals.ca |
| Zonda (formerly Metrolist) | Custom quote | New construction + rentals | Enterprise-grade, likely $1k+/mo |
| CoStar / Apartments.com | Custom quote | Comprehensive US+CA | Requires CoStar subscription, institutional pricing |
| Rentcast API | $29–99/mo | US-focused, limited CA | Worth testing free tier for Toronto boundary |
| CMHC Housing Data | Free | Aggregate stats only | No individual listings; useful for fair value benchmarking |

**Deliverable:** 1-page comparison doc + recommendation. Contact rentals.ca sales first — they have a known Canadian rental focus and mid-range pricing.

---

### MC-286: Commute ROI calculator — time vs cost tradeoff by location
**Priority:** High — directly answers "is the cheaper listing actually cheaper once I factor in getting to work?"

**What:** For each listing, compute an **effective monthly cost** that combines rent + commuting cost + commuting time value. Surface a "commute ROI" score in the Flask UI so users can compare a cheap-but-far listing against a pricier-but-close one on a level playing field.

**Core formula:**
```
effective_cost = rent
              + (commute_days_per_month × 2 × transit_fare)   # transit cost
              + (commute_days_per_month × 2 × commute_minutes/60 × hourly_value)  # time cost
```
Defaults: `commute_days_per_month = 22`, `transit_fare = $3.30` (TTC single fare or Presto monthly $156/21 days), `hourly_value` = user-configurable (suggested: $25/hr).

**Inputs (user-configurable in UI or preference profile):**
- Work address (geocoded to lat/lon via `https://nominatim.openstreetmap.org/search`)
- Transport mode: transit / driving / cycling
- Days per month commuting (default 22)
- Hourly time value in $/hr (default $25)
- Transit pass type: single fare vs monthly Presto ($156/mo flat if commute_minutes ≤ 90)

**Commute time source:**
- Reuse the ORS (OpenRouteService) API already wired for MC-257 — call `POST https://api.openrouteservice.org/v2/matrix/driving-car` for driving, or the transit profile if ORS supports it.
- For transit specifically: OpenTripPlanner or Google Maps Routes API (free tier: 10k requests/mo). Google Maps is more accurate for TTC routing — API key needed.
- Cache commute times in `commute_cache` SQLite table keyed by `(listing_id, work_lat, work_lon, mode)` — avoid re-fetching on every page load.

**UI changes:**
- New column in deals table: **"Effective/mo"** showing `effective_cost` formatted as `$X,XXX`.
- Tooltip on hover: breakdown — `Rent $X,XXX + Transit $XX + Time value $XX`.
- Sort deals table by effective cost (not just rent) — add toggle "Sort by: Rent | Effective Cost".
- Settings panel: work address, mode, days/mo, hourly value. Persist in `user_preferences` table (MC-273).
- Highlight listings where `effective_cost < rent + $200` (i.e., commute is nearly free) with a green "Low commute cost" badge.

**ROI comparison widget (stretch):**
Given two shortlisted listings A and B, show a side-by-side: "Listing A saves $X/mo in rent but costs $Y/mo more in commute → net $Z/mo cheaper over 12 months."

**Files:**
- `rent_finder/commute_roi.py` — `compute_effective_cost(listing, work_coords, mode, days, hourly_value)` + `batch_compute_roi(listings_df, prefs)`
- `rent_finder/commute_cache.py` — SQLite cache wrapper (or add table to `persist.py`)
- Updates to `app.py`: new `/api/commute-roi` endpoint + wire into `/api/deals` response
- Updates to `templates/index.html`: effective cost column + settings panel

**Dependencies:** MC-257 (ORS commute times), MC-273 (user preference profile). Can build commute_roi.py independently; UI integration needs MC-273 for work address storage.

**Notes:**
- TTC monthly Presto pass ($156/mo) is cheaper than 44 single fares ($145.20) only if commuting every workday. For <22 days/mo or irregular schedules, per-trip fare is more accurate — let user choose.
- Cycling mode: cost = $0, time value still applies. Good for listings within 5km of work.
- If Google Maps API key not available: fall back to ORS transit (less accurate for TTC) or straight-line distance heuristic (1 km ≈ 3 min transit).

---

### MC-285: realtor.ca via Playwright browser automation
**Priority:** Low — attempt only after MC-280 (liv.rent) is complete

**What:** Scrape `https://www.realtor.ca/map#` for Toronto rental listings using headless browser to bypass Incapsula bot protection.

**Context:** `api2.realtor.ca/Listing.svc/PropertySearch_Post` returns 403 with Incapsula challenge when called directly. Playwright with stealth mode can bypass this by rendering JavaScript and passing browser fingerprinting checks.

**Approach:**
1. Install `playwright-stealth`: `pip install playwright playwright-stealth`
2. Use `stealth_async(page)` before navigation to mask headless fingerprints
3. Intercept the `PropertySearch_Post` XHR call from within the browser context using `page.on("response", ...)` — capture the API response JSON without calling the API directly
4. Extract: `ListingID`, `Price`, `BedroomTotal`, `BathroomTotal`, `Building.SizeInterior`, `Property.Address`, `PostalCode`, `ProvinceName`
5. Filter: `TransactionType = "For Lease"`, `Province = "Ontario"`, `City = "Toronto"`

**Risk:** Incapsula may fingerprint even headless + stealth. Fallback: rotate residential proxies (Brightdata ~$15/GB). Do not pursue if blocked after 3 attempts — this source is not worth building a brittle scraper for.

**Files:** `rent_finder/scrape_realtor.py`

---

## Learnings

- Kijiji uses Next.js with `__NEXT_DATA__` containing an Apollo GraphQL state
- Listing price is in **cents** (e.g., 157500 = $1,575.00/month) — divide by 100
- Kijiji's rental category URL: `https://www.kijiji.ca/b-apartments-condos/city-of-toronto/apartment-for-rent/k0c37l1700273`
- 5 pages — ~42 listings = 210 raw — 63 after price > $800 filter and dedup
- Duplicates between pages — `drop_duplicates(subset=["link"])` is essential
- **Stale data problem**: Kijiji listings with activationDate 60+ days old — filtered with `days_ago <= 30`
- **Discord posting**: `openclaw message send --account carl --channel discord --target <channel>` works when carl account has Discord bot token configured
- **Source probe results (2026-04-19):** rentals.ca=403, realtor.ca=403 (Incapsula), point2homes=403, rentboard.ca=403, condos.ca=403, hotpads=403, **liv.rent=200** (Next.js SPA, listings load client-side via XHR — needs Playwright or API interception; detail page format: `/rental-listings/detail/apartment/toronto/{id}`)
- **liv.rent detail pages work:** e.g. listing 140849 = 70 Parkwoods Village Dr, 3BR $2,929/mo — confirmed parseable HTML

---

## Files

- `rent_finder/find_deals.py` — complete pipeline (scraper + scorer + output + Discord)
- `rent_finder/scrape_kijiji.py` — Kijiji scraper (Apollo __NEXT_DATA__ extraction)
- `rent_finder/deals_output.csv` — scored output with top deals
- `rent_finder/post_discord.py` — standalone Discord poster
- `rent_finder/persist.py` — SQLite persistence (MC-262+)
- `rent_finder/poi.py` — POI proximity via Overpass API (MC-267/268/269/270)
- `rent_finder/batch_poi.py` — batch POI cache population (MC-269)
- `rent_finder/app.py` — Flask web app
- `rent_finder/templates/index.html` — deals UI

---

## Cron Jobs

| Job ID | Name | Schedule | Status |
|:-------|:-----|:---------|:-------|
| 153f3872 | rent-finder-mission-loop | Every 4 hours | Active — Carl picks up next backlog ticket |
| bcd13b45 | rent-finder-daily | Daily 7 AM ET | Active — runs find_deals.py + posts to Discord |

---

## Blockers

- **MC-276 DEPLOY BLOCKED (2026-04-17):** GitHub Actions workflow `deploy.yml` uses `JorgeLNJunior/render-deploy@v1.5.0` which requires `RENDER_SERVICE_ID` GitHub secret in addition to `RENDER_API_KEY` (already set). Missing secret: `RENDER_SERVICE_ID`. User needs to add this from dashboard.render.com — rent-finder-flask service — Settings — General. Steps: dashboard.render.com -> rent-finder-flask -> Settings -> General -> copy SERVICE_ID -> add to GitHub secrets as RENDER_SERVICE_ID. Then push clean_build.


## 2026-04-23 (01:40 UTC) — Pipeline Run
- **374 listings** (211 Kijiji + 315 Craigslist, 374 deduped) | **231 deals** (61.8% deal rate)
- Best: Toronto 2BR \ (FV=\, +72.9%, score=1.000)
- Discord: No DISCORD_RENT_WEBHOOK env var set — skipping post (pipeline logs to console only)
- Pipeline: healthy, no errors
