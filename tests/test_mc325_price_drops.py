"""
MC-325: Price-drop feature — comprehensive test coverage.

Covers:
  - persist.py: get_listing_price_drop / get_price_dropped_listing_ids /
    get_all_listing_price_drops / seed_price_history_for_listing
  - upsert_listings wiring: upsert_price_history is called per-row
  - app.py: _enrich_price_drops / _normalize_row shape / /api/deals?price_dropped=true
    filter / /api/meta.price_drop_count
  - templates/index.html wiring: toggle element, badge rendering, buildParams,
    parseQueryParams, resetFilters, updateFilterCount, getCurrentFilterStateAsObject,
    describeFilters, applySavedFilters, wiring array
  - backfill_mc325.py: dry-run + non-dry-run paths
"""

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# Ensure rent_finder/ is on sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import persist  # noqa: E402
import app      # noqa: E402


# ── Helpers ─────────────────────────────────────────────────────────────────

def _isolated_db(tmpdir: str) -> str:
    """Point persist at a fresh isolated DB inside tmpdir for the test."""
    db_path = os.path.join(tmpdir, 'listings.db')
    persist.DB_PATH = db_path
    app.DB_PATH = db_path
    # Close + clear the cached connection so the new DB_PATH is honoured
    try:
        persist._reset_conn()
    except AttributeError:
        pass
    persist.init_db()
    return db_path


