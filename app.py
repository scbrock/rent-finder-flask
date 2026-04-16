"""
Toronto Rent Deal Finder — Flask Web App
Serves deals from deals_output.csv with a browsable, filterable UI.
"""

from flask import Flask, render_template, jsonify, request
import pandas as pd
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(APP_DIR, 'templates'))

# Load deals from CSV — relative to this file's directory
DEALS_CSV = os.path.join(os.path.dirname(__file__), 'deals_output.csv')


def load_deals():
    """Load and prepare deals DataFrame."""
    if not os.path.exists(DEALS_CSV):
        return pd.DataFrame()
    df = pd.read_csv(DEALS_CSV)
    # Rename for display
    df = df.rename(columns={
        'neighborhood': 'Neighbourhood',
        'beds': 'Beds',
        'price': 'Price',
        'fair_value': 'Fair Value',
        'pct_under': '% Under',
        'days_ago': 'Days Old',
        'link': 'Link',
        'sqft': 'Sqft',
    })
    # Compute display price
    df['Price'] = df['Price'].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
    df['Fair Value'] = df['Fair Value'].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
    df['% Under'] = df['% Under'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
    return df


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/deals')
def api_deals():
    df = load_deals()
    if df.empty:
        return jsonify([])
    
    # Filter params
    max_price = request.args.get('max_price', type=int)
    min_beds = request.args.get('min_beds', type=int)
    neighbourhood = request.args.get('neighbourhood', '')
    sort_by = request.args.get('sort', 'final_score')

    if max_price:
        # Strip $ and commas to get numeric for filtering
        df = df[df['rank'] <= 50]  # top 50 only for perf
    
    if min_beds is not None:
        df = df[df['Beds'] >= min_beds]
    
    if neighbourhood:
        df = df[df['Neighbourhood'].str.contains(neighbourhood, case=False, na=False)]
    
    # Sort
    sort_cols = {
        'score': 'final_score',
        'price': 'Price',
        'pct': 'pct_under',
    }
    col = sort_cols.get(sort_by, 'final_score')
    if col in df.columns:
        df = df.sort_values(col, ascending=False)
    
    # Return as list of dicts
    return jsonify(df.to_dict(orient='records'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)