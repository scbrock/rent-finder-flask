"""Tests for MC-307: Kijiji listing photos in UI.

Verifies:
- _extract_image_urls() pulls imageUrls[0] from each RealEstateListing in __NEXT_DATA__
- _extract_image_urls() handles empty / missing data gracefully
- _extract_image_urls() filters out non-URL strings
- extract_listings() in scrape_kijiji_real.py sets image_url on each output dict
- scrape_kijiji_real output includes image_url field
- _normalize_row() in app.py exposes image_url
"""

import json
import pytest

from scrape_kijiji import _extract_image_urls, parse_html_cards
import scrape_kijiji_real as kijiji_real


# ── _extract_image_urls (scrape_kijiji.py secondary scraper) ─────────────────

def _build_html_with_listings(listings: list[dict]) -> str:
    """Build minimal Kijiji HTML with __NEXT_DATA__ containing given listings."""
    apollo = {}
    for lst in listings:
        apollo[f"RealEstateListing:{lst['id']}"] = {
            "__typename": "RealEstateListing",
            "id": lst["id"],
            "activationDate": lst.get("activationDate", "2026-07-01T00:00:00.000Z"),
            "imageUrls": lst.get("imageUrls", []),
        }
    next_data = {
        "props": {"pageProps": {"__APOLLO_STATE__": apollo}},
        "page": "/srp", "query": {}, "buildId": "x", "assetPrefix": "x",
    }
    body = json.dumps(next_data)
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{body}</script></body></html>'


class TestExtractImageUrls:
    def test_extracts_first_valid_url_per_listing(self):
        html = _build_html_with_listings([
            {"id": "111", "imageUrls": [
                "https://media.kijiji.ca/api/v1/img1?rule=kijijica-200-jpg",
                "https://media.kijiji.ca/api/v1/img2?rule=kijijica-200-jpg",
            ]},
            {"id": "222", "imageUrls": ["https://media.kijiji.ca/abc"]},
        ])
        result = _extract_image_urls(html)
        assert result["111"] == "https://media.kijiji.ca/api/v1/img1?rule=kijijica-200-jpg"
        assert result["222"] == "https://media.kijiji.ca/abc"
        assert len(result) == 2

    def test_handles_empty_image_urls(self):
        html = _build_html_with_listings([
            {"id": "333", "imageUrls": []},
            {"id": "444", "imageUrls": ["", "  ", None]},
        ])
        result = _extract_image_urls(html)
        assert "333" not in result  # empty list = no entry
        assert "444" not in result  # all invalid values = no entry

    def test_filters_non_http_strings(self):
        html = _build_html_with_listings([
            {"id": "555", "imageUrls": [
                "not-a-url",
                "/relative/path",
                "ftp://media.kijiji.ca/img.jpg",
                "https://valid.kijiji.ca/photo.jpg",
            ]},
        ])
        result = _extract_image_urls(html)
        assert result["555"] == "https://valid.kijiji.ca/photo.jpg"

    def test_returns_empty_dict_for_no_next_data(self):
        assert _extract_image_urls("<html><body></body></html>") == {}

    def test_returns_empty_dict_for_malformed_json(self):
        html = '<html><body><script id="__NEXT_DATA__">{bad json</script></body></html>'
        assert _extract_image_urls(html) == {}

    def test_ignores_non_realestate_entries(self):
        apollo = {
            "RealEstateListing:111": {
                "__typename": "RealEstateListing", "id": "111",
                "imageUrls": ["https://kijiji.ca/photo.jpg"],
            },
            "SomethingElse:222": {
                "__typename": "SomeOtherType", "id": "222",
                "imageUrls": ["https://example.com/other.jpg"],
            },
        }
        body = json.dumps({"props": {"pageProps": {"__APOLLO_STATE__": apollo}}})
        html = f'<html><script id="__NEXT_DATA__">{body}</script></html>'
        result = _extract_image_urls(html)
        assert "111" in result
        assert "222" not in result


# ── parse_html_cards: image_url flows from JSON if HTML src empty ─────────────

HTML_NO_IMG_TAG = """
<section data-testid="listing-card" data-listingid="A1">
  <h3 data-testid="listing-title">
    <a href="/v-apartments-condos/toronto/spacious-1br/A1">Spacious 1BR Apartment for Rent</a>
  </h3>
  <p data-testid="listing-price">$1,800 /month</p>
  <p data-testid="listing-location">Downtown Toronto</p>
</section>
"""


