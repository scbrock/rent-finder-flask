"""Tests for scrape_kijiji.py — MC-246."""

import pytest
from scrape_kijiji import (
    _is_rental_url,
    _is_rental_title,
    parse_html_cards,
    Listing,
)


# ── _is_rental_url ─────────────────────────────────────────────────────────────

class TestIsRentalUrl:
    EXAMPLES = [
        # (url, expected)
        ("https://www.kijiji.ca/v-apartments-condos/toronto/1br/123", True),
        ("https://www.kijiji.ca/v-short-term-rental/toronto/room/456", True),
        ("https://www.kijiji.ca/v-rooms-rentals/toronto/789", True),
        ("https://www.kijiji.ca/v-apartments-condos/mississauga/condo/111", True),
        ("https://www.kijiji.ca/v-cars-trucks/toronto/suv/222", False),
        ("https://www.kijiji.ca/v-electronics/toronto/laptop/333", False),
        ("https://www.kijiji.ca/v-furniture/toronto/sofa/444", False),
        ("https://www.kijiji.ca/v-buy-sell-other/toronto/stuff/555", False),
        ("https://www.kijiji.ca/v-real-estate/toronto/house/666", False),
        ("https://www.kijiji.ca/v-heavy-equipment/toronto/excavator/777", False),
        ("https://www.kijiji.ca/v-classes-lessons/toronto/piano/888", False),
        ("https://www.kijiji.ca/v-jewelry/toronto/ring/999", False),
        ("https://www.kijiji.ca/v-free-stuff/toronto/chair/000", False),
        ("", False),
        (None, False),
    ]

    @pytest.mark.parametrize("url,expected", EXAMPLES)
    def test_is_rental_url(self, url, expected):
        assert _is_rental_url(url) == expected


# ── _is_rental_title ──────────────────────────────────────────────────────────

class TestIsRentalTitle:
    RENTAL = [
        "1 Bedroom Apartment for Rent in Toronto",
        "2 BEDROOM CONDO FOR LEASE - North York",
        "Bachelor Suite near Downtown Toronto",
        "Renovated Den in Mississauga",
        "Bright 1 Bed + 1 Bath in Etobicoke",
        "Bachelor unit Scarborough",
        "Studio for rent - GTA",
        "2 bedrooms, 1 bath - Midtown",
        "Apartment for rent - Downtown",
        "Brampton 3 bed basement suite",
        "For rent: 1 bedroom apartment",
        "Semi-renovated two bedroom, St Clair West",
    ]

    NON_RENTAL = [
        "2016 Harley-Davidson FLTRUSE - CVO Road Glide",
        "Toyota Camry for sale",
        "Tree removal arborist stump grinding",
        "Amazon FBA Wholesale lot",
        "iPhone 15 Pro Max for sale",
        "Excavator for lease",
        "Truck rental - moving services",
        "Car rental - daily rates",
        "Equipment financing available",
        "Piano lessons for beginners",
        "Boat rental - daily",
        "Driving lesson - $40/hr",
        "Call us for lease-to-own options",
        "",
        None,
    ]

    def test_rental_titles_pass(self):
        for title in self.RENTAL:
            assert _is_rental_title(title), f"Expected rental: {title!r}"

    def test_non_rental_titles_fail(self):
        for title in self.NON_RENTAL:
            assert not _is_rental_title(title), f"Expected non-rental: {title!r}"


# ── parse_html_cards ──────────────────────────────────────────────────────────

HTML_RENTAL_CARD = """
<section data-testid="listing-card" data-listingid="1234567">
  <h3 data-testid="listing-title">
    <a href="/v-apartments-condos/city-of-toronto/2-bedroom-apartment-for-rent/1234567">
      2 Bedroom Apartment for Rent in Toronto
    </a>
  </h3>
  <p data-testid="listing-price">$2,500 /month</p>
  <p data-testid="listing-location">Liberty Village, Toronto</p>
  <img data-testid="listing-card-image" src="https://kijiji.img.com/photo.jpg" />
</section>
"""