def _seed_listing(listing_id: str, price: float = 2000.0, days_offset: int = 0):
    """Insert an active listing row so get_listing_price_drop can find it."""
    conn = sqlite3.connect(persist.DB_PATH)
    now = (datetime.now(timezone.utc) - timedelta(days=days_offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        conn.execute("""
            INSERT INTO listings (
                listing_id, source, title, price, beds, baths,
                neighborhood, region, url, image_url,
                days_ago, is_stale, first_seen, last_seen, is_active,
                scrape_count, is_new, fair_value, score, pct_under
            ) VALUES (?, 'kijiji', 'Test', ?, 1, 1, 'Annex', 'Downtown',
                      'http://x/' || ?, '', 1, 0, ?, ?, 1, 1, 0, 2000.0, 0.1, 0.05)
        """, (listing_id, price, listing_id, now, now))
        conn.commit()
    finally:
        conn.close()


# ── TestGetListingPriceDrop ─────────────────────────────────────────────────

class TestGetListingPriceDrop:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix='mc325_')
        _isolated_db(self.tmpdir)

    def teardown_method(self):
        import shutil
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_returns_none_for_no_history(self):
        _seed_listing('lid_no_history', price=2000.0)
        out = persist.get_listing_price_drop('lid_no_history', days=14)
        assert out is None, f'expected None, got {out}'

    def test_returns_none_for_single_history_point(self):
        _seed_listing('lid_one', price=2000.0)
        persist.seed_price_history_for_listing('lid_one', 2000.0, '2026-07-05T12:00:00Z')
        out = persist.get_listing_price_drop('lid_one', days=14)
        assert out is None, 'single price point should not produce a drop'

    def test_returns_none_when_price_increased(self):
        _seed_listing('lid_up', price=2000.0)
        persist.seed_price_history_for_listing('lid_up', 1800.0, '2026-07-05T12:00:00Z')
        persist.seed_price_history_for_listing('lid_up', 2000.0, '2026-07-07T12:00:00Z')
        out = persist.get_listing_price_drop('lid_up', days=14)
        assert out is None, f'price increase should not produce a drop, got {out}'

    def test_returns_drop_for_simple_price_cut(self):
        _seed_listing('lid_drop', price=1800.0)
        persist.seed_price_history_for_listing('lid_drop', 2000.0, '2026-07-05T12:00:00Z')
        persist.seed_price_history_for_listing('lid_drop', 1800.0, '2026-07-07T12:00:00Z')
        out = persist.get_listing_price_drop('lid_drop', days=14)
        assert out is not None
        assert out['from_price'] == 2000.0
        assert out['to_price'] == 1800.0
        assert out['drop_amount'] == 200.0
        assert abs(out['drop_pct'] - 10.0) < 0.01
        assert out['listing_id'] == 'lid_drop'

    def test_uses_oldest_price_in_window(self):
        _seed_listing('lid_oldest', price=1500.0)
        # Three price points: 2000 -> 1800 -> 1500. Oldest (2000) vs latest (1500).
        persist.seed_price_history_for_listing('lid_oldest', 2000.0, '2026-07-01T12:00:00Z')
        persist.seed_price_history_for_listing('lid_oldest', 1800.0, '2026-07-04T12:00:00Z')
        persist.seed_price_history_for_listing('lid_oldest', 1500.0, '2026-07-07T12:00:00Z')
        out = persist.get_listing_price_drop('lid_oldest', days=14)
        assert out is not None
        assert out['from_price'] == 2000.0, f"expected oldest=2000, got {out['from_price']}"
        assert out['to_price'] == 1500.0
        assert abs(out['drop_pct'] - 25.0) < 0.01

    def test_days_ago_from_uses_supplied_now(self):
        _seed_listing('lid_now', price=1900.0)
        persist.seed_price_history_for_listing('lid_now', 2000.0, '2026-07-07T12:00:00Z')
        persist.seed_price_history_for_listing('lid_now', 1900.0, '2026-07-08T12:00:00Z')
        out = persist.get_listing_price_drop('lid_now', days=14,
                                             now_ts='2026-07-15T12:00:00Z')
        assert out is not None
        assert out['days_ago_from'] == 8, f"expected 8 days, got {out['days_ago_from']}"

    def test_excludes_history_older_than_window(self):
        _seed_listing('lid_old', price=2000.0)
        # A drop 30 days ago should NOT count when the window is 14 days
        persist.seed_price_history_for_listing('lid_old', 2500.0, '2026-06-01T12:00:00Z')
        persist.seed_price_history_for_listing('lid_old', 2000.0, '2026-06-10T12:00:00Z')
        out = persist.get_listing_price_drop('lid_old', days=14)
        assert out is None, f'old price point outside 14d window should not count, got {out}'


# ── TestGetPriceDroppedListingIds ──────────────────────────────────────────

class TestGetPriceDroppedListingIds:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix='mc325_')
        _isolated_db(self.tmpdir)

    def teardown_method(self):
        import shutil
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_empty_initially(self):
        assert persist.get_price_dropped_listing_ids() == set()

    def test_returns_only_listings_meeting_threshold(self):
        # Active listing A: drop of 10% — should be returned at default 5% threshold
        _seed_listing('lid_a', price=1800.0)
        persist.seed_price_history_for_listing('lid_a', 2000.0, '2026-07-05T12:00:00Z')
        persist.seed_price_history_for_listing('lid_a', 1800.0, '2026-07-07T12:00:00Z')
        # Active listing B: drop of 3% — should NOT be returned at default 5% threshold
        _seed_listing('lid_b', price=1940.0)
        persist.seed_price_history_for_listing('lid_b', 2000.0, '2026-07-05T12:00:00Z')
        persist.seed_price_history_for_listing('lid_b', 1940.0, '2026-07-07T12:00:00Z')
        # Active listing C: no drop
        _seed_listing('lid_c', price=2000.0)
        persist.seed_price_history_for_listing('lid_c', 2000.0, '2026-07-07T12:00:00Z')

        out = persist.get_price_dropped_listing_ids(days=14, min_drop_pct=5.0)
        assert out == {'lid_a'}, f'expected {{lid_a}}, got {out}'

    def test_lower_threshold_picks_up_small_drops(self):
        _seed_listing('lid_small', price=1940.0)
        persist.seed_price_history_for_listing('lid_small', 2000.0, '2026-07-05T12:00:00Z')
        persist.seed_price_history_for_listing('lid_small', 1940.0, '2026-07-07T12:00:00Z')
        out_5 = persist.get_price_dropped_listing_ids(days=14, min_drop_pct=5.0)
        out_3 = persist.get_price_dropped_listing_ids(days=14, min_drop_pct=3.0)
        assert out_5 == set()
        assert out_3 == {'lid_small'}

    def test_excludes_inactive_listings(self):
        # Listing that would qualify but is not active
        _seed_listing('lid_inactive', price=1800.0)
        persist.seed_price_history_for_listing('lid_inactive', 2000.0, '2026-07-05T12:00:00Z')
        persist.seed_price_history_for_listing('lid_inactive', 1800.0, '2026-07-07T12:00:00Z')
        # Mark inactive
        conn = sqlite3.connect(persist.DB_PATH)
        conn.execute("UPDATE listings SET is_active = 0 WHERE listing_id = ?", ('lid_inactive',))
        conn.commit()
        conn.close()
        out = persist.get_price_dropped_listing_ids(days=14, min_drop_pct=5.0)
        assert 'lid_inactive' not in out


