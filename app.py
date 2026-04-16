"""
Toronto Rent Deal Finder — Flask Web App
Serves deals from deals_output.csv with a browsable, filterable UI.
"""

import csv
import os
from flask import Flask, render_template, jsonify, request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(APP_DIR, 'templates'))

DEALS_CSV = os.path.join(APP_DIR, 'deals_output.csv')


def load_deals():
    if not os.path.exists(DEALS_CSV):
        return []
    with open(DEALS_CSV, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    deals = []
    for r in rows:
        try:
            price = float(r.get('price', 0) or 0)
            fair_value = float(r.get('fair_value', 0) or 0)
            pct_under = float(r.get('pct_under', 0) or 0)
            final_score = float(r.get('final_score', 0) or 0)
            beds_raw = r.get('beds', '')
            beds = int(float(beds_raw)) if beds_raw not in ('', None) else None
            days_ago = r.get('days_ago', '')
            deals.append({
                'neighbourhood': r.get('neighborhood', ''),
                'beds': beds,
                'price': price,
                'price_fmt': f"${price:,.0f}",
                'fair_value_fmt': f"${fair_value:,.0f}" if fair_value else '—',
                'pct_under': round(pct_under, 1),
                'pct_under_fmt': f"{pct_under:.1f}%",
                'days_ago': days_ago,
                'link': r.get('link', ''),
                'final_score': final_score,
                'sqft': r.get('sqft', ''),
            })
        except (ValueError, TypeError):
            continue
    return deals


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/deals')
def api_deals():
    deals = load_deals()

    max_price = request.args.get('max_price', type=int)
    min_beds = request.args.get('min_beds', type=int)
    neighbourhood = request.args.get('neighbourhood', '').lower()
    sort_by = request.args.get('sort', 'score')

    if max_price:
        deals = [d for d in deals if d['price'] <= max_price]
    if min_beds is not None:
        deals = [d for d in deals if d['beds'] is not None and d['beds'] >= min_beds]
    if neighbourhood:
        deals = [d for d in deals if neighbourhood in d['neighbourhood'].lower()]

    reverse = sort_by != 'price'
    key = 'price' if sort_by == 'price' else 'pct_under' if sort_by == 'pct' else 'final_score'
    deals.sort(key=lambda d: d.get(key, 0), reverse=reverse)

    return jsonify(deals[:50])


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
