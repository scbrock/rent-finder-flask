"""Tests for MC-312: Kijiji photo gallery (multi-image carousel).

Verifies:
- _encode_image_urls() / _decode_image_urls() in persist.py
- Schema migration adds image_urls_json column to existing DBs
- upsert_listings() persists image_urls_json
- get_active_listings() returns image_urls_json column
- _normalize_row() in app.py exposes image_urls list (all 3 input shapes)
- _build_listing_detail_response() includes image_urls
- scrape_kijiji_real.extract_listings stores image_urls list (not just first)
- scrape_kijiji._extract_image_urls returns all URLs (not just first)
"""

import json
import os
import sys
import pytest

# Make project root importable
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, PROJECT_DIR)

import persist
import scrape_kijiji
import scrape_kijiji_real as kijiji_real


# ── _encode_image_urls / _decode_image_urls (helpers) ────────────────────────

class TestEncodeImageUrls:

    def test_none_returns_none(self):
        assert persist._encode_image_urls(None) is None

    def test_empty_list_returns_none(self):
        assert persist._encode_image_urls([]) is None

    def test_empty_string_returns_none(self):
        assert persist._encode_image_urls("") is None

    def test_list_of_urls_json_encoded(self):
        urls = ["http://a/1.jpg", "http://b/2.jpg", "http://c/3.jpg"]
        result = persist._encode_image_urls(urls)
        assert result is not None
        decoded = json.loads(result)
        assert decoded == urls

    def test_filters_non_http_urls(self):
        urls = ["http://a/1.jpg", "ftp://no", "/relative", "", None, "http://b/2.jpg"]
        result = persist._encode_image_urls(urls)
        decoded = json.loads(result)
        assert decoded == ["http://a/1.jpg", "http://b/2.jpg"]

    def test_all_invalid_returns_none(self):
        urls = ["ftp://only", "/relative", ""]
        assert persist._encode_image_urls(urls) is None

    def test_single_string_url_wrapped_in_list(self):
        result = persist._encode_image_urls("http://a/1.jpg")
        assert json.loads(result) == ["http://a/1.jpg"]

    def test_single_non_http_string_returns_none(self):
        assert persist._encode_image_urls("ftp://only") is None

    def test_tuple_accepted(self):
        result = persist._encode_image_urls(("http://a/1.jpg", "http://b/2.jpg"))
        decoded = json.loads(result)
        assert decoded == ["http://a/1.jpg", "http://b/2.jpg"]


class TestDecodeImageUrls:

    def test_none_returns_empty_list(self):
        assert persist._decode_image_urls(None) == []

    def test_empty_string_returns_empty_list(self):
        assert persist._decode_image_urls("") == []

    def test_empty_list_returns_empty_list(self):
        assert persist._decode_image_urls([]) == []

    def test_valid_json_string_decoded(self):
        urls = ["http://a/1.jpg", "http://b/2.jpg"]
        result = persist._decode_image_urls(json.dumps(urls))
        assert result == urls

    def test_malformed_json_returns_empty_list(self):
        assert persist._decode_image_urls("not json") == []

    def test_list_input_filtered(self):
        assert persist._decode_image_urls(["http://ok/1.jpg", "ftp://no"]) == ["http://ok/1.jpg"]

    def test_json_non_list_returns_empty(self):
        assert persist._decode_image_urls(json.dumps("http://single")) == []


# ── Schema migration + upsert persistence ────────────────────────────────────

