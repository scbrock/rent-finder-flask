"""
MC-326: Saved-search notify-on-match tests.

Covers:
  TestNotifyFlagPersistence — schema/CRUD: ALTER idempotent, defaults to 0,
                              set via upsert, COALESCE preserves on update
                              when caller doesn't pass the flag.
  TestSavedSearchMatchQuery — _build_match_query_and_params and the count
                              helper apply each legacy column + filters_json
                              snapshot key correctly + since_iso filter.
  TestCheckAndSendSavedSearchAlerts — orchestrator walks notify=1 rows,
                              builds email payload via injected send_fn,
                              rate-limits at 24h, skips empty results,
                              marks last_notification_sent on success.
  TestApiToggleNotify — POST /api/saved-searches/<id>/toggle-notify accepts
                              email+notify, persists, returns 200 with the new
                              state; 400 on missing email/notify, 404 on
                              unknown id or wrong email.
  TestApiRunChecks — POST /api/saved-searches/run-checks invokes the worker
                              and returns the summary; tests inject a stub
                              send_fn via monkeypatch so SendGrid isn't hit.

Run with: `python -m pytest tests/test_mc326_saved_search_notify.py -v`
"""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# Make rent_finder importable
HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.dirname(HERE))


@pytest.fixture()
def isolated_db(monkeypatch):
    """
    Redirect persist.DATA_DIR + DB_PATH to a temp dir so we don't touch the
    real listings.db. Also reset the connection cache and the Module-level
    DATA_DIR/DB_PATH constants after the test (each test gets a fresh DB).
    """
    import persist

    tmpdir = tempfile.mkdtemp(prefix="mc326_")
    db_path = os.path.join(tmpdir, "mc326.sqlite")
    monkeypatch.setattr(persist, "DATA_DIR", tmpdir)
    monkeypatch.setattr(persist, "DB_PATH", db_path)
    persist._reset_conn()

    yield db_path

    persist._reset_conn()
    try:
        os.remove(db_path)
        os.rmdir(tmpdir)
    except Exception:
        pass


def _seed_listing(persist_mod, listing_id="L1", **fields):
    """Insert a listing row directly. Defaults match find_deals.py output.
    Only columns that exist on the live `listings` table."""
    base = {
        "listing_id": listing_id,
        "source": "kijiji",
        "title": f"Test {listing_id}",
        "price": 2000.0,
        "beds": 1,
        "baths": 1.0,
        "sqft": 600,
        "neighborhood": "King West",
        "region": "Downtown",
        "location": "Toronto, ON",
        "url": f"https://kijiji.ca/{listing_id}",
        "image_url": None,
        "days_ago": 0,
        "is_stale": 0,
        "first_seen": "2026-07-07T10:00:00Z",
        "last_seen": "2026-07-07T10:00:00Z",
        "is_active": 1,
        "scrape_count": 1,
        "is_new": 1,
        "fair_value": 2500.0,
        "score": 0.20,
        "pct_under": 0.25,
    }
    base.update(fields)
    # Drop any kwargs that are not in the live schema.
    from persist import _get_conn  # type: ignore
    conn = _get_conn()
    try:
        valid_cols = [r[1] for r in conn.execute("PRAGMA table_info(listings)").fetchall()]
    finally:
        conn.close()
    base = {k: v for k, v in base.items() if k in valid_cols}
    init_cols = ", ".join(base.keys())
    placeholders = ", ".join(["?"] * len(base))
    conn = persist_mod._get_conn()
    try:
        conn.execute(f"INSERT INTO listings ({init_cols}) VALUES ({placeholders})", list(base.values()))
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# TestNotifyFlagPersistence
# ─────────────────────────────────────────────────────────────────────────────

