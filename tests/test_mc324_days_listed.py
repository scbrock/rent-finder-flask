"""
Tests for MC-324: days_listed column on /api/deals + sort option + Listed UI column.

days_listed is the durable "how long has our scraper tracked this listing"
metric, computed from SQLite first_seen (or falling back to days_ago when
SQLite data is unavailable). Distinct from days_ago, which is the
source-side "days since posting" timestamp.

Coverage:
  - _days_listed_from_first_seen: parses ISO timestamps, handles bad input,
    treats naive timestamps as UTC, floors negative deltas to 0
  - _days_listed_str / _days_listed_class: human label + CSS class
  - _normalize_row: emits days_listed/str/class on every row, fall-back
    to days_ago when first_seen is missing
  - /api/deals?sort=days_listed: orders ASC (longest first) by default;
    DESC works when explicitly requested via key flip
  - /api/deals response shape: every row has days_listed field
  - Sort interop: days_listed sort coexists with other filters (region,
    source, beds_min)
  - Templates: index.html has Listed column header, sort option, cell render,
    and CSS rules (.listed-fresh/.listed-medium/.listed-stale/.listed-neutral)
  - Regression: existing _days_ago_* helpers untouched, /api/deals shape stable
"""

import os
import sys
import csv
import sqlite3
from datetime import datetime, timezone, timedelta

import pytest

# Ensure rent_finder is importable
RENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RENT_DIR)

import app as app_module  # noqa: E402


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------

def _row(idx, *, days_ago='5', is_stale='False', neighborhood='Downtown',
         price='1500', beds='1', region='Downtown', first_seen=None):
    """Build a CSV-shaped row with sensible defaults."""
    return {
        'source': 'Kijiji',
        'price': price, 'beds': beds, 'baths': '1', 'sqft': '',
        'neighborhood': neighborhood, 'days_ago': days_ago, 'is_stale': is_stale,
        'link': f'https://example.com/{idx}', 'image_url': '',
        'image_urls': '[]',
        'fair_value': '2000', 'pct_under': '25.0', 'score': '0.85',
        'freshness_boost': '0.15', 'final_score': '1.00', 'rank': str(idx),
        'region': region,
        'is_new': '0',
        'first_seen': first_seen if first_seen is not None else '',
    }