# ── TestGetAllListingPriceDrops ─────────────────────────────────────────────

class TestGetAllListingPriceDrops:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix='mc325_')
        _isolated_db(self.tmpdir)

    def teardown_method(self):
        import shutil
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_returns_dict_of_drop_info(self):
        _seed_listing('lid_x', price=1800.0)
        persist.seed_price_history_for_listing('lid_x', 2000.0, '2026-07-05T12:00:00Z')
        persist.seed_price_history_for_listing('lid_x', 1800.0, '2026-07-07T12:00:00Z')
        out = persist.get_all_listing_price_drops(days=14, min_drop_pct=5.0)
        assert 'lid_x' in out
        assert out['lid_x']['drop_pct'] == 10.0

    def test_empty_when_no_drops(self):
        assert persist.get_all_listing_price_drops() == {}


# ── TestSeedPriceHistoryForListing ──────────────────────────────────────────

class TestSeedPriceHistoryForListing:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix='mc325_')
        _isolated_db(self.tmpdir)

    def teardown_method(self):
        import shutil
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_inserts_new_row(self):
        ok = persist.seed_price_history_for_listing('lid_seed', 1500.0, '2026-07-05T12:00:00Z')
        assert ok is True
        conn = sqlite3.connect(persist.DB_PATH)
        row = conn.execute(
            "SELECT price FROM price_history WHERE listing_id=? AND seen_at=?",
            ('lid_seed', '2026-07-05T12:00:00Z')
        ).fetchone()
        assert row is not None and row[0] == 1500.0
        conn.close()

    def test_idempotent_on_duplicate_seen_at(self):
        persist.seed_price_history_for_listing('lid_dup', 1500.0, '2026-07-05T12:00:00Z')
        ok = persist.seed_price_history_for_listing('lid_dup', 1500.0, '2026-07-05T12:00:00Z')
        assert ok is False, 'second insert with same seen_at should not insert'
        conn = sqlite3.connect(persist.DB_PATH)
        n = conn.execute(
            "SELECT COUNT(*) FROM price_history WHERE listing_id=?",
            ('lid_dup',)
        ).fetchone()[0]
        conn.close()
        assert n == 1


# ── TestUpsertListingsWiresPriceHistory ─────────────────────────────────────

