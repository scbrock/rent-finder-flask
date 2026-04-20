"""
MC-282: Tests for price history chart endpoint and get_price_history / get_all_price_trends
"""
import os
import sys
import json
import pytest
from unittest.mock import patch

# Make rent_finder importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['RENT_DATA_DIR'] = os.path.join(os.path.dirname(__file__), 'test_data_mc282')
os.makedirs(os.environ['RENT_DATA_DIR'], exist_ok=True)

import persist
from app import app


@pytest.fixture(autouse=True)
def clean_db():
    """Clear price_history tables before/after each test for isolation."""
    import importlib
    importlib.reload(persist)
    persist.init_db()
    # Clear relevant tables before test
    conn = persist._get_conn()
    conn.execute("DELETE FROM price_history")
    conn.execute("DELETE FROM price_drop_alerts")
    conn.commit()
    conn.close()
    yield
    # Clear after test
    conn = persist._get_conn()
    conn.execute("DELETE FROM price_history")
    conn.execute("DELETE FROM price_drop_alerts")
    conn.commit()
    conn.close()


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


# ── Unit tests for persist layer ─────────────────────────────────────────────

class TestGetPriceHistory:
    def test_empty_returns_empty_list(self):
        result = persist.get_price_history('no-such-listing', days=30)
        assert result == []

    def test_single_point_returned(self):
        persist.upsert_price_history('listing-abc', 2500.0)
        result = persist.get_price_history('listing-abc', days=30)
        assert len(result) == 1
        assert result[0]['price'] == 2500.0
        assert 'ts' in result[0]

    def test_multiple_points_sorted_oldest_first(self):
        from datetime import datetime, timezone, timedelta
        conn = persist._get_conn()
        for i, delta in enumerate([5, 3, 1]):
            ts = (datetime.now(timezone.utc) - timedelta(days=delta)).strftime('%Y-%m-%dT%H:%M:%SZ')
            conn.execute(
                "INSERT OR IGNORE INTO price_history (listing_id, price, seen_at) VALUES (?, ?, ?)",
                ('listing-multi', 2000.0 - i * 100, ts)
            )
        conn.commit()
        conn.close()
        result = persist.get_price_history('listing-multi', days=30)
        assert len(result) == 3
        # Oldest first (lowest delta = most recent, so largest delta = oldest)
        prices = [r['price'] for r in result]
        assert prices == sorted(prices, reverse=True)  # 2000, 1900, 1800

    def test_days_filter_excludes_old_entries(self):
        from datetime import datetime, timezone, timedelta
        conn = persist._get_conn()
        # One recent, one old (60 days ago)
        recent_ts = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).strftime('%Y-%m-%dT%H:%M:%SZ')
        conn.execute("INSERT OR IGNORE INTO price_history (listing_id, price, seen_at) VALUES (?, ?, ?)",
                     ('listing-filter', 2200.0, recent_ts))
        conn.execute("INSERT OR IGNORE INTO price_history (listing_id, price, seen_at) VALUES (?, ?, ?)",
                     ('listing-filter', 2500.0, old_ts))
        conn.commit()
        conn.close()
        result = persist.get_price_history('listing-filter', days=30)
        assert len(result) == 1
        assert result[0]['price'] == 2200.0


class TestGetAllPriceTrends:
    def _insert_history(self, listing_id, prices_with_days):
        """Insert price points: prices_with_days = [(price, days_ago), ...]"""
        from datetime import datetime, timezone, timedelta
        conn = persist._get_conn()
        for price, days_ago in prices_with_days:
            ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime('%Y-%m-%dT%H:%M:%SZ')
            conn.execute("INSERT OR IGNORE INTO price_history (listing_id, price, seen_at) VALUES (?, ?, ?)",
                         (listing_id, price, ts))
        conn.commit()
        conn.close()

    def test_empty_db_returns_empty_dict(self):
        result = persist.get_all_price_trends(days=30)
        assert result == {}

    def test_single_point_not_included(self):
        persist.upsert_price_history('only-one', 2000.0)
        result = persist.get_all_price_trends(days=30)
        assert 'only-one' not in result

    def test_price_drop_returns_down(self):
        self._insert_history('drop-listing', [(2500.0, 5), (2200.0, 1)])
        result = persist.get_all_price_trends(days=30)
        assert result.get('drop-listing') == 'down'

    def test_price_rise_returns_up(self):
        self._insert_history('rise-listing', [(1800.0, 5), (2100.0, 1)])
        result = persist.get_all_price_trends(days=30)
        assert result.get('rise-listing') == 'up'

    def test_stable_price_returns_stable(self):
        self._insert_history('stable-listing', [(2000.0, 5), (2000.0, 1)])
        result = persist.get_all_price_trends(days=30)
        assert result.get('stable-listing') == 'stable'


# ── HTTP endpoint tests ───────────────────────────────────────────────────────

class TestApiPriceHistory:
    def test_missing_id_returns_400(self, client):
        resp = client.get('/api/price-history')
        assert resp.status_code == 400
        assert b'id required' in resp.data

    def test_unknown_listing_returns_empty(self, client):
        resp = client.get('/api/price-history?id=no-such-listing')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['count'] == 0
        assert data['history'] == []
        assert data['trend'] == 'stable'

    def test_listing_with_history_returns_data(self, client):
        persist.upsert_price_history('test-listing-xyz', 2400.0)
        resp = client.get('/api/price-history?id=test-listing-xyz')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['count'] == 1
        assert data['history'][0]['price'] == 2400.0

    def test_trend_field_present(self, client):
        resp = client.get('/api/price-history?id=any-listing')
        data = json.loads(resp.data)
        assert 'trend' in data
        assert data['trend'] in ('up', 'down', 'stable')


class TestApiTrends:
    def test_returns_200_with_trends_key(self, client):
        resp = client.get('/api/trends')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert 'trends' in data
        assert 'count' in data

    def test_empty_db_returns_empty_trends(self, client):
        resp = client.get('/api/trends')
        data = json.loads(resp.data)
        assert data['trends'] == {}
        assert data['count'] == 0