class TestNotifyFlagPersistence:
    """Schema + CRUD on the new notify_on_match and last_notification_sent cols."""

    def test_alter_idempotent(self, isolated_db):
        """Running ensure_schema twice doesn't blow up on re-ALTER."""
        import persist
        persist.init_db()
        # Second call simulates a second process touching the same DB:
        persist._reset_conn()
        persist.init_db()  # must not raise
        # Sanity: both columns exist.
        cols = [r[1] for r in persist._get_conn().execute("PRAGMA table_info(saved_searches)").fetchall()]
        assert "notify_on_match" in cols
        assert "last_notification_sent" in cols

    def test_default_value_zero(self, isolated_db):
        """A new row without notify_on_match param defaults to 0."""
        import persist
        persist.init_db()
        sid = persist.upsert_saved_search(email="u@x.com", name="default")
        row = persist.get_saved_search_by_id("u@x.com", sid)
        assert int(row["notify_on_match"]) == 0
        assert row["last_notification_sent"] is None

    def test_set_on_via_param(self, isolated_db):
        """upsert_saved_search(notify_on_match=True) → notify_on_match=1."""
        import persist
        persist.init_db()
        sid = persist.upsert_saved_search(email="u@x.com", name="on", notify_on_match=True)
        row = persist.get_saved_search_by_id("u@x.com", sid)
        assert int(row["notify_on_match"]) == 1
        assert row["last_notification_sent"] is None

    def test_set_off_explicit_via_param(self, isolated_db):
        """upsert_saved_search(notify_on_match=False) explicitly stores 0."""
        import persist
        persist.init_db()
        sid = persist.upsert_saved_search(email="u@x.com", name="off", notify_on_match=False)
        row = persist.get_saved_search_by_id("u@x.com", sid)
        assert int(row["notify_on_match"]) == 0

    def test_coalesce_preserves_flag_on_update_without_param(self, isolated_db):
        """Re-upsert without notify_on_match param must NOT overwrite a True row."""
        import persist
        persist.init_db()
        sid = persist.upsert_saved_search(
            email="u@x.com", name="x", beds_min=1, notify_on_match=True
        )
        # Caller forgets to pass notify_on_match — should be preserved.
        sid2 = persist.upsert_saved_search(email="u@x.com", name="x", beds_min=2)
        row = persist.get_saved_search_by_id("u@x.com", sid2)
        assert int(row["notify_on_match"]) == 1, "COALESCE should preserve the True flag"
        assert float(row["beds_min"]) == 2.0, "Other fields should still update normally"

    def test_explicit_false_overrides_existing_true(self, isolated_db):
        """Re-upsert with notify_on_match=False sets it to 0 even if existing row is True."""
        import persist
        persist.init_db()
        sid = persist.upsert_saved_search(email="u@x.com", name="x", notify_on_match=True)
        sid2 = persist.upsert_saved_search(email="u@x.com", name="x", notify_on_match=False)
        row = persist.get_saved_search_by_id("u@x.com", sid2)
        assert int(row["notify_on_match"]) == 0

    def test_update_saved_search_notify_toggles_owner_gated(self, isolated_db):
        """update_saved_search_notify updates only the matching email; rejects others."""
        import persist
        persist.init_db()
        sid = persist.upsert_saved_search(email="u@x.com", name="x", notify_on_match=False)
        ok = persist.update_saved_search_notify(sid, "u@x.com", True)
        assert ok is not None and int(ok["notify_on_match"]) == 1
        # Wrong email → returns None
        nope = persist.update_saved_search_notify(sid, "other@x.com", False)
        assert nope is None
        # Toggle back
        ok2 = persist.update_saved_search_notify(sid, "u@x.com", False)
        assert ok2 is not None and int(ok2["notify_on_match"]) == 0

    def test_update_saved_search_notify_unknown_id(self, isolated_db):
        """update_saved_search_notify on a non-existent search returns None."""
        import persist
        persist.init_db()
        assert persist.update_saved_search_notify(9999, "u@x.com", True) is None

    def test_get_saved_searches_to_notify_filters(self, isolated_db):
        """get_saved_searches_to_notify returns ONLY notify_on_match=1 rows."""
        import persist
        persist.init_db()
        persist.upsert_saved_search(email="a@x.com", name="on1", notify_on_match=True)
        persist.upsert_saved_search(email="a@x.com", name="off", notify_on_match=False)
        persist.upsert_saved_search(email="a@x.com", name="on2", notify_on_match=True)
        rows = persist.get_saved_searches_to_notify()
        names = sorted(r["name"] for r in rows)
        assert names == ["on1", "on2"]
        # Also: filters_dict is populated
        assert all("filters_dict" in r and isinstance(r["filters_dict"], dict) for r in rows)