HTML_BED_BATHS = """
<section data-testid="listing-card" data-listingid="9999999">
  <h3 data-testid="listing-title">
    <a href="/v-apartments-condos/toronto/bright-2br-2ba/9999999">
      Bright 2 Bedroom 2 Bath in Etobicoke
    </a>
  </h3>
  <p data-testid="listing-price">$2,800 /month</p>
  <p data-testid="listing-location">Etobicoke, Toronto</p>
  <img data-testid="listing-card-image" src="https://kijiji.img.com/photo2.jpg" />
</section>
"""

HTML_NON_RENTAL = """
<section data-testid="listing-card" data-listingid="1111111">
  <h3 data-testid="listing-title">
    <a href="/v-cars-trucks/toronto/toyota-camry/1111111">
      2020 Toyota Camry for sale
    </a>
  </h3>
  <p data-testid="listing-price">$22,000</p>
  <p data-testid="listing-location">Toronto</p>
  <img data-testid="listing-card-image" src="" />
</section>
"""

HTML_WRONG_PRICE = """
<section data-testid="listing-card" data-listingid="2222222">
  <h3 data-testid="listing-title">
    <a href="/v-apartments-condos/toronto/fake-listing/2222222">
      Cheap apartment - too low price
    </a>
  </h3>
  <p data-testid="listing-price">$50 /month</p>
  <p data-testid="listing-location">Toronto</p>
  <img data-testid="listing-card-image" src="" />
</section>
"""

HTML_TOO_EXPENSIVE = """
<section data-testid="listing-card" data-listingid="3333333">
  <h3 data-testid="listing-title">
    <a href="/v-apartments-condos/toronto/luxury-penthouse/3333333">
      Luxury Penthouse - Downtown Toronto
    </a>
  </h3>
  <p data-testid="listing-price">$50,000 /month</p>
  <p data-testid="listing-location">Downtown Toronto</p>
  <img data-testid="listing-card-image" src="https://kijiji.img.com/penthouse.jpg" />
</section>
"""


class TestParseHtmlCards:
    def test_parses_valid_rental_card(self):
        listings = parse_html_cards(HTML_RENTAL_CARD)
        assert len(listings) == 1
        lst = listings[0]
        assert lst.listing_id == "1234567"
        assert lst.title == "2 Bedroom Apartment for Rent in Toronto"
        assert lst.price == 2500.0
        assert lst.price_str == "$2,500 /month"
        assert lst.location == "Liberty Village, Toronto"
        assert lst.url == "https://www.kijiji.ca/v-apartments-condos/city-of-toronto/2-bedroom-apartment-for-rent/1234567"
        assert lst.image_url == "https://kijiji.img.com/photo.jpg"
        assert lst.source == "kijiji"

    def test_extracts_beds_and_baths(self):
        listings = parse_html_cards(HTML_BED_BATHS)
        assert len(listings) == 1
        lst = listings[0]
        assert "2" in lst.beds or "bed" in lst.beds.lower()

    def test_filters_non_rental_by_url(self):
        listings = parse_html_cards(HTML_NON_RENTAL)
        assert len(listings) == 0

    def test_filters_way_too_cheap(self):
        listings = parse_html_cards(HTML_WRONG_PRICE)
        assert len(listings) == 0

    def test_filters_way_too_expensive(self):
        listings = parse_html_cards(HTML_TOO_EXPENSIVE)
        assert len(listings) == 0

    def test_multiple_cards_returns_only_rentals(self):
        html = HTML_RENTAL_CARD + HTML_NON_RENTAL + HTML_WRONG_PRICE + HTML_BED_BATHS
        listings = parse_html_cards(html)
        assert len(listings) == 2  # only the two valid rental cards

    def test_empty_html_returns_empty(self):
        assert parse_html_cards("") == []
        assert parse_html_cards("<html></html>") == []

    def test_listing_dataclass_fields(self):
        listings = parse_html_cards(HTML_RENTAL_CARD)
        lst = listings[0]
        assert isinstance(lst, Listing)
        assert hasattr(lst, "listing_id")
        assert hasattr(lst, "title")
        assert hasattr(lst, "price")
        assert hasattr(lst, "price_str")
        assert hasattr(lst, "location")
        assert hasattr(lst, "beds")
        assert hasattr(lst, "baths")
        assert hasattr(lst, "url")
        assert hasattr(lst, "image_url")
        assert hasattr(lst, "source")