class TestParseHtmlCardsImages:
    def test_uses_image_from_json_when_html_src_empty(self):
        # HTML has no <img> tag (lazy-load), JSON has image
        img_urls = {"A1": "https://media.kijiji.ca/api/v1/photo-a1?rule=kijijica-200-jpg"}
        listings = parse_html_cards(HTML_NO_IMG_TAG, {}, img_urls)
        assert len(listings) == 1
        assert listings[0].image_url == "https://media.kijiji.ca/api/v1/photo-a1?rule=kijijica-200-jpg"

    def test_html_img_takes_precedence_when_present(self):
        # Both HTML src and JSON present — JSON wins (it has the real photo URL)
        html = """<section data-testid="listing-card" data-listingid="A2">
            <h3 data-testid="listing-title"><a href="/v-apartments-condos/toronto/condo/A2">Condo for rent</a></h3>
            <p data-testid="listing-price">$2,500 /month</p>
            <p data-testid="listing-location">Toronto</p>
            <img data-testid="listing-card-image" src="https://lazy.kijiji.ca/placeholder.jpg" />
        </section>"""
        img_urls = {"A2": "https://media.kijiji.ca/api/v1/photo-a2?rule=kijijica-200-jpg"}
        listings = parse_html_cards(html, {}, img_urls)
        assert listings[0].image_url == "https://media.kijiji.ca/api/v1/photo-a2?rule=kijijica-200-jpg"

    def test_empty_image_when_neither_provided(self):
        listings = parse_html_cards(HTML_NO_IMG_TAG, {}, {})
        assert listings[0].image_url == ""

    def test_backward_compatible_no_image_urls_arg(self):
        # Old call signature (no image_urls kwarg) still works
        listings = parse_html_cards(HTML_NO_IMG_TAG, {})
        assert listings[0].image_url == ""


# ── scrape_kijiji_real: image_url set on output dict ─────────────────────────

# Build a minimal valid Apollo state RealEstateListing for extract_listings()
def _apollo_listing(id_: str, image_urls: list, price_cents: int = 250000,
                    activation: str = "2026-07-01T00:00:00.000Z") -> dict:
    """Build a minimal RealEstateListing entry that extract_listings() will accept."""
    return {
        "__typename": "RealEstateListing",
        "id": id_,
        "title": "Test Apartment for Rent",
        "url": f"/v-apartments-condos/toronto/test/{id_}",
        "description": "test description",
        "activationDate": activation,
        "price": {"__typename": "StandardAmountPrice", "type": "FIXED", "amount": price_cents},
        "imageUrls": image_urls,
        "attributes": {"__typename": "RealEstateListingAttributes", "all": [
            {"canonicalName": "numberbedrooms", "canonicalValues": ["1"]},
            {"canonicalName": "numberbathrooms", "canonicalValues": ["1"]},
            {"canonicalName": "unittype", "canonicalValues": ["apartment"]},
        ]},
        "location": {"__typename": "RealEstateListingLocation", "address": "Toronto, ON"},
    }


def _apollo_html(listings: list) -> str:
    apollo = {f"RealEstateListing:{lst['id']}": lst for lst in listings}
    body = json.dumps({"props": {"pageProps": {"__APOLLO_STATE__": apollo}}})
    return f'<html><script id="__NEXT_DATA__">{body}</script></html>'


class TestExtractListingsImages:
    def test_image_url_set_on_extracted_listing(self):
        url = "https://media.kijiji.ca/api/v1/img-100?rule=kijijica-200-jpg"
        listings = [_apollo_listing("100", [url, "https://media.kijiji.ca/api/v1/img-100b"])]
        html = _apollo_html(listings)
        result = kijiji_real.extract_listings(html)
        assert len(result) == 1
        assert result[0]["image_url"] == url  # first valid URL

    def test_image_url_empty_when_no_images(self):
        listings = [_apollo_listing("200", [])]
        html = _apollo_html(listings)
        result = kijiji_real.extract_listings(html)
        assert result[0]["image_url"] == ""

    def test_image_url_skips_empty_strings(self):
        listings = [_apollo_listing("300", ["", "  ", "https://media.kijiji.ca/abc"])]
        html = _apollo_html(listings)
        result = kijiji_real.extract_listings(html)
        assert result[0]["image_url"] == "https://media.kijiji.ca/abc"

    def test_output_dict_includes_image_url_field(self):
        # Even when no images, the field is present (for DataFrame consistency)
        listings = [_apollo_listing("400", [])]
        html = _apollo_html(listings)
        result = kijiji_real.extract_listings(html)
        assert "image_url" in result[0]


# ── _normalize_row in app.py exposes image_url ───────────────────────────────

class TestNormalizeRowImageUrl:
    @pytest.fixture
    def app_module(self):
        import importlib
        return importlib.import_module("app")

    def test_normalize_row_includes_image_url(self, app_module):
        row = {
            "listing_id": "X1",
            "url": "https://kijiji.ca/v/test/X1",
            "neighborhood": "Toronto",
            "price": 2000,
            "image_url": "https://media.kijiji.ca/api/v1/img-x1?rule=kijijica-200-jpg",
        }
        result = app_module._normalize_row(row)
        assert result.get("image_url") == "https://media.kijiji.ca/api/v1/img-x1?rule=kijijica-200-jpg"

    def test_normalize_row_image_url_empty_when_missing(self, app_module):
        row = {
            "listing_id": "X2",
            "url": "https://kijiji.ca/v/test/X2",
            "neighborhood": "Toronto",
            "price": 2000,
        }
        result = app_module._normalize_row(row)
        # Empty string is acceptable (placeholder shows house emoji)
        assert result.get("image_url", "") == ""

    def test_normalize_row_image_url_empty_when_none(self, app_module):
        row = {
            "listing_id": "X3",
            "url": "https://kijiji.ca/v/test/X3",
            "neighborhood": "Toronto",
            "price": 2000,
            "image_url": None,
        }
        result = app_module._normalize_row(row)
        assert result.get("image_url", "") == ""