class TestUpsertListingsWiresPriceHistory:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix='mc325_')
        _isolated_db(self.tmpdir)

    def teardown_method(self):
        import shutil
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_upsert_listings_records_price_point(self):
        rows = [{
            'listing_id': 'lid_upsert_1',
            'source': 'kijiji',
            'title': 'Test',
            'price': 1750.0,
            'price_str': '$1,750',
            'beds': 1, 'baths': 1, 'sqft': None,
            'neighborhood': 'Annex',
            'region': 'Downtown',
            'url': 'http://x/lid_upsert_1',
            'image_url': '',
            'days_ago': 1,
            'is_stale': False,
        }]
        persist.upsert_listings(rows)
        # A price_history row should exist for this listing
        conn = sqlite3.connect(persist.DB_PATH)
        n = conn.execute(
            "SELECT COUNT(*) FROM price_history WHERE listing_id=?",
            ('lid_upsert_1',)
        ).fetchone()[0]
        conn.close()
        assert n >= 1, 'upsert_listings should record a price_history row'

    def test_upsert_listings_records_correct_price(self):
        rows = [{
            'listing_id': 'lid_upsert_2',
            'source': 'craigslist',
            'title': 'Test',
            'price': 2200.0,
            'price_str': '$2,200',
            'beds': 2, 'baths': 1, 'sqft': None,
            'neighborhood': 'Bay Street Corridor',
            'region': 'Downtown',
            'url': 'http://x/lid_upsert_2',
            'image_url': '',
            'days_ago': 1,
            'is_stale': False,
        }]
        persist.upsert_listings(rows)
        conn = sqlite3.connect(persist.DB_PATH)
        row = conn.execute(
            "SELECT price FROM price_history WHERE listing_id=? ORDER BY seen_at DESC LIMIT 1",
            ('lid_upsert_2',)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 2200.0

    def test_upsert_skips_zero_price(self):
        rows = [{
            'listing_id': 'lid_zero',
            'source': 'kijiji',
            'title': 'Test',
            'price': 0,
            'price_str': '',
            'beds': 1, 'baths': 1, 'sqft': None,
            'neighborhood': 'Annex',
            'region': 'Downtown',
            'url': 'http://x/lid_zero',
            'image_url': '',
            'days_ago': 1,
            'is_stale': False,
        }]
        # Should not raise; price=0 listings should not pollute price_history.
        persist.upsert_listings(rows)
        conn = sqlite3.connect(persist.DB_PATH)
        n = conn.execute(
            "SELECT COUNT(*) FROM price_history WHERE listing_id=?",
            ('lid_zero',)
        ).fetchone()[0]
        conn.close()
        assert n == 0


# ── TestApiDealsPriceDroppedFilter ──────────────────────────────────────────

class TestApiDealsPriceDroppedFilter:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix='mc325_')
        _isolated_db(self.tmpdir)

    def teardown_method(self):
        import shutil
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_default_endpoint_returns_all_rows_with_drop_fields(self):
        _seed_listing('lid_a', price=1800.0)
        _seed_listing('lid_b', price=2000.0)
        client = app.app.test_client()
        r = client.get('/api/deals')
        data = json.loads(r.data)
        assert r.status_code == 200
        for row in data['deals']:
            assert 'price_dropped' in row
            assert 'price_drop_pct' in row
            assert 'price_drop_amount' in row
            assert 'price_drop_from_price' in row
            assert 'price_drop_days_ago' in row

    def test_price_dropped_filter_excludes_non_drops(self):
        _seed_listing('lid_drop', price=1800.0)
        persist.seed_price_history_for_listing('lid_drop', 2000.0, '2026-07-05T12:00:00Z')
        persist.seed_price_history_for_listing('lid_drop', 1800.0, '2026-07-07T12:00:00Z')
        _seed_listing('lid_normal', price=2000.0)
        client = app.app.test_client()
        r = client.get('/api/deals?price_dropped=true')
        data = json.loads(r.data)
        assert r.status_code == 200
        ids = {row['listing_id'] for row in data['deals']}
        assert 'lid_drop' in ids
        assert 'lid_normal' not in ids
        assert all(row['price_dropped'] is True for row in data['deals'])

    def test_price_dropped_filter_explicit_falsy_returns_all(self):
        _seed_listing('lid_only', price=2000.0)
        client = app.app.test_client()
        r = client.get('/api/deals?price_dropped=false')
        data = json.loads(r.data)
        ids = {row['listing_id'] for row in data['deals']}
        assert 'lid_only' in ids

    def test_meta_includes_price_drop_count(self):
        _seed_listing('lid_meta', price=1800.0)
        persist.seed_price_history_for_listing('lid_meta', 2000.0, '2026-07-05T12:00:00Z')
        persist.seed_price_history_for_listing('lid_meta', 1800.0, '2026-07-07T12:00:00Z')
        client = app.app.test_client()
        r = client.get('/api/meta')
        data = json.loads(r.data)
        assert 'price_drop_count' in data
        assert data['price_drop_count'] >= 1

    def test_combined_filters_with_price_dropped(self):
        _seed_listing('lid_a', price=1800.0)
        persist.seed_price_history_for_listing('lid_a', 2000.0, '2026-07-05T12:00:00Z')
        persist.seed_price_history_for_listing('lid_a', 1800.0, '2026-07-07T12:00:00Z')
        _seed_listing('lid_b', price=1800.0)
        client = app.app.test_client()
        r = client.get('/api/deals?price_dropped=true&beds_min=2')
        data = json.loads(r.data)
        # lid_a has beds=1, so even though it's a drop, beds_min=2 excludes it.
        assert all(row.get('beds', 0) >= 2 for row in data['deals'])

    def test_enrich_price_drops_idempotent(self):
        # Re-running the enrich on already-enriched deals should not lose fields.
        rows = [{
            'listing_id': 'lid_idem',
            'source': 'kijiji',
            'title': 'Test',
            'price': 1800.0,
            'price_str': '$1,800',
            'beds': 1, 'baths': 1, 'sqft': None,
            'neighborhood': 'Annex',
            'region': 'Downtown',
            'url': 'http://x/lid_idem',
            'image_url': '',
            'days_ago': 1,
            'is_stale': False,
        }]
        persist.upsert_listings(rows)
        # Second upsert (no price change) — should still leave the fields populated
        persist.upsert_listings(rows)
        client = app.app.test_client()
        r = client.get('/api/deals')
        data = json.loads(r.data)
        rows_out = [r for r in data['deals'] if r['listing_id'] == 'lid_idem']
        assert len(rows_out) == 1
        assert rows_out[0]['price_dropped'] is False