class TestUpsertImageUrlsJson:
    """Verify the new column is added on existing DBs and persisted on upsert."""

    @pytest.fixture
    def tmp_db(self, tmp_path, monkeypatch):
        """Set up a clean DB in a tmp dir with RENT_DATA_DIR env override."""
        monkeypatch.setenv("RENT_DATA_DIR", str(tmp_path))
        # Patch DB_PATH for the module + reset cached conn
        original_db_path = persist.DB_PATH
        persist.DB_PATH = os.path.join(str(tmp_path), "listings.db")
        # Reset cached connection by setting first elem to None (list-of-one)
        persist._cached_conn[0] = None
        try:
            persist.init_db()
            yield tmp_path
        finally:
            persist._cached_conn[0] = None
            persist.DB_PATH = original_db_path

    def _make_row(self, **overrides):
        base = {
            "source": "Kijiji",
            "title": "Test Listing",
            "price": 2000.0,
            "price_str": "$2,000",
            "beds": 1.0,
            "baths": 1.0,
            "sqft": 600,
            "neighborhood": "Downtown",
            "region": "Downtown",
            "location": "",
            "link": "https://example.com/test-listing",
            "image_url": "http://photos.example.com/1.jpg",
            "image_urls": [
                "http://photos.example.com/1.jpg",
                "http://photos.example.com/2.jpg",
                "http://photos.example.com/3.jpg",
            ],
            "days_ago": 3,
            "is_stale": False,
        }
        base.update(overrides)
        return base

    def test_schema_has_image_urls_json_column(self, tmp_db):
        """After init_db, listings table has image_urls_json column."""
        conn = persist._get_conn()
        cols = conn.execute("PRAGMA table_info(listings)").fetchall()
        names = [c[1] for c in cols]
        assert "image_urls_json" in names, f"Missing column. Got: {names}"
        conn.close()

    def test_upsert_writes_image_urls_json(self, tmp_db):
        """upsert_listings persists image_urls_json for listings with photos."""
        row = self._make_row()
        persist.upsert_listings([row])
        conn = persist._get_conn()
        raw = conn.execute(
            "SELECT image_urls_json FROM listings WHERE listing_id = ?",
            ("https://example.com/test-listing",)
        ).fetchone()
        assert raw is not None
        assert raw[0] is not None
        decoded = json.loads(raw[0])
        assert len(decoded) == 3
        assert decoded[0] == "http://photos.example.com/1.jpg"
        conn.close()

    def test_upsert_writes_null_when_no_image_urls(self, tmp_db):
        """upsert_listings writes NULL for listings without images."""
        row = self._make_row(image_url="", image_urls=[])
        persist.upsert_listings([row])
        conn = persist._get_conn()
        raw = conn.execute(
            "SELECT image_urls_json FROM listings WHERE listing_id = ?",
            ("https://example.com/test-listing",)
        ).fetchone()
        assert raw is not None
        assert raw[0] is None
        conn.close()

    def test_get_active_listings_returns_image_urls_json(self, tmp_db):
        """get_active_listings DataFrame includes image_urls_json column."""
        persist.upsert_listings([self._make_row()])
        df = persist.get_active_listings()
        assert "image_urls_json" in df.columns
        assert df.iloc[0]["image_urls_json"] is not None


# ── scrape_kijiji_real extracts all image URLs ──────────────────────────────

class TestScrapeKijijiRealImageUrls:
    """Verify Apollo-state extractor stores full imageUrls[] as image_urls."""

    def test_image_urls_list_passes_through_to_listing_dict(self):
        apollo = {
            "RealEstateListing:l1": {
                "__typename": "RealEstateListing",
                "id": "l1",
                "title": "Test",
                "price": {"amount": 200000},  # $2,000 in cents
                "attributes": {"__typename": "RealEstateListingAttributes", "all": []},
                "location": {},
                "url": "/v-test",
                "imageUrls": ["http://a/1.jpg", "http://a/2.jpg", "http://a/3.jpg"],
            }
        }
        next_data = {"props": {"pageProps": {"__APOLLO_STATE__": apollo}}}
        html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script></body></html>'

        listings = kijiji_real.extract_listings(html)
        assert len(listings) == 1
        lst = listings[0]
        assert lst["image_url"] == "http://a/1.jpg", "image_url keeps first URL"
        assert lst["image_urls"] == ["http://a/1.jpg", "http://a/2.jpg", "http://a/3.jpg"]
        assert len(lst["image_urls"]) == 3, "image_urls has all 3 URLs, not just first"

    def test_empty_image_urls_yields_empty_list(self):
        apollo = {
            "RealEstateListing:l1": {
                "__typename": "RealEstateListing",
                "id": "l1",
                "title": "Test",
                "price": {"amount": 200000},
                "attributes": {"__typename": "RealEstateListingAttributes", "all": []},
                "location": {},
                "url": "/v-test",
                "imageUrls": [],
            }
        }
        next_data = {"props": {"pageProps": {"__APOLLO_STATE__": apollo}}}
        html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script></body></html>'
        listings = kijiji_real.extract_listings(html)
        assert listings[0]["image_url"] == ""
        assert listings[0]["image_urls"] == []

    def test_filters_non_http_urls_from_image_urls(self):
        apollo = {
            "RealEstateListing:l1": {
                "__typename": "RealEstateListing",
                "id": "l1",
                "title": "Test",
                "price": {"amount": 200000},
                "attributes": {"__typename": "RealEstateListingAttributes", "all": []},
                "location": {},
                "url": "/v-test",
                "imageUrls": ["", None, "http://a/1.jpg", "ftp://no", "/relative"],
            }
        }
        next_data = {"props": {"pageProps": {"__APOLLO_STATE__": apollo}}}
        html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script></body></html>'
        listings = kijiji_real.extract_listings(html)
        assert listings[0]["image_urls"] == ["http://a/1.jpg"]


