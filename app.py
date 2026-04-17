"""
Toronto Rent Deal Finder — Flask Web App
MC-262: Serves deals from SQLite (listings.db) with browsable, filterable UI.
Falls back to deals_output.csv if SQLite is not yet populated.
"""

import os, sys
from flask import Flask, render_template, jsonify, request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'listings.db')
DEALS_CSV = os.path.join(APP_DIR, 'deals_output.csv')

app = Flask(__name__, template_folder=os.path.join(APP_DIR, 'templates'))


def _normalize_row(r: dict) -> dict:
    """Normalize a listing dict to the format expected by the UI."""
    try:
        price = float(r.get('price') or 0)
        fair_value = float(r.get('fair_value') or 0)
        pct_under = float(r.get('pct_under') or 0)
        final_score = float(r.get('score') or r.get('final_score') or 0)
        beds_raw = r.get('beds', '')
        beds = int(float(beds_raw)) if str(beds_raw) not in ('', 'None', 'nan') else None
        baths_raw = r.get('baths', '')
        baths = float(baths_raw) if str(baths_raw) not in ('', 'None', 'nan') else None
        return {
            'neighbourhood': r.get('neighborhood', ''),
            'region': r.get('region', ''),
            'beds': beds,
            'baths': baths,
            'price': price,
            'price_fmt': f"${price:,.0f}",
            'fair_value_fmt': f"${fair_value:,.0f}" if fair_value else '—',
            'pct_under': round(pct_under, 1),
            'pct_under_fmt': f"{pct_under:.1f}%",
            'days_ago': r.get('days_ago', ''),
            'is_stale': str(r.get('is_stale', '')).strip().lower() in ('true', '1', 'yes', '1.0'),
            'commute_minutes': float(r['commute_minutes']) if r.get('commute_minutes', '') not in ('', 'None', 'nan', None) else None,
            'link': r.get('url') or r.get('link', ''),
            'final_score': round(final_score, 3) if final_score else 0,
        }
    except (ValueError, TypeError):
        return None


def load_deals():
    """
    Load active listings from SQLite (MC-262), falling back to CSV.
    """
    # Try SQLite first (MC-262)
    if os.path.exists(DB_PATH):
        try:
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM listings WHERE is_active = 1"
            ).fetchall()
            conn.close()
            if rows:
                deals = []
                for r in rows:
                    d = _normalize_row(dict(r))
                    if d:
                        deals.append(d)
                if deals:
                    return deals
        except Exception:
            pass

    # Fallback to CSV
    import csv
    if not os.path.exists(DEALS_CSV):
        return []
    with open(DEALS_CSV, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    deals = []
    for r in rows:
        d = _normalize_row(r)
        if d:
            deals.append(d)
    return deals


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/deals')
def api_deals():
    deals = load_deals()

    # Parse filter params
    beds_min = request.args.get('beds_min', type=int)
    beds_max = request.args.get('beds_max', type=int)
    baths_min = request.args.get('baths_min', type=int)
    parking = request.args.get('parking', type=lambda v: v.lower() == 'true' if v else None)
    price_min = request.args.get('price_min', type=int)
    price_max = request.args.get('price_max', type=int)
    neighbourhood = request.args.get('neighbourhood', '').strip().lower()
    region = request.args.get('region', '').strip()
    sort_by = request.args.get('sort', 'score')
    max_commute = request.args.get('max_commute', type=int)
    commute_dest = request.args.get('commute_dest', '').strip()

    # Apply filters
    if beds_min is not None:
        deals = [d for d in deals if d['beds'] is not None and d['beds'] >= beds_min]
    if beds_max is not None:
        deals = [d for d in deals if d['beds'] is not None and d['beds'] <= beds_max]
    if baths_min is not None:
        deals = [d for d in deals if d['baths'] is not None and d['baths'] >= baths_min]
    if parking is True:
        deals = [d for d in deals if d['has_parking'] is True]
    if price_min is not None:
        deals = [d for d in deals if d['price'] >= price_min]
    if price_max is not None:
        deals = [d for d in deals if d['price'] <= price_max]
    if neighbourhood:
        deals = [d for d in deals if neighbourhood in d['neighbourhood'].lower()]
    if region:
        deals = [d for d in deals if d.get('region', '') == region]
    if max_commute is not None:
        deals = [d for d in deals if d.get('commute_minutes') is not None and d['commute_minutes'] <= max_commute]
        deals.sort(key=lambda d: d.get('commute_minutes', 999))

    # Sort
    reverse = sort_by not in ('price', 'days_ago')
    key_map = {
        'price': 'price',
        'pct': 'pct_under',
        'score': 'final_score',
        'beds': 'beds',
        'baths': 'baths',
        'days_ago': 'days_ago',
    }
    key = key_map.get(sort_by, 'final_score')
    deals.sort(key=lambda d: d.get(key, 0) if isinstance(d.get(key), (int, float)) else 0, reverse=reverse)

    return jsonify(deals[:50])


@app.route('/api/meta')
def api_meta():
    """Return min/max ranges derived from actual data for UI slider construction."""
    deals = load_deals()
    if not deals:
        return jsonify({'beds': [], 'price': [0, 0], 'baths': [], 'regions': []})

    beds_vals = sorted(set(d['beds'] for d in deals if d['beds'] is not None))
    price_vals = [min(d['price'] for d in deals), max(d['price'] for d in deals)]
    baths_vals = sorted(set(d['baths'] for d in deals if d['baths'] is not None))
    regions = sorted(set(d.get('region', '') for d in deals if d.get('region', '')))

    return jsonify({
        'beds': beds_vals,
        'price': [int(price_vals[0]), int(price_vals[1])],
        'baths': baths_vals,
        'regions': regions,
    })


@app.route('/api/deals/export.csv')
def api_export_csv():
    """CSV export endpoint for data users. MC-262."""
    import csv, io
    deals = load_deals()
    output = io.StringIO()
    if not deals:
        output.write("no data\n")
        return output.getvalue(), 200, {"Content-Type": "text/csv"}
    fieldnames = ['neighbourhood', 'region', 'beds', 'baths', 'price', 'price_fmt',
                  'fair_value_fmt', 'pct_under', 'days_ago', 'commute_minutes', 'link', 'final_score']
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(deals)
    return output.getvalue(), 200, {"Content-Type": "text/csv", "Content-Disposition": "attachment; filename=deals.csv"}


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)