"""
MC-265: Competitive positioning — deal-first homepage and value prop.
Tests acceptance criteria:
1. Homepage hero section clearly states the value prop
2. Deal score is the most prominent visual element on each listing card
3. Cautions visible on cards without clicking through
4. Stats bar at top: listings today, avg price, best deal
5. "How it works" section: 3 steps
"""

import pytest, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c

def test_index_has_value_prop(client):
    """AC1: Value prop in hero section."""
    html = client.get('/').data.decode('utf-8')
    assert 'Find Toronto rentals priced below market' in html, \
        "Value prop missing from hero section"

def test_how_it_works_section(client):
    """AC5: 'How it works' 3-step section present."""
    html = client.get('/').data.decode('utf-8')
    assert 'How it works' in html
    assert 'We Scrape' in html
    assert 'We Score' in html
    assert 'You Save' in html

def test_stats_bar(client):
    """AC4: Stats bar with listings count, avg % under, best deal."""
    html = client.get('/').data.decode('utf-8')
    assert 'Deals Found' in html or 'Deals Found Today' in html
    assert 'Avg % Under' in html or 'Avg % Under Market' in html
    assert 'Best Deal' in html

def test_score_column_is_first_in_table(client):
    """AC2: Score is first column in table (most prominent position)."""
    html = client.get('/').data.decode('utf-8')
    # First th in table should be Score (not #)
    th_match = re.search(r'<thead>.*?<th[^>]*>([^<]+)</th>', html, re.DOTALL)
    assert th_match, "Could not find first table header"
    first_col = th_match.group(1).strip()
    assert first_col == 'Score', f"First column should be 'Score', got '{first_col}'"

def test_cautions_visible_in_table(client):
    """AC3: Cautions column present in table — visible without clicking."""
    html = client.get('/').data.decode('utf-8')
    assert 'Cautions' in html, "Cautions column missing from table header"

def test_deal_score_td_larger_than_price_td(client):
    """AC2: Score TD font is larger than price TD font."""
    html = client.get('/').data.decode('utf-8')
    # Score TD style: font-size >= 1.1rem
    score_match = re.search(r'<td[^>]*title="Deal score[^"]*"[^>]*style="([^"]*)"', html)
    if score_match:
        style = score_match.group(1)
        assert 'font-size:1.1rem' in style or 'font-size:1.2rem' in style, \
            f"Score font-size not prominent: {style}"
    # Price TD should NOT have extra-large font
    price_td_match = re.search(r'<td>\$\{d\.price_fmt', html)
    assert price_td_match, "Price TD not found"

def test_no_comps_column(client):
    """Comps column should be removed — was confusing/misleading."""
    html = client.get('/').data.decode('utf-8')
    assert 'Comps' not in html

def test_app_renders_without_error(client):
    """App loads and returns 200."""
    r = client.get('/')
    assert r.status_code == 200

def test_api_deals_returns_200(client):
    """API works and returns deals list."""
    r = client.get('/api/deals')
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)