# ── TestIndexHtmlWiring ─────────────────────────────────────────────────────

class TestIndexHtmlWiring:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix='mc325_')
        _isolated_db(self.tmpdir)

    def teardown_method(self):
        import shutil
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_index_has_price_drop_toggle(self):
        client = app.app.test_client()
        r = client.get('/')
        html = r.data.decode('utf-8', errors='ignore')
        assert 'id="price_drop_toggle"' in html
        assert 'id="price_dropped"' in html
        assert 'id="price_drop_count"' in html

    def test_index_has_price_drop_badge_css(self):
        client = app.app.test_client()
        html = client.get('/').data.decode('utf-8', errors='ignore')
        assert '.price-drop-badge' in html

    def test_index_renders_price_drop_badge_when_set(self):
        # The badge is JS-rendered; verify the JS literal exists.
        client = app.app.test_client()
        html = client.get('/').data.decode('utf-8', errors='ignore')
        assert 'priceDropTag' in html
        assert 'price_drop_pct' in html
        assert 'price_drop_from_price' in html

    def test_buildParams_includes_price_dropped(self):
        client = app.app.test_client()
        html = client.get('/').data.decode('utf-8', errors='ignore')
        assert "params.set('price_dropped'" in html

    def test_parseQueryParams_reads_price_dropped(self):
        client = app.app.test_client()
        html = client.get('/').data.decode('utf-8', errors='ignore')
        assert "params.get('price_dropped')" in html

    def test_reset_filters_clears_price_dropped(self):
        client = app.app.test_client()
        html = client.get('/').data.decode('utf-8', errors='ignore')
        # Look for the line in resetFilters that unchecks the toggle
        assert "document.getElementById('price_dropped').checked = false" in html
        assert "document.getElementById('price_drop_toggle').classList.remove('active')" in html

    def test_update_filter_count_includes_price_dropped(self):
        client = app.app.test_client()
        html = client.get('/').data.decode('utf-8', errors='ignore')
        # Find the updateFilterCount body and check it includes the increment
        import re
        m = re.search(r"function updateFilterCount\([^)]*\)\s*\{(.*?)\n\s*\}", html, re.DOTALL)
        assert m is not None, 'updateFilterCount function not found'
        body = m.group(1)
        assert "document.getElementById('price_dropped').checked" in body, (
            "updateFilterCount body should reference price_dropped"
        )

    def test_wiring_array_includes_price_dropped(self):
        client = app.app.test_client()
        html = client.get('/').data.decode('utf-8', errors='ignore')
        assert "'price_dropped'" in html

    def test_getCurrentFilterStateAsObject_includes_price_dropped(self):
        client = app.app.test_client()
        html = client.get('/').data.decode('utf-8', errors='ignore')
        assert "out.price_dropped = document.getElementById('price_dropped').checked" in html

    def test_describe_filters_includes_price_drop_label(self):
        client = app.app.test_client()
        html = client.get('/').data.decode('utf-8', errors='ignore')
        assert "Price drops" in html

    def test_apply_saved_filters_handles_price_dropped(self):
        client = app.app.test_client()
        html = client.get('/').data.decode('utf-8', errors='ignore')
        assert "filters.price_dropped === 'true'" in html

    def test_load_price_drop_count_badge_call_present(self):
        client = app.app.test_client()
        html = client.get('/').data.decode('utf-8', errors='ignore')
        assert 'loadPriceDropCountBadge()' in html

    def test_saved_searches_page_lists_price_drop_tag(self):
        client = app.app.test_client()
        html = client.get('/saved-searches').data.decode('utf-8', errors='ignore')
        assert 'price-drop-tag' in html


# ── TestBackfillM325 ────────────────────────────────────────────────────────

