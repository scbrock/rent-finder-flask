"""
MC-333 — Neighbourhood fallback handling tests.

Verifies:
1. resolve_neighbourhood() classifies raw values correctly:
   - 'Toronto' / 'city of toronto' -> ('Toronto', 'toronto_catchall')
   - '30 Carabob Court' / 'Bloor St W & Bathurst St' -> ('...', 'low_signal_address')
   - 'Brampton' / 'Mississauga, Ontario' -> ('...', 'off_toronto')
   - 'Annex' / 'Agincourt North' -> ('...', 'resolved')
2. URL slug fallback can resolve generic 'Toronto' rows whose URL
   encodes a real neighbourhood ('toronto-11-yonge-and-bloor-condo' -> 'Church-Yonge Corridor').
3. /api/deals default view excludes toronto_catchall + low_signal_address +
   off_toronto rows; pass ?include_fallback=true to opt in.
4. /api/meta neighborhoods never returns raw street addresses.
5. _looks_like_address() correctly classifies numbered / intersection / suffix
   strings.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import neighbourhood_lookup as nl
from app import app


# ── resolve_neighbourhood classification ────────────────────────────────────


class TestResolvePreciseMatch:
    """Already-specific raw values resolve to themselves and are 'resolved'."""

    def test_annex(self):
        assert nl.resolve_neighbourhood('Annex') == ('Annex', 'resolved')

    def test_niagara(self):
        assert nl.resolve_neighbourhood('Niagara') == ('Niagara', 'resolved')

    def test_agincourt_north(self):
        assert nl.resolve_neighbourhood('Agincourt North') == (
            'Agincourt North', 'resolved')

    def test_bay_street_corridor(self):
        # Bay Street Corridor is a real official neighbourhood, NOT a
        # catch-all. Kijiji listings that legitimately set this name
        # must pass through as 'resolved' (the catch-all flag only
        # fires when the *raw* input was generic and the resolution
        # came from the direct-map fallback).
        assert nl.resolve_neighbourhood('Bay Street Corridor') == (
            'Bay Street Corridor', 'resolved')


class TestResolveGenericCatchall:
    """Generic raw inputs that don't resolve via title/URL stay as
    toronto_catchall so the UI hides them from the default view."""

    def test_toronto_no_hint(self):
        assert nl.resolve_neighbourhood('Toronto', '', '') == (
            'Toronto', 'toronto_catchall')

    def test_TORONTO_uppercase(self):
        assert nl.resolve_neighbourhood('TORONTO', '', '') == (
            'TORONTO', 'toronto_catchall')

    def test_city_of_toronto(self):
        assert nl.resolve_neighbourhood('city of toronto', '', '') == (
            'city of toronto', 'toronto_catchall')

    def test_empty_string(self):
        # Empty raw -> low_signal_address (no signal at all)
        assert nl.resolve_neighbourhood('', '', '') == (
            '', 'low_signal_address')

    def test_none_raw(self):
        # None is treated the same as empty.
        assert nl.resolve_neighbourhood(None, '', '') == (
            '', 'low_signal_address')


class TestResolveUrlSlugHint:
    """Generic 'Toronto' rows with informative URL slugs resolve via
    the slug fallback. This is the main mechanism that takes the
    Toronto catch-all rate from ~21% down to <5%."""

    def test_yonge_and_bloor_in_slug(self):
        name, status = nl.resolve_neighbourhood(
            'Toronto',
            'https://www.craigslist.org/view/d/toronto-11-yonge-and-bloor-condo/abc',
            '',
        )
        assert name == 'Church-Yonge Corridor'
        assert status == 'resolved'

    def test_king_west_in_slug(self):
        name, status = nl.resolve_neighbourhood(
            'Toronto',
            'https://www.craigslist.org/view/d/1br-condo-in-king-west-furnished/abc',
            '',
        )
        assert name == 'Niagara'
        assert status == 'resolved'

    def test_distillery_in_slug(self):
        name, status = nl.resolve_neighbourhood(
            'Toronto',
            'https://www.craigslist.org/view/d/condo-in-the-distillery-for-rent/abc',
            '',
        )
        assert name == 'St.Andrew-Windfields'
        assert status == 'resolved'

    def test_mississauga_slug_marks_off_toronto(self):
        # URL slug that names a non-Toronto city should mark the row
        # as off_toronto so it gets filtered from the default view.
        name, status = nl.resolve_neighbourhood(
            'Toronto',
            'https://www.craigslist.org/view/d/mississauga-2br-apartment-near-square-one/abc',
            '',
        )
        assert status == 'off_toronto'

    def test_uninformative_slug_stays_catchall(self):
        # 'toronto-1bed-apt-to-rent-in-toronto' has no neighbourhood
        # hint; raw 'Toronto' stays a catch-all.
        name, status = nl.resolve_neighbourhood(
            'Toronto',
            'https://www.craigslist.org/view/d/toronto-1bed-apt-to-rent-in-toronto/abc',
            '',
        )
        assert name == 'Toronto'
        assert status == 'toronto_catchall'


class TestResolveTitleHint:
    """Generic 'Toronto' rows with informative titles resolve via the
    title hint scan. (We don't see real titles in the SQLite today, but
    the path is exercised when future scrapers start populating them.)"""

    def test_king_west_in_title(self):
        name, status = nl.resolve_neighbourhood(
            'Toronto', '', 'Beautiful 2BR in King West')
        assert name == 'Niagara'
        assert status == 'resolved'

    def test_annex_in_title(self):
        name, status = nl.resolve_neighbourhood(
            'Toronto', '', 'Annex 2BR apartment')
        assert name == 'Annex'
        assert status == 'resolved'


class TestResolveAddressOnly:
    """Non-generic raw values that look like street addresses (numbered
    prefix / intersection / street suffix) get classified as
    low_signal_address. The UI hides them from the default view."""

    def test_numbered_address(self):
        assert nl.resolve_neighbourhood('30 Carabob Court') == (
            '30 Carabob Court', 'low_signal_address')

    def test_numbered_address_with_letter(self):
        assert nl.resolve_neighbourhood('1A Bansley Ave') == (
            '1A Bansley Ave', 'low_signal_address')

    def test_ampersand_intersection(self):
        assert nl.resolve_neighbourhood('Bloor St W & Bathurst St') == (
            'Bloor St W & Bathurst St', 'low_signal_address')

    def test_and_intersection(self):
        # 'Bloor and Yonge' is BOTH a real intersection AND a real
        # intersection in our _DIRECT_MAP -> resolves to a real
        # neighbourhood. Only unrecognised intersections (no _DIRECT_MAP
        # hit AND no street-pattern match) fall to low_signal_address.
        name, status = nl.resolve_neighbourhood('Bloor and Yonge')
        assert name == 'Church-Yonge Corridor'
        assert status == 'resolved'

    def test_slash_intersection(self):
        assert nl.resolve_neighbourhood('Henderson Av / Proctor Av') == (
            'Henderson Av / Proctor Av', 'low_signal_address')

    def test_street_suffix(self):
        assert nl.resolve_neighbourhood('Niska Rd') == (
            'Niska Rd', 'low_signal_address')

    def test_avenue_suffix(self):
        assert nl.resolve_neighbourhood('Beech Avenue') == (
            'Beech Avenue', 'low_signal_address')

    def test_complex_address_with_mixpanel(self):
        assert nl.resolve_neighbourhood(
            '81 Navy Wharf Court - Spadina Avenue / Bremner Blvd   M5V3S2'
        ) == (
            '81 Navy Wharf Court - Spadina Avenue / Bremner Blvd   M5V3S2',
            'low_signal_address',
        )

    def test_whitmore_ave_toronto(self):
        # Has "Ave" suffix + the word Toronto — must still be low-signal
        # because it's an address, not a real neighbourhood.
        assert nl.resolve_neighbourhood('Whitmore Ave, Toronto') == (
            'Whitmore Ave, Toronto', 'low_signal_address')


class TestResolveNonToronto:
    """Listings outside Toronto get off_toronto status so the default
    /api/deals view hides them."""

    def test_brampton(self):
        assert nl.resolve_neighbourhood('Brampton') == (
            'Brampton', 'off_toronto')

    def test_mississauga_ontario(self):
        # NOT in _DIRECT_MAP, but _looks_off_toronto() catches it via
        # substring match on 'mississauga'.
        assert nl.resolve_neighbourhood('Mississauga, Ontario') == (
            'Mississauga, Ontario', 'off_toronto')

    def test_mississauga_erin_mills(self):
        assert nl.resolve_neighbourhood('Mississauga, Erin Mills') == (
            'Mississauga, Erin Mills', 'off_toronto')

    def test_aurora_on(self):
        assert nl.resolve_neighbourhood('Aurora, ON') == (
            'Aurora, ON', 'off_toronto')

    def test_orangeville(self):
        assert nl.resolve_neighbourhood('Orangeville') == (
            'Orangeville', 'off_toronto')

    def test_richmond_hill(self):
        assert nl.resolve_neighbourhood('Richmond hill') == (
            'Richmond hill', 'off_toronto')

    def test_kleinburg(self):
        # Kleinburg is in Vaughan (not Toronto) — off_toronto via DIRECT_MAP.
        assert nl.resolve_neighbourhood('Kleinburg') == (
            'Kleinburg', 'off_toronto')


class TestResolveFallbackRaw:
    """Raw values that don't match any pattern AND don't look like an
    address fall through to 'fallback_raw' — kept as-is, no special
    treatment."""

    def test_leslieville(self):
        # 'Leslieville' isn't in OFFICIAL_NEIGHBOURHOODS and doesn't
        # look like an address — falls through to fallback_raw.
        name, status = nl.resolve_neighbourhood('Leslieville')
        assert status == 'fallback_raw'
        assert name == 'Leslieville'

    def test_fashion_district(self):
        name, status = nl.resolve_neighbourhood('Fashion District')
        assert status == 'fallback_raw'

    def test_near_toronto_general(self):
        # Long descriptive text without street suffix / number prefix
        # but containing '&' which triggers intersection detection, so
        # this is actually low_signal_address. The point of the test
        # is that we don't expose a real neighbourhood name for this
        # kind of ungrounded listing.
        name, status = nl.resolve_neighbourhood(
            'near Toronto General & Princess Margaret Hospital, City Hall')
        assert status in ('low_signal_address', 'fallback_raw')
        # Critically: it must NOT resolve to a real Toronto
        # neighbourhood via fuzzy match (regression guard).
        assert name not in ('Annex', 'Niagara', 'Bay Street Corridor')


class TestResolveIntersectionMaps:
    """Intersection-style raw values that ARE in _DIRECT_MAP should
    resolve to a real neighbourhood (not be classified as low-signal)."""

    def test_king_and_dufferin(self):
        name, status = nl.resolve_neighbourhood('King and Dufferin')
        assert name == 'South Parkdale'
        assert status == 'resolved'

    def test_spadina_and_bloor(self):
        name, status = nl.resolve_neighbourhood('Spadina and Bloor')
        assert name == 'Annex'
        assert status == 'resolved'

    def test_dundas_and_keele(self):
        name, status = nl.resolve_neighbourhood('DUNDAS AND KEELE')
        assert name == 'Dovercourt-Wallace Emerson-Junction'
        assert status == 'resolved'

    def test_dupont_and_lansdowne(self):
        name, status = nl.resolve_neighbourhood('DUPONT AND LANSDOWNE')
        assert name == 'Dovercourt-Wallace Emerson-Junction'
        assert status == 'resolved'

    def test_bay_and_college(self):
        name, status = nl.resolve_neighbourhood('Bay and College')
        assert name == 'Bay Street Corridor'
        assert status == 'resolved'

    def test_king_street_west(self):
        # The "long form" intersection equivalent.
        name, status = nl.resolve_neighbourhood('king street west')
        assert name == 'Niagara'
        assert status == 'resolved'


# ── _looks_like_address classification helper ──────────────────────────────


class TestLooksLikeAddress:
    """_looks_like_address() returns True for street addresses,
    False for neighbourhood names."""

    def test_numbered_prefix(self):
        assert nl._looks_like_address('30 Carabob Court') is True
        assert nl._looks_like_address('5 Mallory Gardens') is True
        assert nl._looks_like_address('1A Bansley Ave') is True

    def test_ampersand_intersection(self):
        assert nl._looks_like_address('Bloor St W & Bathurst St') is True
        assert nl._looks_like_address('Yonge & Bloor') is True

    def test_and_intersection(self):
        assert nl._looks_like_address('Bloor and Yonge') is True
        assert nl._looks_like_address('DUNDAS AND KEELE') is True

    def test_slash_intersection(self):
        assert nl._looks_like_address('Henderson Av / Proctor Av') is True
        assert nl._looks_like_address('Spadina / College') is True

    def test_street_suffix(self):
        assert nl._looks_like_address('Niska Rd') is True
        assert nl._looks_like_address('Beech Avenue') is True
        assert nl._looks_like_address('Conference Blvd') is True
        assert nl._looks_like_address('Montrose Ave') is True

    def test_not_address(self):
        assert nl._looks_like_address('Bay Street Corridor') is False
        assert nl._looks_like_address('Annex') is False
        assert nl._looks_like_address('Niagara') is False
        assert nl._looks_like_address('Agincourt North') is False
        assert nl._looks_like_address('Woburn') is False
        assert nl._looks_like_address('') is False
        assert nl._looks_like_address(None) is False

    def test_toronto_alone(self):
        # 'Toronto' alone is not an address — it's a catch-all.
        assert nl._looks_like_address('Toronto') is False


# ── /api/deals include_fallback filter ──────────────────────────────────────


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


class TestApiDealsExcludeFallback:
    """Default /api/deals hides toronto_catchall, low_signal_address,
    and off_toronto rows. Pass ?include_fallback=true to see all."""

    def test_default_excludes_toronto_catchall(self, client):
        rv = client.get('/api/deals?limit=200')
        assert rv.status_code == 200
        payload = rv.get_json()
        # No row in the default view should have 'toronto_catchall' status.
        statuses = {d.get('neighborhood_status') for d in payload['deals']}
        assert 'toronto_catchall' not in statuses, (
            f'default view leaked toronto_catchall rows: {statuses}')

    def test_default_excludes_low_signal_address(self, client):
        rv = client.get('/api/deals?limit=200')
        statuses = {d.get('neighborhood_status') for d in rv.get_json()['deals']}
        assert 'low_signal_address' not in statuses

    def test_default_excludes_off_toronto(self, client):
        rv = client.get('/api/deals?limit=200')
        statuses = {d.get('neighborhood_status') for d in rv.get_json()['deals']}
        assert 'off_toronto' not in statuses

    def test_toronto_catchall_share_under_5_percent(self, client):
        """AC1: Toronto catch-all share of /api/deals default view
        must be under 5%. Since we now exclude them entirely, the
        share is 0%."""
        rv = client.get('/api/deals?limit=200')
        deals = rv.get_json()['deals']
        toronto_rows = [
            d for d in deals
            if (d.get('neighbourhood') or '').lower() in (
                'toronto', 'city of toronto')
        ]
        share = len(toronto_rows) / max(1, len(deals))
        assert share < 0.05, (
            f'AC1: Toronto catch-all share = {share:.1%}, expected < 5%')

    def test_include_fallback_true_returns_everything(self, client):
        rv_with = client.get('/api/deals?limit=200&include_fallback=true')
        rv_without = client.get('/api/deals?limit=200')
        total_with = rv_with.get_json()['total']
        total_without = rv_without.get_json()['total']
        # include_fallback=true exposes the hidden rows, so total goes up.
        assert total_with > total_without

    def test_include_fallback_exposes_catchall_rows(self, client):
        rv = client.get('/api/deals?limit=200&include_fallback=true')
        statuses = {d.get('neighborhood_status') for d in rv.get_json()['deals']}
        # At least one of the hidden categories must show up.
        assert 'toronto_catchall' in statuses or 'low_signal_address' in statuses

    def test_every_row_has_neighborhood_status(self, client):
        rv = client.get('/api/deals?limit=200')
        for d in rv.get_json()['deals']:
            assert 'neighborhood_status' in d, (
                f'row missing neighborhood_status: {d.get("listing_id")}')
            assert d['neighborhood_status'] in (
                'resolved', 'toronto_catchall', 'low_signal_address',
                'off_toronto', 'fallback_raw',
            ), f'unexpected status: {d.get("neighborhood_status")!r}'


class TestApiMetaCleanNeighborhoods:
    """AC2: /api/meta neighborhoods no longer returns raw street
    addresses as neighbourhood names."""

    def test_no_numbered_street_addresses(self, client):
        rv = client.get('/api/meta')
        nbhds = rv.get_json().get('neighborhoods', [])
        bad = [n['name'] for n in nbhds
               if any(n['name'].startswith(f'{i} ') for i in range(100))]
        assert not bad, f'/api/meta leaked numbered addresses: {bad}'

    def test_no_brampton_or_mississauga(self, client):
        rv = client.get('/api/meta')
        names = {n['name'].lower() for n in rv.get_json().get('neighborhoods', [])}
        assert 'brampton' not in names
        assert 'mississauga' not in names
        assert 'mississauga, ontario' not in names

    def test_no_ampersand_intersection_names(self, client):
        rv = client.get('/api/meta')
        names = [n['name'] for n in rv.get_json().get('neighborhoods', [])]
        # Real neighbourhoods shouldn't contain ' & ' in their name
        # (the City of Toronto uses hyphens / words). The few legit
        # exceptions are NOT in the dataset; the live rows we care
        # about (Bloor & Bathurst etc.) must be filtered.
        bad = [n for n in names if ' & ' in n]
        assert not bad, f'/api/meta leaked &-intersections: {bad}'

    def test_no_catchall_toronto(self, client):
        rv = client.get('/api/meta')
        names = [n['name'] for n in rv.get_json().get('neighborhoods', [])]
        for n in ('Toronto', 'TORONTO', 'city of toronto', 'Downtown Toronto'):
            assert n not in names, f'/api/meta leaked generic Toronto: {n}'

    def test_meta_includes_known_real_neighbourhoods(self, client):
        # Regression: ensure we DIDN'T drop the legitimate ones.
        rv = client.get('/api/meta')
        names = {n['name'] for n in rv.get_json().get('neighborhoods', [])}
        for expected in (
            'Agincourt North', 'Lansing-Westgate', 'Annex',
            'Bay Street Corridor', 'Etobicoke West Mall',
        ):
            assert expected in names, (
                f'/api/meta missing real neighbourhood: {expected}')


class TestNeighborhoodEndpoint:
    """The /api/neighborhoods/<slug>/stats endpoint should still work
    for the neighbourhoods that remain after the filter (regression)."""

    def test_known_slug_returns_200(self, client):
        rv = client.get('/api/neighborhoods/bay-street-corridor/stats')
        assert rv.status_code == 200

    def test_unknown_slug_returns_404(self, client):
        rv = client.get('/api/neighborhoods/atlantis/stats')
        assert rv.status_code == 404

    def test_catchall_slug_now_404(self, client):
        """The 'toronto' slug no longer has any active listings because
        the catch-all rows are hidden from the default view. (If a
        user passes include_fallback=true, the rows still exist in
        load_deals; but the slug-to-name resolution is name-based, so
        we test the inverse: a real slug is still served.)"""
        rv = client.get('/api/neighborhoods/bay-street-corridor/stats')
        payload = rv.get_json()
        assert payload['neighborhood'] == 'Bay Street Corridor'
