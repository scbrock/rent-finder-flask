"""
Tests for MC-284: SMS Alert System.

Covers:
- sms_alerts.normalize_phone()
- sms_alerts.send_sms_alert() (mocked Twilio)
- sms_alerts.check_and_send_sms_alerts() (mocked subscriptions + deals)
- persist SMS CRUD functions
- app.py SMS endpoints
"""

import pytest, os, sqlite3, json
from unittest.mock import patch, MagicMock

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DATA_DIR = os.path.join(TEST_DIR, 'data')
TEST_DB = os.path.join(TEST_DATA_DIR, 'test_sms.db')


def _init_test_db():
    """Build the test DB schema in TEST_DATA_DIR/listings.db (persist.DB_PATH pattern)."""
    os.makedirs(TEST_DATA_DIR, exist_ok=True)
    # persist.DB_PATH = os.path.join(DATA_DIR, "listings.db") — always "listings.db"
    db_path = os.path.join(TEST_DATA_DIR, 'listings.db')
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scrape_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            source TEXT NOT NULL, listings_seen INTEGER NOT NULL DEFAULT 0,
            listings_new INTEGER NOT NULL DEFAULT 0, listings_inactive INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS listings (
            listing_id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT,
            price REAL NOT NULL, price_str TEXT, beds REAL, baths REAL, sqft REAL,
            neighborhood TEXT, region TEXT, location TEXT, url TEXT, image_url TEXT,
            days_ago INTEGER, is_stale INTEGER NOT NULL DEFAULT 0,
            first_seen TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            last_seen TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            is_active INTEGER NOT NULL DEFAULT 1, scrape_count INTEGER NOT NULL DEFAULT 1,
            is_new INTEGER NOT NULL DEFAULT 0, fair_value REAL, score REAL, pct_under REAL
        );
        CREATE TABLE IF NOT EXISTS user_alerts (
            alert_id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
            region TEXT, min_beds REAL, max_price REAL, min_score REAL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            is_enabled INTEGER NOT NULL DEFAULT 1, last_sent TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS sms_subscriptions (
            sub_id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL, max_price REAL, min_beds REAL, neighbourhood TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            last_alerted TEXT
        );
        CREATE INDEX idx_listings_active ON listings(is_active);
        CREATE INDEX idx_listings_region ON listings(region);
    """)
    conn.close()
    return db_path  # This is TEST_DATA_DIR/listings.db == persist.DB_PATH for tests


@pytest.fixture(autouse=True)
def fresh_db():
    """Reset persist's cached connection so it opens the fresh test DB."""
    _init_test_db()
    # Must set env BEFORE importing persist (DATA_DIR is set at import time)
    os.environ['RENT_DATA_DIR'] = TEST_DATA_DIR

    import importlib, persist
    persist._reset_conn()          # close any open cached conn
    importlib.reload(persist)       # reload to pick up the new DATA_DIR

    yield

    try:
        persist._reset_conn()
    except Exception:
        pass
    # Clean up the test listings.db
    test_db = os.path.join(TEST_DATA_DIR, 'listings.db')
    if os.path.exists(test_db):
        try:
            os.remove(test_db)
        except Exception:
            pass


# ── normalize_phone ──────────────────────────────────────────────────────────

class TestNormalizePhone:
    def _norm(self, phone):
        from sms_alerts import normalize_phone
        return normalize_phone(phone)

    def test_10_digit_local(self):
        assert self._norm('4165551234') == '+14165551234'

    def test_10_digit_with_dashes(self):
        assert self._norm('416-555-1234') == '+14165551234'

    def test_10_digit_with_parens(self):
        assert self._norm('(416) 555-1234') == '+14165551234'

    def test_11_digit_with_1_prefix(self):
        assert self._norm('14165551234') == '+14165551234'

    def test_e164_already(self):
        assert self._norm('+14165551234') == '+14165551234'

    def test_international(self):
        assert self._norm('+44 7911 123456') == '+447911123456'

    def test_too_short(self):
        from sms_alerts import normalize_phone
        with pytest.raises(ValueError, match='at least 10 digits'):
            normalize_phone('12345')


# ── send_sms_alert ───────────────────────────────────────────────────────────

class TestSendSmsAlert:
    @patch.dict(os.environ, {
        'TWILIO_ACCOUNT_SID': 'ACxxx',
        'TWILIO_AUTH_TOKEN': 'tok',
        'TWILIO_FROM_NUMBER': '+14165550000'
    })
    @patch('twilio.rest.Client')
    def test_send_sms_calls_twilio(self, mock_client_cls):
        mock_msg = MagicMock()
        mock_msg.sid = 'SM12345'
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_client_cls.return_value = mock_client

        import importlib
        import sms_alerts as _sms
        importlib.reload(_sms)

        sid = _sms.send_sms_alert(
            '+14165551234', 'King West', 2100, 1, 18.5, 0.22, 'http://x.com'
        )

        assert sid == 'SM12345'
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs['to'] == '+14165551234'
        assert call_kwargs['from_'] == '+14165550000'
        assert 'King West' in call_kwargs['body']
        assert '$2,100' in call_kwargs['body']

    @patch.dict(os.environ, {
        'TWILIO_ACCOUNT_SID': '',
        'TWILIO_AUTH_TOKEN': '',
        'TWILIO_FROM_NUMBER': ''
    })
    def test_raises_when_not_configured(self):
        import importlib
        import sms_alerts as _sms
        importlib.reload(_sms)
        with pytest.raises(RuntimeError, match='Twilio credentials not configured'):
            _sms.send_sms_alert('+14165551234', 'King West', 2100, 1, 18.5, 0.22, 'http://x.com')


# ── SMS persistence functions ─────────────────────────────────────────────────

class TestSmsPersistence:
    def test_upsert_sms_subscription(self):
        import persist
        sub_id = persist.upsert_sms_subscription(
            phone='+14165551234', email='test@example.com',
            max_price=2500.0, min_beds=1.0, neighbourhood='Downtown'
        )
        assert sub_id is not None
        sub_id2 = persist.upsert_sms_subscription(
            phone='+14165551234', email='test2@example.com', max_price=3000.0
        )
        assert sub_id2 == sub_id  # same row updated

    def test_get_sms_subscription(self):
        import persist
        persist.upsert_sms_subscription(
            phone='+14165559876', email='test@example.com', max_price=2200.0
        )
        sub = persist.get_sms_subscription('+14165559876')
        assert sub is not None
        assert sub['email'] == 'test@example.com'
        assert sub['max_price'] == 2200.0

    def test_get_sms_subscription_not_found(self):
        import persist
        assert persist.get_sms_subscription('+19999999999') is None

    def test_get_active_sms_subscriptions(self):
        import persist
        persist.upsert_sms_subscription(phone='+14165551000', email='a@example.com')
        persist.upsert_sms_subscription(phone='+14165551001', email='b@example.com')
        subs = persist.get_active_sms_subscriptions()
        assert len(subs) == 2

    def test_deactivate_sms_subscription(self):
        import persist
        persist.upsert_sms_subscription(phone='+14165552000', email='x@example.com')
        persist.deactivate_sms_subscription('+14165552000')
        assert persist.get_sms_subscription('+14165552000') is None


# ── check_and_send_sms_alerts ───────────────────────────────────────────────

class TestCheckAndSendSmsAlerts:
    @patch.dict(os.environ, {
        'TWILIO_ACCOUNT_SID': 'ACxxx',
        'TWILIO_AUTH_TOKEN': 'tok',
        'TWILIO_FROM_NUMBER': '+14165550000',
        'RENT_DATA_DIR': TEST_DATA_DIR
    })
    @patch('twilio.rest.Client')
    def test_sends_sms_for_matching_deal(self, mock_client_cls):
        import importlib, persist
        importlib.reload(persist)
        import sms_alerts as _sms
        importlib.reload(_sms)

        mock_msg = MagicMock()
        mock_msg.sid = 'SM999'
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_client_cls.return_value = mock_client

        persist.upsert_sms_subscription(
            phone='+14165559999', email='deal@example.com',
            max_price=2500.0, min_beds=1.0
        )

        test_db = os.path.join(TEST_DATA_DIR, 'listings.db')
        conn = sqlite3.connect(test_db)
        conn.execute("""
            INSERT INTO listings
                (listing_id, source, price, beds, neighborhood, url, score, pct_under, is_active)
            VALUES
                ('L1', 'kijiji', 2100, 1, 'King West', 'http://x.com/1', 0.22, 18.5, 1)
        """)
        conn.commit()
        conn.close()

        result = _sms.check_and_send_sms_alerts(min_score=0.15)
        assert result['sent'] == 1
        assert result['skipped'] == 0
        assert len(result['errors']) == 0

    @patch.dict(os.environ, {
        'TWILIO_ACCOUNT_SID': 'ACxxx',
        'TWILIO_AUTH_TOKEN': 'tok',
        'TWILIO_FROM_NUMBER': '+14165550000',
        'RENT_DATA_DIR': TEST_DATA_DIR
    })
    def test_skips_no_matching_deals(self):
        import importlib, persist
        importlib.reload(persist)
        import sms_alerts as _sms
        importlib.reload(_sms)

        persist.upsert_sms_subscription(
            phone='+14165559900', email='nope@example.com', max_price=999.0
        )
        result = _sms.check_and_send_sms_alerts(min_score=0.15)
        assert result['sent'] == 0
        assert result['skipped'] == 1

    @patch.dict(os.environ, {
        'TWILIO_ACCOUNT_SID': '',
        'TWILIO_AUTH_TOKEN': '',
        'TWILIO_FROM_NUMBER': ''
    })
    def test_no_credentials(self):
        import importlib, persist
        importlib.reload(persist)
        import sms_alerts as _sms
        importlib.reload(_sms)
        result = _sms.check_and_send_sms_alerts()
        assert result['sent'] == 0
        assert 'Twilio not configured' in result['errors']


# ── App API endpoints ───────────────────────────────────────────────────────

class TestSmsApiEndpoints:
    @pytest.fixture
    def client(self):
        os.environ['RENT_DATA_DIR'] = TEST_DATA_DIR
        import importlib, persist, app as _app
        persist._reset_conn()
        importlib.reload(persist)
        importlib.reload(_app)
        app = _app.app
        app.config['TESTING'] = True
        with app.test_client() as c:
            yield c

    def test_subscribe_invalid_phone(self, client):
        r = client.post('/api/sms/subscribe',
                        json={'phone': '123', 'email': 'a@b.com'})
        assert r.status_code == 400

    def test_subscribe_invalid_email(self, client):
        r = client.post('/api/sms/subscribe',
                        json={'phone': '+14165551234', 'email': 'notanemail'})
        assert r.status_code == 400

    def test_subscribe_success(self, client):
        with patch('sms_alerts.normalize_phone', return_value='+14165551234'):
            with patch('persist.upsert_sms_subscription', return_value=42):
                r = client.post('/api/sms/subscribe',
                                json={'phone': '4165551234', 'email': 'a@b.com',
                                      'max_price': 2500, 'min_beds': 1})
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data['success'] is True
        assert data['sub_id'] == 42
        assert data['phone'] == '+14165551234'

    def test_get_subscription_not_found(self, client):
        with patch('sms_alerts.normalize_phone', return_value='+19999999999'):
            r = client.get('/api/sms/subscription/+19999999999')
        assert r.status_code == 404

    def test_delete_subscription(self, client):
        with patch('sms_alerts.normalize_phone', return_value='+14165559999'):
            with patch('persist.deactivate_sms_subscription') as mock_deact:
                r = client.delete('/api/sms/subscription/+14165559999')
        assert r.status_code == 200
        mock_deact.assert_called_once_with('+14165559999')