# ─────────────────────────────────────────────────────────────────────────────
# TestSavedSearchMatchQuery
# ─────────────────────────────────────────────────────────────────────────────

class TestSavedSearchMatchQuery:
    """_build_match_query_and_params applies each filter dimension correctly."""

    def test_query_no_filters_returns_all_active(self, isolated_db):
        """A search with no filters matches every active listing."""
        import persist
        persist.init_db()
        _seed_listing(persist, "L1")
        _seed_listing(persist, "L2", region="Midtown")
        s = {"beds_min": None}
        query, params = persist._build_match_query_and_params(s)
        query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        count = persist._get_conn().execute(query, params).fetchone()[0]
        assert count == 2

    def test_query_beds_min(self, isolated_db):
        import persist
        persist.init_db()
        _seed_listing(persist, "S1", beds=0)
        _seed_listing(persist, "S2", beds=1)
        _seed_listing(persist, "S3", beds=3)
        query, _ = persist._build_match_query_and_params({"beds_min": 1.0})
        query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        rows = persist._get_conn().execute(query, [1.0]).fetchall()
        # Both "1" and "3" should be selected (>=1)
        assert rows[0][0] == 2

    def test_query_beds_max(self, isolated_db):
        import persist
        persist.init_db()
        _seed_listing(persist, "S1", beds=0)
        _seed_listing(persist, "S2", beds=1)
        _seed_listing(persist, "S3", beds=4)
        query, _ = persist._build_match_query_and_params({"beds_max": 1.0})
        query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        rows = persist._get_conn().execute(query, [1.0]).fetchall()
        assert rows[0][0] == 2

    def test_query_price_range(self, isolated_db):
        import persist
        persist.init_db()
        _seed_listing(persist, "S1", price=1500)
        _seed_listing(persist, "S2", price=2200)
        _seed_listing(persist, "S3", price=4000)
        s = {"price_min": 1500.0, "price_max": 2500.0}
        query, params = persist._build_match_query_and_params(s)
        query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        rows = persist._get_conn().execute(query, params).fetchall()
        assert rows[0][0] == 2

    def test_query_min_score(self, isolated_db):
        import persist
        persist.init_db()
        _seed_listing(persist, "L1", score=0.10)
        _seed_listing(persist, "L2", score=0.30)
        _seed_listing(persist, "L3", score=0.50)
        s = {"min_score": 0.25}
        query, params = persist._build_match_query_and_params(s)
        query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        rows = persist._get_conn().execute(query, params).fetchall()
        assert rows[0][0] == 2  # 0.30 and 0.50

    def test_query_region_exact_match(self, isolated_db):
        import persist
        persist.init_db()
        _seed_listing(persist, "L1", region="Downtown")
        _seed_listing(persist, "L2", region="Midtown")
        _seed_listing(persist, "L3", region="Downtown")
        s = {"region": "Downtown"}
        query, params = persist._build_match_query_and_params(s)
        query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        rows = persist._get_conn().execute(query, params).fetchall()
        assert rows[0][0] == 2

    def test_query_neighborhood_substring(self, isolated_db):
        import persist
        persist.init_db()
        _seed_listing(persist, "L1", neighborhood="King West")
        _seed_listing(persist, "L2", neighborhood="Queen West")
        _seed_listing(persist, "L3", neighborhood="Bay Street Corridor")
        s = {"neighbourhood": "West"}
        query, params = persist._build_match_query_and_params(s)
        query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        rows = persist._get_conn().execute(query, params).fetchall()
        assert rows[0][0] == 2  # L1 + L2

    def test_query_filters_json_source_filter(self, isolated_db):
        """filters_dict.source='kijiji' filters to Kijiji rows only."""
        import persist
        persist.init_db()
        _seed_listing(persist, "L1", source="kijiji")
        _seed_listing(persist, "L2", source="craigslist")
        _seed_listing(persist, "L3", source="kijiji")
        s = {"filters_dict": {"source": "kijiji"}}
        query, params = persist._build_match_query_and_params(s)
        query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        rows = persist._get_conn().execute(query, params).fetchall()
        assert rows[0][0] == 2

    def test_query_filters_json_only_new(self, isolated_db):
        """filters_dict.is_new='true' → is_new=1 only."""
        import persist
        persist.init_db()
        _seed_listing(persist, "L1", is_new=1)
        _seed_listing(persist, "L2", is_new=0)
        _seed_listing(persist, "L3", is_new=1)
        s = {"filters_dict": {"is_new": "true"}}
        query, params = persist._build_match_query_and_params(s)
        query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        rows = persist._get_conn().execute(query, params).fetchall()
        assert rows[0][0] == 2

    def test_query_since_iso_filter_on_first_seen(self, isolated_db):
        """since_iso restricts to listings with first_seen >= the cutoff."""
        import persist
        persist.init_db()
        _seed_listing(persist, "Old", first_seen="2026-07-01T10:00:00Z")
        _seed_listing(persist, "New", first_seen="2026-07-07T10:00:00Z")
        s = {"beds_min": None}
        query, params = persist._build_match_query_and_params(s, since_iso="2026-07-05T00:00:00Z")
        query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        rows = persist._get_conn().execute(query, params).fetchall()
        assert rows[0][0] == 1

    def test_get_listings_returns_match_rows(self, isolated_db):
        """get_listings_matching_saved_search returns dicts, sorted by score DESC."""
        import persist
        persist.init_db()
        _seed_listing(persist, "low", score=0.10)
        _seed_listing(persist, "high", score=0.50)
        _seed_listing(persist, "mid", score=0.30)
        rows = persist.get_listings_matching_saved_search({"beds_min": None})
        scores = [r["score"] for r in rows]
        assert scores == sorted(scores, reverse=True)
        assert len(rows) == 3

    def test_count_listings_helper_matches_query(self, isolated_db):
        """count_listings_matching_saved_search == COUNT(*) over same query."""
        import persist
        persist.init_db()
        for i in range(5):
            _seed_listing(persist, f"L{i+1}", price=1500 + i*200, beds=1, region="Downtown")
        # Prices: 1500, 1700, 1900, 2100, 2300 — 3 of them <= 1900
        s = {"beds_min": 1.0, "price_max": 1900.0, "region": "Downtown"}
        conn = persist._get_conn()
        count = persist.count_listings_matching_saved_search(conn, s)
        assert count == 3


