"""Flask test_client smoke check for MC-353."""
import importlib.util, sys, os
spec = importlib.util.spec_from_file_location('app_rent_finder_353', r'C:\Users\steph\.openclaw\workspace-coding\rent_finder\app.py')
mod = importlib.util.module_from_spec(spec)
sys.modules['app_rent_finder_353'] = mod
spec.loader.exec_module(mod)
flask_app = mod.app
c = flask_app.test_client()
r = c.get('/')
print(f'GET / -> {r.status_code}, {len(r.data)} bytes')
html = r.data.decode('utf-8', errors='replace')
# MC-353 wiring checks
checks = [
    ('MC-353 button id',       'id="recent_searches_btn"' in html),
    ('MC-353 count badge',     'id="recent_searches_count"' in html),
    ('MC-353 popover',         'id="recent_searches_popover"' in html),
    ('MC-353 script',          'recent_searches.js' in html),
    ('MC-353 init wiring',     'createView' in html),
    ('MC-353 attachPopover',   'attachPopover' in html or '__recentSearches.attachPopover' in html or 'attachPopover(' in html),
    ('MC-353 count update JS', 'rsCountEl' in html or 'recent_searches_count' in html),
]
for label, ok in checks:
    print(f'  {"PASS" if ok else "FAIL"}: {label}')
r2 = c.get('/static/recent_searches.js')
print(f'GET /static/recent_searches.js -> {r2.status_code}, {len(r2.data)} bytes')