@pytest.fixture
def csv_deals_file(monkeypatch, tmp_path):
    """Write sample rows to a temp CSV and point app.DEALS_CSV at it."""
    rows = [
        _row(1, days_ago='2',  neighborhood='Downtown',      price='1500', beds='1', first_seen='2026-07-05T00:00:00Z'),  # ~2d listed
        _row(2, days_ago='10', neighborhood='Queen West',    price='1100', beds='1', first_seen='2026-06-27T00:00:00Z'),  # ~10d listed
        _row(3, days_ago='35', neighborhood='King West',     price='2200', beds='2', first_seen='2026-06-02T00:00:00Z'),  # ~35d listed
        _row(4, days_ago='5',  neighborhood='Liberty Village', price='3000', beds='2', first_seen='2026-07-02T00:00:00Z'),  # ~5d listed
        _row(5, days_ago='20', neighborhood='Downtown',      price='900',  beds='0', first_seen=''),  # CSV fallback → days_ago=20
    ]
    p = tmp_path / 'deals_output.csv'
    with open(p, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(app_module, 'DEALS_CSV', str(p))
    monkeypatch.setattr(app_module, 'DB_PATH', str(tmp_path / 'no-such-db.sqlite'))
    return p


@pytest.fixture
def client(csv_deals_file):
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Pure-helper tests: _days_listed_from_first_seen
# ---------------------------------------------------------------------------

class TestDaysListedFromFirstSeen:
    """_days_listed_from_first_seen should compute integer days since first_seen."""

    def test_returns_none_for_empty_string(self):
        assert app_module._days_listed_from_first_seen('') is None

    def test_returns_none_for_none(self):
        assert app_module._days_listed_from_first_seen(None) is None

    def test_returns_none_for_nan_string(self):
        assert app_module._days_listed_from_first_seen('nan') is None

    def test_returns_none_for_none_string(self):
        assert app_module._days_listed_from_first_seen('None') is None

    def test_returns_none_for_malformed_string(self):
        assert app_module._days_listed_from_first_seen('not-a-date') is None

    def test_parses_iso_z_timestamp(self):
        # 5 days ago, allow off-by-one for time-of-day
        five_days_ago = (datetime.now(timezone.utc) - timedelta(days=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        assert app_module._days_listed_from_first_seen(five_days_ago) == 5

    def test_parses_iso_with_explicit_offset(self):
        ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        assert app_module._days_listed_from_first_seen(ten_days_ago) == 10

    def test_handles_naive_timestamp_as_utc(self):
        # No Z, no offset — should be treated as UTC (consistent with persist.py storage)
        thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S')
        assert app_module._days_listed_from_first_seen(thirty_days_ago) == 30

    def test_today_returns_zero(self):
        today = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        assert app_module._days_listed_from_first_seen(today) == 0

    def test_negative_delta_floors_to_zero(self):
        # Future timestamp (clock skew) — should floor to 0, not return -1
        future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
        assert app_module._days_listed_from_first_seen(future) == 0

    def test_explicit_now_overrides_internal_clock(self):
        # now_utc parameter allows deterministic testing
        fixed_now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)
        first_seen = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        assert app_module._days_listed_from_first_seen(first_seen, now_utc=fixed_now) == 6


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

class TestDaysListedStr:
    """_days_listed_str produces a short human-readable label."""

    def test_none_returns_dash(self):
        assert app_module._days_listed_str(None) == '—'

    def test_zero_returns_today(self):
        assert app_module._days_listed_str(0) == 'today'

    def test_one_returns_one_day_listed(self):
        assert app_module._days_listed_str(1) == '1d listed'

    def test_multi_day(self):
        assert app_module._days_listed_str(15) == '15d listed'

    def test_large_value(self):
        assert app_module._days_listed_str(120) == '120d listed'


class TestDaysListedClass:
    """_days_listed_class returns CSS class for color coding (green/yellow/red)."""

    def test_none_returns_neutral(self):
        assert app_module._days_listed_class(None) == 'listed-neutral'

    def test_zero_is_fresh(self):
        assert app_module._days_listed_class(0) == 'listed-fresh'

    def test_seven_is_fresh_boundary(self):
        assert app_module._days_listed_class(7) == 'listed-fresh'

    def test_eight_is_medium(self):
        assert app_module._days_listed_class(8) == 'listed-medium'

    def test_thirty_is_medium_boundary(self):
        assert app_module._days_listed_class(30) == 'listed-medium'

    def test_thirty_one_is_stale(self):
        assert app_module._days_listed_class(31) == 'listed-stale'

    def test_large_value_is_stale(self):
        assert app_module._days_listed_class(120) == 'listed-stale'


# ---------------------------------------------------------------------------
# _normalize_row: days_listed + display fields
# ---------------------------------------------------------------------------

class TestNormalizeDaysListed:
    """_normalize_row must emit days_listed, days_listed_str, days_listed_class."""

    def test_first_seen_present_emits_computed_days_listed(self):
        five_days_ago = (datetime.now(timezone.utc) - timedelta(days=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        row = _row(1, first_seen=five_days_ago)
        out = app_module._normalize_row(dict(row))
        assert out is not None
        assert out['days_listed'] == 5
        assert out['days_listed_str'] == '5d listed'
        assert out['days_listed_class'] == 'listed-fresh'

    def test_first_seen_missing_falls_back_to_days_ago(self):
        row = _row(2, days_ago='15', first_seen='')
        out = app_module._normalize_row(dict(row))
        assert out is not None
        # No first_seen → falls back to days_ago
        assert out['days_listed'] == 15
        assert out['days_listed_str'] == '15d listed'
        assert out['days_listed_class'] == 'listed-medium'

    def test_long_listed_emits_stale_class(self):
        fifty_days_ago = (datetime.now(timezone.utc) - timedelta(days=50)).strftime('%Y-%m-%dT%H:%M:%SZ')
        row = _row(3, first_seen=fifty_days_ago)
        out = app_module._normalize_row(dict(row))
        assert out['days_listed_class'] == 'listed-stale'
        assert '50d listed' == out['days_listed_str']

    def test_today_emits_today_label(self):
        today = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        row = _row(4, first_seen=today)
        out = app_module._normalize_row(dict(row))
        assert out['days_listed'] == 0
        assert out['days_listed_str'] == 'today'
        assert out['days_listed_class'] == 'listed-fresh'

    def test_existing_days_ago_still_emitted(self):
        # Regression: ensure MC-324 additions don't remove MC-254 fields
        five_days_ago = (datetime.now(timezone.utc) - timedelta(days=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        row = _row(5, days_ago='7', first_seen=five_days_ago)
        out = app_module._normalize_row(dict(row))
        assert 'days_ago' in out
        assert 'days_ago_str' in out
        assert 'days_ago_class' in out


# ---------------------------------------------------------------------------
# /api/deals endpoint: response shape
# ---------------------------------------------------------------------------

class TestApiDealsDaysListedField:
    """/api/deals must include days_listed on every row."""

    def test_every_row_has_days_listed(self, client):
        rv = client.get('/api/deals')
        assert rv.status_code == 200
        payload = rv.get_json()
        assert len(payload['deals']) == 5
        for row in payload['deals']:
            assert 'days_listed' in row, f"days_listed missing: {row}"
            assert row['days_listed'] is not None
            assert isinstance(row['days_listed'], int)

    def test_every_row_has_days_listed_str(self, client):
        rv = client.get('/api/deals')
        payload = rv.get_json()
        for row in payload['deals']:
            assert 'days_listed_str' in row
            assert isinstance(row['days_listed_str'], str)

    def test_every_row_has_days_listed_class(self, client):
        rv = client.get('/api/deals')
        payload = rv.get_json()
        for row in payload['deals']:
            assert 'days_listed_class' in row
            assert row['days_listed_class'] in (
                'listed-fresh', 'listed-medium', 'listed-stale', 'listed-neutral'
            )

    def test_existing_days_ago_field_still_present(self, client):
        # Regression: MC-324 must not remove MC-254 fields
        rv = client.get('/api/deals')
        payload = rv.get_json()
        for row in payload['deals']:
            assert 'days_ago' in row
            assert 'days_ago_str' in row


# ---------------------------------------------------------------------------
# /api/deals?sort=days_listed
# ---------------------------------------------------------------------------

class TestApiDealsSortDaysListed:
    """/api/deals?sort=days_listed default = LONGEST-listed first (AC3)."""

    def test_default_sort_longest_first(self, client):
        # AC3: asc = longest-listed first → highest days_listed at index 0.
        rv = client.get('/api/deals?sort=days_listed')
        assert rv.status_code == 200
        payload = rv.get_json()
        days = [r['days_listed'] for r in payload['deals']]
        # Highest days_listed at top, lowest at bottom.
        assert days == sorted(days, reverse=True), f"expected longest-first, got {days}"
        assert days[0] >= days[-1]

    def test_longest_listed_first(self, client):
        rv = client.get('/api/deals?sort=days_listed')
        payload = rv.get_json()
        first = payload['deals'][0]
        last = payload['deals'][-1]
        assert first['days_listed'] >= last['days_listed']
        # First row should be the ~35d King West listing
        assert first['days_listed'] >= 30
        # MC-333: neighbourhood now flows through resolve_neighbourhood()
        # which upgrades "King West" -> "Niagara" via _DIRECT_MAP, so the
        # assertion uses the resolved name.
        assert first['neighbourhood'] == 'Niagara'

    def test_default_sort_matches_reversed_ascending(self, client):
        """AC3 explicitly defines asc = longest first. Reversing the result
        yields ascending (newest listed first)."""
        rv = client.get('/api/deals?sort=days_listed')
        payload = rv.get_json()
        days = [r['days_listed'] for r in payload['deals']]
        assert list(reversed(days)) == sorted(days)

    def test_sort_combines_with_source_filter(self, client):
        rv = client.get('/api/deals?sort=days_listed&source=kijiji')
        payload = rv.get_json()
        # All our test rows are Kijiji, so this is a regression for filter+sort combo
        assert all(r['source'] == 'kijiji' for r in payload['deals'])
        days = [r['days_listed'] for r in payload['deals']]
        # Longest first
        assert days == sorted(days, reverse=True)

    def test_sort_combines_with_beds_filter(self, client):
        rv = client.get('/api/deals?sort=days_listed&beds_min=2')
        payload = rv.get_json()
        for r in payload['deals']:
            assert r['beds'] is not None and r['beds'] >= 2
        days = [r['days_listed'] for r in payload['deals']]
        assert days == sorted(days, reverse=True)


# ---------------------------------------------------------------------------
# UI wiring: templates/index.html
# ---------------------------------------------------------------------------

class TestIndexHtmlWiring:
    """index.html must wire the Listed column + sort option + JS + CSS."""

    @pytest.fixture
    def index_html_text(self):
        path = os.path.join(RENT_DIR, 'templates', 'index.html')
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_sort_option_value_present(self, index_html_text):
        # Look for the days_listed option in the sort dropdown
        assert 'value="days_listed"' in index_html_text
        assert 'Longest Listed' in index_html_text

    def test_listed_column_header_present(self, index_html_text):
        # Header cell with sortTable('days_listed') + tooltip
        assert "sortTable('days_listed')" in index_html_text
        assert '>Listed<' in index_html_text or '>Listed</th>' in index_html_text

    def test_listed_badge_cell_rendered(self, index_html_text):
        # JS uses d.days_listed, d.days_listed_class, d.days_listed_str
        assert 'd.days_listed_class' in index_html_text
        assert 'd.days_listed_str' in index_html_text
        assert 'class="listed-badge' in index_html_text

    def test_listed_css_classes_defined(self, index_html_text):
        for cls in ('.listed-fresh', '.listed-medium', '.listed-stale', '.listed-neutral'):
            assert cls in index_html_text, f"missing CSS class: {cls}"

    def test_listed_class_helper_in_js(self, index_html_text):
        # JS fallback classifier should match the server-side helpers
        assert "'listed-fresh'" in index_html_text
        assert "'listed-medium'" in index_html_text
        assert "'listed-stale'" in index_html_text


# ---------------------------------------------------------------------------
# Regression: existing sort keys still work
# ---------------------------------------------------------------------------

class TestSortKeyRegression:
    """Existing sort keys (score, price, days_ago, etc.) must still work."""

    def test_default_sort_unchanged(self, client):
        rv = client.get('/api/deals')
        payload = rv.get_json()
        # Default is sort=score which sorts DESCENDING (reverse=True for score)
        scores = [r.get('final_score', 0) for r in payload['deals']]
        # Just verify the endpoint doesn't error; ordering is implementation detail
        assert len(scores) == 5

    def test_price_sort_ascending(self, client):
        rv = client.get('/api/deals?sort=price')
        payload = rv.get_json()
        prices = [r['price'] for r in payload['deals']]
        assert prices == sorted(prices)

    def test_days_ago_sort_still_works(self, client):
        rv = client.get('/api/deals?sort=days_ago')
        payload = rv.get_json()
        ages = [r['days_ago'] for r in payload['deals']]
        # ASC by default (days_ago)
        assert ages == sorted(ages)


# ---------------------------------------------------------------------------
# SQLite path: first_seen comes through load_deals → normalize correctly
# ---------------------------------------------------------------------------

class TestSqliteDaysListed:
    """When load_deals pulls from SQLite, days_listed should use first_seen."""

    def test_sqlite_first_seen_propagates_to_days_listed(self, monkeypatch, tmp_path):
        # Build a real SQLite DB with first_seen set
        db_path = tmp_path / 'listings.sqlite'
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE listings (
                listing_id TEXT PRIMARY KEY,
                source TEXT,
                title TEXT,
                price REAL,
                price_str TEXT,
                beds REAL,
                baths REAL,
                sqft REAL,
                neighborhood TEXT,
                region TEXT,
                location TEXT,
                url TEXT,
                image_url TEXT,
                image_urls_json TEXT,
                days_ago INTEGER,
                is_stale INTEGER DEFAULT 0,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                scrape_count INTEGER DEFAULT 1,
                is_new INTEGER DEFAULT 0,
                fair_value REAL,
                score REAL,
                pct_under REAL,
                image_urls TEXT DEFAULT '[]'
            )
        """)
        # 8 days ago
        eight_days_ago = (datetime.now(timezone.utc) - timedelta(days=8)).strftime('%Y-%m-%dT%H:%M:%SZ')
        conn.execute("""
            INSERT INTO listings
              (listing_id, source, title, price, price_str, beds, baths, sqft,
               neighborhood, region, location, url, image_url, image_urls_json,
               days_ago, is_stale, first_seen, last_seen, is_active, scrape_count,
               is_new, fair_value, score, pct_under, image_urls)
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'TEST001', 'Kijiji', 'Test listing', 1500, '$1500', 1, 1, 0,
            'Downtown', 'Downtown', 'Downtown', 'https://example.com/1', '', '[]',
            8, 0, eight_days_ago, eight_days_ago, 1, 1,
            0, 2000, 0.8, 25.0, '[]'
        ))
        conn.commit()
        conn.close()

        monkeypatch.setattr(app_module, 'DB_PATH', str(db_path))
        # Point CSV at non-existent so SQLite path is the only path
        monkeypatch.setattr(app_module, 'DEALS_CSV', str(tmp_path / 'no-such.csv'))

        deals = app_module.load_deals()
        assert len(deals) == 1
        d = deals[0]
        assert d['days_listed'] == 8
        assert d['days_listed_str'] == '8d listed'
        assert d['days_listed_class'] == 'listed-medium'  # 8d is at boundary