# ─────────────────────────────────────────────────────────────────────────────
# TestCheckAndSendSavedSearchAlerts
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckAndSendSavedSearchAlerts:
    """End-to-end worker: walks subscribe list, applies rate limit, sends email."""

    def _make_sender(self):
        calls = []
        def _send(to_email, search_name, matches, unsub_url=""):
            calls.append({"to": to_email, "name": search_name, "count": len(matches), "url": unsub_url})
            return True
        _send.calls = calls
        return _send

    def test_sends_email_for_one_subscribed_search_with_matches(self, isolated_db):
        import persist
        persist.init_db()
        _seed_listing(persist, "L1", first_seen="2026-07-07T05:00:00Z")
        persist.upsert_saved_search(
            email="u@x.com", name="downtown-1br",
            beds_min=1.0, region="Downtown", notify_on_match=True,
        )
        send = self._make_sender()
        # Stub time so the worker's `now` matches the listing's first_seen.
        result = persist.check_and_send_saved_search_alerts(
            min_hours_between=24, send_fn=send,
        )
        assert result["checked"] == 1
        assert result["sent"] == 1
        assert result["skipped_no_matches"] == 0
        assert result["skipped_rate_limit"] == 0
        assert result["errors"] == 0
        assert len(send.calls) == 1
        assert send.calls[0]["to"] == "u@x.com"
        assert send.calls[0]["name"] == "downtown-1br"
        assert send.calls[0]["count"] == 1
        # last_notification_sent now stamped
        s = persist.get_saved_searches_to_notify()[0]
        assert s["last_notification_sent"] is not None

    def test_skips_non_subscribed_searches(self, isolated_db):
        """Searches with notify_on_match=0 are not touched."""
        import persist
        persist.init_db()
        _seed_listing(persist, "L1", first_seen="2026-07-07T05:00:00Z")
        persist.upsert_saved_search(
            email="u@x.com", name="off",
            beds_min=1.0, region="Downtown",
            notify_on_match=False,
        )
        send = self._make_sender()
        result = persist.check_and_send_saved_search_alerts(send_fn=send)
        assert result["checked"] == 0
        assert result["sent"] == 0
        assert send.calls == []

    def test_skips_search_with_no_matching_new_listings(self, isolated_db):
        """A subscribed search that has no matches in the window is skipped silently."""
        import persist
        persist.init_db()
        _seed_listing(persist, "old", first_seen="2026-07-01T05:00:00Z")  # 6d before NOW
        persist.upsert_saved_search(
            email="u@x.com", name="recent",
            beds_min=1.0, region="Downtown", notify_on_match=True,
        )
        send = self._make_sender()
        result = persist.check_and_send_saved_search_alerts(send_fn=send)
        assert result["sent"] == 0
        assert result["skipped_no_matches"] == 1
        assert send.calls == []

    def test_rate_limiting_within_window(self, isolated_db):
        """A search notified <24h ago is skipped."""
        import persist
        persist.init_db()
        _seed_listing(persist, "L1", first_seen="2026-07-07T05:00:00Z")
        persist.upsert_saved_search(
            email="u@x.com", name="repeat",
            beds_min=1.0, region="Downtown", notify_on_match=True,
        )
        # Stamp with a recent timestamp (within the 24h window).
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = persist._get_conn()
        conn.execute(
            "UPDATE saved_searches SET last_notification_sent = ? WHERE name = 'repeat'",
            (recent,),
        )
        conn.commit()
        conn.close()

        send = self._make_sender()
        result = persist.check_and_send_saved_search_alerts(send_fn=send)
        assert result["sent"] == 0
        assert result["skipped_rate_limit"] == 1
        assert send.calls == []

    def test_multiple_searches_each_get_their_own_email(self, isolated_db):
        """Each subscribed search gets its own send() call with its name."""
        import persist
        persist.init_db()
        _seed_listing(persist, "L_downtown", first_seen="2026-07-07T05:00:00Z", region="Downtown")
        _seed_listing(persist, "L_midtown", first_seen="2026-07-07T05:00:00Z", region="Midtown")
        persist.upsert_saved_search(
            email="a@x.com", name="dt",
            region="Downtown", notify_on_match=True,
        )
        persist.upsert_saved_search(
            email="b@x.com", name="mt",
            region="Midtown", notify_on_match=True,
        )
        send = self._make_sender()
        result = persist.check_and_send_saved_search_alerts(send_fn=send)
        assert result["checked"] == 2
        assert result["sent"] == 2
        names = sorted(c["name"] for c in send.calls)
        assert names == ["dt", "mt"]

    def test_send_returns_false_counts_as_error(self, isolated_db):
        """If send_fn returns False, we record an error and don't stamp last_sent."""
        import persist
        persist.init_db()
        _seed_listing(persist, "L1", first_seen="2026-07-07T05:00:00Z")
        persist.upsert_saved_search(
            email="u@x.com", name="boom", notify_on_match=True,
        )
        send = lambda *a, **kw: False
        result = persist.check_and_send_saved_search_alerts(send_fn=send)
        assert result["errors"] == 1
        assert result["sent"] == 0
        # last_notification_sent NOT stamped (sender failed).
        s = persist.get_saved_searches_to_notify()[0]
        assert s["last_notification_sent"] is None

    def test_send_exception_counts_as_error(self, isolated_db):
        import persist
        persist.init_db()
        _seed_listing(persist, "L1", first_seen="2026-07-07T05:00:00Z")
        persist.upsert_saved_search(
            email="u@x.com", name="boom2", notify_on_match=True,
        )
        def _raise(*a, **kw):
            raise RuntimeError("simulated SendGrid outage")
        result = persist.check_and_send_saved_search_alerts(send_fn=_raise)
        assert result["errors"] == 1
        assert result["sent"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# TestApiToggleNotify (Flask test client)
# ─────────────────────────────────────────────────────────────────────────────

class TestApiToggleNotify:
    """POST /api/saved-searches/<id>/toggle-notify accepts/persists the flag."""

    def _client(self, isolated_db):
        """Build a Flask test client. The DB path is already patched by the
        `isolated_db` fixture — we just import app and reuse the test_client.
        We deliberately do NOT reload persist: reload would re-evaluate
        DATA_DIR = os.path.join(...) at module level and clobber our patch.
        """
        import app as app_module  # already imported at collection time
        return app_module.app.test_client()

    def test_toggle_on(self, isolated_db):
        import persist
        persist.init_db()
        sid = persist.upsert_saved_search(email="u@x.com", name="x", notify_on_match=False)
        client = self._client(isolated_db)
        res = client.post(
            f"/api/saved-searches/{sid}/toggle-notify",
            json={"email": "u@x.com", "notify": True},
        )
        assert res.status_code == 200, res.get_json()
        body = res.get_json()
        assert body["success"] is True
        assert body["notify_on_match"] == 1
        # Persisted.
        row = persist.get_saved_search_by_id("u@x.com", sid)
        assert int(row["notify_on_match"]) == 1

    def test_toggle_off(self, isolated_db):
        import persist
        persist.init_db()
        sid = persist.upsert_saved_search(email="u@x.com", name="x", notify_on_match=True)
        client = self._client(isolated_db)
        res = client.post(
            f"/api/saved-searches/{sid}/toggle-notify",
            json={"email": "u@x.com", "notify": False},
        )
        assert res.status_code == 200
        assert res.get_json()["notify_on_match"] == 0

    def test_missing_email_returns_400(self, isolated_db):
        import persist
        persist.init_db()
        sid = persist.upsert_saved_search(email="u@x.com", name="x")
        client = self._client(isolated_db)
        res = client.post(f"/api/saved-searches/{sid}/toggle-notify", json={"notify": True})
        assert res.status_code == 400

    def test_missing_notify_returns_400(self, isolated_db):
        import persist
        persist.init_db()
        sid = persist.upsert_saved_search(email="u@x.com", name="x")
        client = self._client(isolated_db)
        res = client.post(f"/api/saved-searches/{sid}/toggle-notify", json={"email": "u@x.com"})
        assert res.status_code == 400

    def test_unknown_id_returns_404(self, isolated_db):
        import persist
        persist.init_db()
        client = self._client(isolated_db)
        res = client.post(
            "/api/saved-searches/9999/toggle-notify",
            json={"email": "u@x.com", "notify": True},
        )
        assert res.status_code == 404

    def test_wrong_email_returns_404(self, isolated_db):
        import persist
        persist.init_db()
        sid = persist.upsert_saved_search(email="u@x.com", name="x")
        client = self._client(isolated_db)
        res = client.post(
            f"/api/saved-searches/{sid}/toggle-notify",
            json={"email": "other@x.com", "notify": True},
        )
        assert res.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# TestApiRunChecks — POST /api/saved-searches/run-checks
# ─────────────────────────────────────────────────────────────────────────────

class TestApiRunChecks:
    """POST /api/saved-searches/run-checks invokes the worker and returns the summary."""

    def _client(self, isolated_db):
        import app as app_module
        return app_module.app.test_client()

    def test_run_checks_invokes_worker(self, isolated_db, monkeypatch):
        import persist
        persist.init_db()
        _seed_listing(persist, "L1", first_seen="2026-07-07T05:00:00Z")
        persist.upsert_saved_search(
            email="u@x.com", name="x", notify_on_match=True,
        )
        # The endpoint does `from persist import check_and_send_saved_search_alerts`
        # inside the function — that import looks up persist's namespace at call
        # time, so a monkeypatch on persist is honored.
        sentinel = {
            "checked": 1, "sent": 1, "skipped_no_matches": 0,
            "skipped_rate_limit": 0, "errors": 0, "details": [],
        }
        monkeypatch.setattr(persist, "check_and_send_saved_search_alerts",
                            lambda min_hours_between=24, send_fn=None: sentinel)
        client = self._client(isolated_db)
        res = client.post("/api/saved-searches/run-checks", json={"min_hours_between": 24})
        assert res.status_code == 200
        body = res.get_json()
        assert body["success"] is True
        assert body["result"] == sentinel