class TestBackfillM325:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix='mc325_back_')
        # Point persist at this temp dir
        _isolated_db(self.tmpdir)

    def teardown_method(self):
        import shutil
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_dry_run_does_not_write(self):
        import backfill_mc325
        # Write small raw files
        path = os.path.join(self.tmpdir, 'raw_2026-07-05.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump([
                {'listing_id': 'A1', 'price': 1500.0},
                {'listing_id': 'A2', 'price': 2200.0},
            ], f)
        summary = backfill_mc325.backfill(self.tmpdir, dry_run=True)
        assert summary['total_attempted'] == 2
        assert summary['total_inserted'] == 0
        conn = sqlite3.connect(persist.DB_PATH)
        n = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
        conn.close()
        assert n == 0

    def test_non_dry_run_inserts_rows(self):
        import backfill_mc325
        path = os.path.join(self.tmpdir, 'raw_2026-07-05.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump([
                {'listing_id': 'B1', 'price': 1500.0},
                {'listing_id': 'B2', 'price': 2200.0},
            ], f)
        summary = backfill_mc325.backfill(self.tmpdir, dry_run=False)
        assert summary['total_attempted'] == 2
        assert summary['total_inserted'] == 2
        conn = sqlite3.connect(persist.DB_PATH)
        n = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
        conn.close()
        assert n == 2

    def test_skips_missing_files(self):
        import backfill_mc325
        # No raw files at all
        summary = backfill_mc325.backfill(self.tmpdir, dry_run=True)
        assert summary['total_attempted'] == 0

    def test_detects_drop_after_backfill(self):
        import backfill_mc325
        # Day 1: price = 2000
        with open(os.path.join(self.tmpdir, 'raw_2026-07-05.json'), 'w', encoding='utf-8') as f:
            json.dump([{'listing_id': 'DROP_ME', 'price': 2000.0}], f)
        # Day 2: same listing, price = 1800 (10% drop)
        with open(os.path.join(self.tmpdir, 'raw_2026-07-07.json'), 'w', encoding='utf-8') as f:
            json.dump([{'listing_id': 'DROP_ME', 'price': 1800.0}], f)
        # Seed the active listing so it's not excluded by the active-set filter
        _seed_listing('DROP_ME', price=1800.0)
        summary = backfill_mc325.backfill(self.tmpdir, dry_run=False)
        assert summary['all_dropped_count'] >= 1
        drops = persist.get_all_listing_price_drops(days=14, min_drop_pct=5.0)
        assert 'DROP_ME' in drops
        assert abs(drops['DROP_ME']['drop_pct'] - 10.0) < 0.01

    def test_idempotent_on_repeat_run(self):
        import backfill_mc325
        with open(os.path.join(self.tmpdir, 'raw_2026-07-05.json'), 'w', encoding='utf-8') as f:
            json.dump([{'listing_id': 'IDEM', 'price': 1500.0}], f)
        backfill_mc325.backfill(self.tmpdir, dry_run=False)
        backfill_mc325.backfill(self.tmpdir, dry_run=False)
        conn = sqlite3.connect(persist.DB_PATH)
        n = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
        conn.close()
        assert n == 1, f'expected 1 row, got {n}'


# ── TestLiveSmoke ───────────────────────────────────────────────────────────

class TestLiveSmoke:
    """Verifies the feature works end-to-end with a realistic backfill."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix='mc325_smoke_')
        _isolated_db(self.tmpdir)

    def teardown_method(self):
        import shutil
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_end_to_end_with_synthetic_drop(self):
        """Insert 2 listings, simulate a 10% drop on one, verify the API returns it."""
        _seed_listing('dropper', price=1800.0)
        _seed_listing('keeper', price=2200.0)
        # Inject price history: dropper went 2000 -> 1800, keeper stayed 2200
        persist.seed_price_history_for_listing('dropper', 2000.0, '2026-07-05T12:00:00Z')
        persist.seed_price_history_for_listing('dropper', 1800.0, '2026-07-07T12:00:00Z')
        persist.seed_price_history_for_listing('keeper', 2200.0, '2026-07-05T12:00:00Z')
        persist.seed_price_history_for_listing('keeper', 2200.0, '2026-07-07T12:00:00Z')

        client = app.app.test_client()
        r = client.get('/api/deals?price_dropped=true')
        data = json.loads(r.data)
        ids = {row['listing_id'] for row in data['deals']}
        assert 'dropper' in ids, f'expected dropper in results, got {ids}'
        assert 'keeper' not in ids

        # Verify the row has the badge fields populated
        dropper = next(row for row in data['deals'] if row['listing_id'] == 'dropper')
        assert dropper['price_dropped'] is True
        assert dropper['price_drop_pct'] == 10.0
        assert dropper['price_drop_from_price'] == 2000.0
        assert dropper['price_drop_amount'] == 200.0

        # Verify meta
        meta = json.loads(client.get('/api/meta').data)
        assert meta['price_drop_count'] == 1