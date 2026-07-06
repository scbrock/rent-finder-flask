"""Tests for MC-308: Craigslist on-demand listing photo fetch.

Verifies:
- craigslist_photo_fetcher._extract_og_image:
    - parses og:image meta
    - falls back to img#thumbs
    - falls back to first <img> with http URL
    - filters out javascript: / data: schemes
    - filters out icon/logo srcs
    - returns None when no usable image
- craigslist_photo_fetcher.fetch_listing_photo:
    - returns None on 4xx, timeout, parse fail
    - returns image_url on 200 with valid HTML
- persist (craigslist_photo_cache):
    - upsert positive + read back within TTL
    - stale positive returns None
    - negative cache hit within 1h TTL
    - negative cache expiry after 1h
    - get_recent_cl_photo_fetches window counts
    - empty url is no-op
- app /api/craigslist/photo endpoint:
    - 400 on missing url
    - 400 on non-craigslist url
    - 200 cache hit (positive)
    - 200 cache hit (negative -> is_negative=true)
    - 200 fresh fetch + cache write
    - 502 + negative cache when upstream has no image
    - 429 when budget exhausted
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import craigslist_photo_fetcher as cl_fetcher
import persist as db
from app import app
from persist import (
    POSITIVE_TTL_SECS,
    NEGATIVE_TTL_SECS,
)


# HTML fixtures -----------------------------------------------------------

HTML_OG_IMAGE = '<html><head><meta property="og:image" content="https://images.craigslist.org/abc123_0ci0.jpg" /></head><body><h1>Listing</h1></body></html>'
HTML_THUMBS_FALLBACK = '<html><head><title>Listing</title></head><body><div id="thumbs"><img src="https://images.craigslist.org/xyz789_0ci0.jpg" alt="1" /></div></body></html>'
HTML_NO_IMAGES = '<html><body><h1>1BR Apartment</h1><p>No photos</p></body></html>'
HTML_OG_JAVASCRIPT = '<html><head><meta property="og:image" content="javascript:alert(1)" /></head><body><img src="https://images.craigslist.org/real_img.jpg" /></body></html>'
HTML_OG_EMPTY = '<html><head><meta property="og:image" content="" /></head><body><img src="https://images.craigslist.org/ok.jpg" /></body></html>'
HTML_LOGO_FIRST = '<html><body><img src="https://www.craigslist.org/assets/logo.png" /><img src="https://www.craigslist.org/assets/icon.png" /><img src="https://images.craigslist.org/listing.jpg" /></body></html>'


class TestExtractOgImage:
    def test_parses_og_image(self):
        assert cl_fetcher._extract_og_image(HTML_OG_IMAGE) == "https://images.craigslist.org/abc123_0ci0.jpg"

    def test_falls_back_to_thumbs_when_no_og(self):
        assert cl_fetcher._extract_og_image(HTML_THUMBS_FALLBACK) == "https://images.craigslist.org/xyz789_0ci0.jpg"

    def test_returns_none_when_no_images(self):
        assert cl_fetcher._extract_og_image(HTML_NO_IMAGES) is None

    def test_filters_javascript_scheme_in_og(self):
        assert cl_fetcher._extract_og_image(HTML_OG_JAVASCRIPT) == "https://images.craigslist.org/real_img.jpg"

    def test_skips_empty_og_image(self):
        assert cl_fetcher._extract_og_image(HTML_OG_EMPTY) == "https://images.craigslist.org/ok.jpg"

    def test_filters_icon_logo_src(self):
        assert cl_fetcher._extract_og_image(HTML_LOGO_FIRST) == "https://images.craigslist.org/listing.jpg"

    def test_handles_malformed_html(self):
        assert cl_fetcher._extract_og_image("<html><body><p>nope</p>") is None
        assert cl_fetcher._extract_og_image("") is None


class _StubResponse:
    def __init__(self, status_code=200, text="", ctype="text/html"):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": ctype}


class _StubSession:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def get(self, url, timeout=None, allow_redirects=None):
        self.calls.append({"url": url, "timeout": timeout})
        if self.responses:
            return self.responses.pop(0)
        return _StubResponse(200, text="<html><body>x</body></html>")


class TestFetchListingPhoto:
    def test_returns_image_url_on_200_with_og(self):
        stub = _StubSession([_StubResponse(200, text=HTML_OG_IMAGE)])
        url = cl_fetcher.fetch_listing_photo("https://toronto.craigslist.org/tor/apa/d/test/12345.html", session=stub)
        assert url == "https://images.craigslist.org/abc123_0ci0.jpg"
        assert len(stub.calls) == 1

    def test_returns_none_on_404(self):
        stub = _StubSession([_StubResponse(404)])
        assert cl_fetcher.fetch_listing_photo("https://toronto.craigslist.org/missing.html", session=stub) is None

    def test_returns_none_on_non_html_content_type(self):
        stub = _StubSession([_StubResponse(200, text="binary", ctype="image/jpeg")])
        assert cl_fetcher.fetch_listing_photo("https://toronto.craigslist.org/img-only", session=stub) is None

    def test_returns_none_when_no_image_in_html(self):
        stub = _StubSession([_StubResponse(200, text=HTML_NO_IMAGES)])
        assert cl_fetcher.fetch_listing_photo("https://toronto.craigslist.org/nope/12345.html", session=stub) is None

    def test_request_error_returns_none(self):
        class _FailSession:
            def get(self, url, **kw):
                import requests
                raise requests.ConnectionError("boom")
        assert cl_fetcher.fetch_listing_photo("https://toronto.craigslist.org/x/12345.html", session=_FailSession()) is None


# persist cache tests -----------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_cl_cache():
    db._reset_conn()
    db.reset_craigslist_photo_cache()
    yield
    db.reset_craigslist_photo_cache()


class TestCraigslistPhotoCache:
    def test_upsert_positive_and_read_back(self):
        db.upsert_craigslist_photo_cache("https://toronto.craigslist.org/a/1.html", "https://img.craigslist.org/1.jpg", now_ts=1000)
        row = db.get_craigslist_photo_cache("https://toronto.craigslist.org/a/1.html", now_ts=1000 + 60)
        assert row is not None
        assert row["image_url"] == "https://img.craigslist.org/1.jpg"
        assert row["is_negative"] == 0

    def test_positive_cache_expires_after_14_days(self):
        db.upsert_craigslist_photo_cache("https://toronto.craigslist.org/b/2.html", "https://img.craigslist.org/2.jpg", now_ts=1000)
        row = db.get_craigslist_photo_cache("https://toronto.craigslist.org/b/2.html", now_ts=1000 + POSITIVE_TTL_SECS - 10)
        assert row is not None
        row = db.get_craigslist_photo_cache("https://toronto.craigslist.org/b/2.html", now_ts=1000 + POSITIVE_TTL_SECS + 10)
        assert row is None

    def test_negative_cache_hit(self):
        db.upsert_craigslist_photo_cache("https://toronto.craigslist.org/c/3.html", None, is_negative=True, now_ts=5000)
        row = db.get_craigslist_photo_cache("https://toronto.craigslist.org/c/3.html", now_ts=5000 + 60)
        assert row is not None
        assert row["image_url"] is None
        assert row["is_negative"] == 1

    def test_negative_cache_expires_after_1_hour(self):
        db.upsert_craigslist_photo_cache("https://toronto.craigslist.org/d/4.html", None, is_negative=True, now_ts=10000)
        row = db.get_craigslist_photo_cache("https://toronto.craigslist.org/d/4.html", now_ts=10000 + NEGATIVE_TTL_SECS - 10)
        assert row is not None
        row = db.get_craigslist_photo_cache("https://toronto.craigslist.org/d/4.html", now_ts=10000 + NEGATIVE_TTL_SECS + 10)
        assert row is None

    def test_recent_fetches_window_count(self):
        db.upsert_craigslist_photo_cache("https://cl/x/1.html", "https://img/1.jpg", now_ts=1000)
        db.upsert_craigslist_photo_cache("https://cl/x/2.html", "https://img/2.jpg", now_ts=2000)
        db.upsert_craigslist_photo_cache("https://cl/x/3.html", None, is_negative=True, now_ts=3000)
        assert db.get_recent_cl_photo_fetches(10000, now_ts=3500) == 3
        assert db.get_recent_cl_photo_fetches(1500, now_ts=3500) == 2
        assert db.get_recent_cl_photo_fetches(0, now_ts=3500) == 0

    def test_empty_url_is_noop(self):
        assert db.get_craigslist_photo_cache("") is None
        assert db.upsert_craigslist_photo_cache("", "x") is None
        assert db.upsert_craigslist_photo_cache(None, "x") is None

    def test_upsert_overwrites_existing(self):
        db.upsert_craigslist_photo_cache("https://cl/y/1.html", "https://old.jpg", now_ts=1000)
        db.upsert_craigslist_photo_cache("https://cl/y/1.html", "https://new.jpg", now_ts=2000)
        row = db.get_craigslist_photo_cache("https://cl/y/1.html", now_ts=2000)
        assert row["image_url"] == "https://new.jpg"
        assert row["fetched_at"] == 2000


# /api/craigslist/photo endpoint tests ------------------------------------

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def stub_cl_fetcher(monkeypatch):
    """Patch craigslist_photo_fetcher (the module the endpoint imports as _cl_fetcher)."""
    # Use the literal name the endpoint does: `import craigslist_photo_fetcher as _cl_fetcher`
    import craigslist_photo_fetcher as fetcher_mod

    class _Configurable:
        def __init__(self):
            self.calls = []
            self.return_value = "https://img.craigslist.org/test.jpg"

        def fetch_listing_photo(self, url, **kw):
            self.calls.append(url)
            return self.return_value

    stub = _Configurable()
    monkeypatch.setattr(fetcher_mod, "fetch_listing_photo", stub.fetch_listing_photo)
    return stub


class TestApiCraigslistPhotoEndpoint:
    def test_missing_url_returns_400(self, client):
        r = client.get("/api/craigslist/photo")
        assert r.status_code == 400
        body = r.get_json()
        assert "url" in body["error"].lower()

    def test_non_craigslist_url_returns_400(self, client):
        r = client.get("/api/craigslist/photo?url=https://example.com/x")
        assert r.status_code == 400

    def test_http_only_url_rejected(self, client):
        r = client.get("/api/craigslist/photo?url=http://toronto.craigslist.org/x")
        assert r.status_code == 400

    def test_cache_hit_returns_cached_image(self, client):
        url = "https://toronto.craigslist.org/apa/d/cached/12345.html"
        db.upsert_craigslist_photo_cache(url, "https://img.craigslist.org/cached.jpg")
        r = client.get(f"/api/craigslist/photo?url={url}")
        assert r.status_code == 200
        body = r.get_json()
        assert body["cached"] is True
        assert body["image_url"] == "https://img.craigslist.org/cached.jpg"
        assert body["is_negative"] is False

    def test_cache_hit_negative_returns_image_null(self, client):
        url = "https://toronto.craigslist.org/apa/d/nope/67890.html"
        db.upsert_craigslist_photo_cache(url, None, is_negative=True)
        r = client.get(f"/api/craigslist/photo?url={url}")
        assert r.status_code == 200
        body = r.get_json()
        assert body["cached"] is True
        assert body["image_url"] is None
        assert body["is_negative"] is True

    def test_fresh_fetch_returns_200_and_caches(self, client, stub_cl_fetcher):
        url = "https://toronto.craigslist.org/apa/d/fresh/11111.html"
        r = client.get(f"/api/craigslist/photo?url={url}")
        assert r.status_code == 200
        body = r.get_json()
        assert body["cached"] is False
        assert body["image_url"] == "https://img.craigslist.org/test.jpg"
        assert len(stub_cl_fetcher.calls) == 1
        row = db.get_craigslist_photo_cache(url)
        assert row is not None
        assert row["image_url"] == "https://img.craigslist.org/test.jpg"

    def test_no_image_returns_502_and_caches_negative(self, client, stub_cl_fetcher):
        stub_cl_fetcher.return_value = None
        url = "https://toronto.craigslist.org/apa/d/noimg/22222.html"
        r = client.get(f"/api/craigslist/photo?url={url}")
        assert r.status_code == 502
        row = db.get_craigslist_photo_cache(url)
        assert row is not None
        assert row["image_url"] is None
        assert row["is_negative"] == 1

    def test_budget_exhausted_returns_429(self, client, stub_cl_fetcher, monkeypatch):
        # Patch the rate-limit check to always report exhausted budget.
        import app as app_module
        for k in list(app_module.__dict__.keys()):
            if "get_recent_cl_photo_fetches" in k:
                monkeypatch.setattr(app_module, k, lambda window_secs: 999)
        url = "https://toronto.craigslist.org/apa/d/budget/33333.html"
        r = client.get(f"/api/craigslist/photo?url={url}")
        assert r.status_code == 429
        body = r.get_json()
        assert body["error"] == "budget_exhausted"
        assert stub_cl_fetcher.calls == []
