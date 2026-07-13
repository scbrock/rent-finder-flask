# Render deploy runbook

## Symptom
Live Render (`https://rent-finder-flask.onrender.com`) is serving an
old build; new features / fixes that pass locally and are committed
locally to `clean_build` never reach the live URL.

## Root cause (verified MC-352)
The deploy pipeline is:

  1. `git push origin clean_build` (or via PR merge) -- triggers
     GitHub Action
  2. `.github/workflows/deploy.yml` -- runs
     `curl -s --fail "${{ secrets.RENDER_DEPLOY_HOOK }}"`
  3. Render receives the hook -> starts a new build

If the local `clean_build` branch has commits that haven't been
pushed to `origin/clean_build`, step 1 never fires. The hook
never curls. Render keeps serving the last successful build
indefinitely. No error / no warning visible in the repo.

## How to detect
Compare `git log origin/clean_build..HEAD` (commits ahead of
remote) against `gh run list --repo scbrock/rent-finder-flask
--workflow=deploy.yml --limit 1` (most recent deploy).

If `git log origin/clean_build..HEAD` is non-empty but the most
recent Action run was hours/days ago, the local commits are stranded.

## How to fix
1. `git push origin clean_build` -- single command, kicks off the
   pipeline.
2. Watch the action: `gh run list -w deploy.yml -L 1` (should
   transition queued -> in_progress -> completed in 1-2 min).
3. Wait for Render to finish the build (~2-5 min on free tier) and
   the new static files to be served.

## Prevention
- Make `git push` part of the post-commit habit whenever
  `clean_build` is the active branch.
- The cron mission loop SHOULD auto-push after each commit, but
  currently doesn't. Add a `git push origin clean_build` step to
  the cron mission-loop (or use a post-commit git hook) to prevent
  this drift from accumulating.

## Last incident (MC-352, 2026-07-13)
- Local `clean_build` had 4 unpushed commits (MC-343, MC-345,
  MC-347, MC-351) at 09:08 UTC.
- Remote `origin/clean_build` was at `a188502` (MC-337+MC-338) from
  06:48 UTC on 2026-07-10.
- Render was serving the stale `a188502` build. `static/
  recently_viewed.js` 404. `minutes_since_scrape` 4700 (stale).
- Fix: `git push origin clean_build`. Action run #29252610242
  completed at 13:09:20Z with success.
- Verified live: `static/recently_viewed.js` 200, `minutes_since_
  scrape` 2.5, MC-351 features reachable.

## Auto-transition fix (mission-control-server)
This repo's `cd2e7ed` (MC-317: assigned_to sync in POST /tickets/
status) is also on `master`. Mission-control-server has its own
deploy pipeline (cron-driven `scp` to Render). Check its status
separately via the mission-control-server repo's deploy logs.