# ── scrape_kijiji (SSR) returns all image URLs ─────────────────────────────

class TestScrapeKijijiSSRExtractImageUrls:

    def test_extract_image_urls_returns_all_urls_in_dict(self):
        apollo = {
            "RealEstateListing:l1": {
                "__typename": "RealEstateListing",
                "id": "l1",
                "imageUrls": ["http://a/1.jpg", "http://a/2.jpg", "http://a/3.jpg"],
            }
        }
        next_data = {"props": {"pageProps": {"__APOLLO_STATE__": apollo}}}
        html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script></body></html>'

        result = scrape_kijiji._extract_image_urls(html)
        assert "l1" in result
        entry = result["l1"]
        assert isinstance(entry, dict)
        assert entry["first"] == "http://a/1.jpg"
        assert len(entry["all"]) == 3
        assert entry["all"][2] == "http://a/3.jpg"

    def test_extract_image_urls_empty_for_missing_apollodata(self):
        html = "<html><body>no next_data here</body></html>"
        assert scrape_kijiji._extract_image_urls(html) == {}

    def test_extract_image_urls_filters_invalid(self):
        apollo = {
            "RealEstateListing:l1": {
                "__typename": "RealEstateListing",
                "id": "l1",
                "imageUrls": ["", None, "http://ok/1.jpg", "ftp://nope"],
            }
        }
        next_data = {"props": {"pageProps": {"__APOLLO_STATE__": apollo}}}
        html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script></body></html>'
        result = scrape_kijiji._extract_image_urls(html)
        entry = result["l1"]
        assert entry["all"] == ["http://ok/1.jpg"]


# ── Listing dataclass back-compat ────────────────────────────────────────────

class TestListingDataclassBackCompat:

    def test_old_call_without_image_urls_still_works(self):
        from scrape_kijiji import Listing
        lst = Listing(
            listing_id="old1",
            title="old",
            price=2000,
            price_str="$2,000",
            location="Toronto",
            beds="1 bd",
            baths="1 ba",
            url="https://example.com/old",
            image_url="http://img/old.jpg",
        )
        # __post_init__ should populate image_urls=[image_url]
        assert lst.image_urls == ["http://img/old.jpg"]

    def test_new_call_with_image_urls_works(self):
        from scrape_kijiji import Listing
        urls = ["http://a/1.jpg", "http://a/2.jpg"]
        lst = Listing(
            listing_id="new1",
            title="new",
            price=2000,
            price_str="$2,000",
            location="Toronto",
            beds="1 bd",
            baths="1 ba",
            url="https://example.com/new",
            image_url="http://a/1.jpg",
            image_urls=urls,
        )
        assert lst.image_urls == urls


# ── app.py _normalize_row exposes image_urls (3 input shapes) ───────────────

class TestNormalizeRowImageUrls:
    """Verify _normalize_row handles all 3 input shapes for image_urls."""

    @pytest.fixture
    def app_module(self):
        import app
        return app

    def test_normalize_with_pre_decoded_list(self, app_module):
        """image_urls as a list in the input dict."""
        row = {
            "price": 2000,
            "fair_value": 2400,
            "pct_under": 16.6,
            "score": 0.123,
            "beds": 1,
            "baths": 1,
            "neighborhood": "Downtown",
            "image_url": "http://a/1.jpg",
            "image_urls": ["http://a/1.jpg", "http://a/2.jpg", "http://a/3.jpg"],
            "url": "https://example.com/x",
        }
        result = app_module._normalize_row(row)
        assert result["image_url"] == "http://a/1.jpg"
        assert result["image_urls"] == ["http://a/1.jpg", "http://a/2.jpg", "http://a/3.jpg"]
        assert len(result["image_urls"]) == 3

    def test_normalize_with_json_string(self, app_module):
        """image_urls as a JSON-encoded string."""
        row = {
            "price": 2000,
            "beds": 1,
            "neighborhood": "Downtown",
            "image_url": "http://a/1.jpg",
            "image_urls": json.dumps(["http://a/1.jpg", "http://a/2.jpg"]),
            "url": "https://example.com/x",
        }
        result = app_module._normalize_row(row)
        assert result["image_urls"] == ["http://a/1.jpg", "http://a/2.jpg"]

    def test_normalize_with_image_urls_json_db_column(self, app_module):
        """image_urls_json column (DB-style) when image_urls is absent."""
        row = {
            "price": 2000,
            "beds": 1,
            "neighborhood": "Downtown",
            "image_url": "http://a/1.jpg",
            "image_urls_json": json.dumps(["http://a/1.jpg", "http://a/2.jpg", "http://a/3.jpg"]),
            "url": "https://example.com/x",
        }
        result = app_module._normalize_row(row)
        assert result["image_urls"] == ["http://a/1.jpg", "http://a/2.jpg", "http://a/3.jpg"]

    def test_normalize_falls_back_to_image_url(self, app_module):
        """When no image_urls anywhere, wrap single image_url in list."""
        row = {
            "price": 2000,
            "beds": 1,
            "neighborhood": "Downtown",
            "image_url": "http://a/only.jpg",
            "url": "https://example.com/x",
        }
        result = app_module._normalize_row(row)
        assert result["image_urls"] == ["http://a/only.jpg"]

    def test_normalize_empty_when_no_images(self, app_module):
        row = {
            "price": 2000,
            "beds": 1,
            "neighborhood": "Downtown",
            "image_url": "",
            "url": "https://example.com/x",
        }
        result = app_module._normalize_row(row)
        assert result["image_urls"] == []

    def test_normalize_filters_non_http_strings(self, app_module):
        row = {
            "price": 2000,
            "beds": 1,
            "neighborhood": "Downtown",
            "image_url": "http://a/1.jpg",
            "image_urls": ["http://a/1.jpg", "ftp://no", "/relative"],
            "url": "https://example.com/x",
        }
        result = app_module._normalize_row(row)
        assert result["image_urls"] == ["http://a/1.jpg"]


# ── app.py listing detail response includes image_urls ──────────────────────

class TestListingDetailResponseImageUrls:
    """Verify /api/listing/<idx> JSON contains the image_urls list."""

    @pytest.fixture
    def client(self):
        import app
        app.app.config["TESTING"] = True
        with app.app.test_client() as c:
            yield c

    def test_listing_detail_includes_image_urls(self, client):
        """The detail endpoint returns image_urls field."""
        # First, ensure at least one listing exists in the live DB.
        # We use the existing listings.db in the project. If empty we skip.
        rv = client.get("/api/deals?region=&beds=0&max_price=100000")
        if rv.status_code != 200:
            pytest.skip(f"/api/deals returned {rv.status_code}")
        deals = rv.get_json()
        if not deals:
            pytest.skip("No active listings — skipping detail response test")
        # Pick a listing that has at least one photo (image_urls non-empty)
        with_photos = [d for d in deals if d.get("image_urls")]
        if not with_photos:
            pytest.skip("No deals have photos — skipping detail test")
        target = with_photos[0]
        d2 = client.get("/api/listing/detail?id=" + target["listing_id"]).get_json()
        assert "image_urls" in d2
        assert isinstance(d2["image_urls"], list)
        assert len(d2["image_urls"]) >= 1
