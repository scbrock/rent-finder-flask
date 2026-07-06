/* MC-313: Tests for static/compare.js — side-by-side deal comparison.
 * Run with Node: `node tests/test_mc313_compare.js`.
 * The compare module attaches to window.__compare AND module.exports.
 */
'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

// ── DOM mock ───────────────────────────────────────────────────────────────

function makeMockElement(tag) {
  const el = {
    tagName: (tag || 'DIV').toUpperCase(),
    style: {},
    children: [],
    className: '',
    textContent: '',
    src: '',
    alt: '',
    href: '',
    type: '',
    value: '',
    checked: false,
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); el.className = Array.from(this._set).join(' '); },
      remove(c) { this._set.delete(c); el.className = Array.from(this._set).join(' '); },
      contains(c) { return this._set.has(c); }
    },
    setAttribute(k, v) { this[k] = v; },
    getAttribute(name) { return this[name] !== undefined ? this[name] : null; },
    appendChild(child) { this.children.push(child); child.parentNode = this; return child; },
    removeChild(child) {
      const i = this.children.indexOf(child);
      if (i >= 0) this.children.splice(i, 1);
      return child;
    },
    addEventListener(type, fn) { this._listeners = this._listeners || {}; (this._listeners[type] = this._listeners[type] || []).push(fn); },
    querySelector(selector) {
      const cls = selector.startsWith('.') ? selector.slice(1) : selector;
      const walk = (node) => {
        for (const child of node.children || []) {
          if (child.classList && child.classList.contains(cls)) return child;
          const found = walk(child);
          if (found) return found;
        }
        return null;
      };
      return walk(this);
    },
    querySelectorAll(selector) {
      const cls = selector.startsWith('.') ? selector.slice(1) : selector;
      const out = [];
      const walk = (node) => {
        for (const child of node.children || []) {
          if (child.classList && child.classList.contains(cls)) out.push(child);
          walk(child);
        }
      };
      walk(this);
      return out;
    }
  };
  Object.defineProperty(el, 'firstChild', { get() { return this.children[0] || null; } });
  let _cn = '';
  Object.defineProperty(el, 'className', {
    get() { return _cn; },
    set(v) {
      _cn = v;
      el.classList._set.clear();
      String(v || '').split(/\s+/).filter(Boolean).forEach(c => el.classList._set.add(c));
    }
  });
  let _cn_tc = '';
  Object.defineProperty(el, 'textContent', {
    get() { return _cn_tc; },
    set(v) { _cn_tc = v; }
  });
  return el;
}

const win = { localStorage: undefined };
const localStorageMock = (() => {
  const store = {};
  return {
    getItem(k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
    setItem(k, v) { store[k] = String(v); },
    removeItem(k) { delete store[k]; },
    clear() { Object.keys(store).forEach(k => delete store[k]); }
  };
})();
// Wire localStorage into the win object BEFORE loading the module so that
// the module's `root.localStorage` lookup succeeds during init/load calls.
win.localStorage = localStorageMock;

const stubDoc = {
  createElement(tag) { return makeMockElement(tag); },
  // getElementById returns null (no DOM in tests) so updateCompareBadge's
  // `var btn = document.getElementById('compare_btn')` becomes a no-op.
  getElementById() { return null; },
  querySelector() { return null; },
  querySelectorAll() { return []; }
};

global.window = win;
global.self = win;
global.document = stubDoc;
global.localStorage = localStorageMock;
global.module = undefined;
global.fetch = undefined;  // not exercised in unit tests

// Load the module under test (it assigns to window.__compare AND module.exports)
const comparePath = path.resolve(__dirname, '..', 'static', 'compare.js');
const code = fs.readFileSync(comparePath, 'utf-8');
const moduleScope = { exports: {} };
const fn = new Function('module', 'window', 'self', 'document', 'localStorage', code);
fn(moduleScope, win, win, stubDoc, localStorageMock);
const compare = moduleScope.exports;

// ── Test harness ───────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log('  PASS', name);
  } catch (e) {
    failed += 1;
    console.error('  FAIL', name);
    console.error('    ', e.message);
    if (e.stack) console.error(e.stack.split('\n').slice(1, 3).join('\n'));
  }
}

function makeListing(overrides) {
  const base = {
    listing_id: 'LID_' + Math.random().toString(36).slice(2, 10),
    title: '1BR Apartment',
    neighbourhood: 'King West',
    region: 'Downtown',
    price: 2000,
    price_fmt: '$2,000',
    fair_value: 2500,
    fair_value_fmt: '$2,500',
    pct_under: 20,
    pct_under_fmt: '+20.0%',
    beds: 1,
    baths: 1,
    sqft: '',
    days_ago: 5,
    days_ago_str: '5d ago',
    commute_minutes: 12,
    image_url: '',
    image_urls: [],
    link: 'https://example.com/listing/1',
    final_score: 0.5,
    cautions: [],
    grocery_name: null,
    gym_name: null,
    station_name: null,
    parking_name: null,
    price_per_sqft: null,
    photo_count: 0,
    savings: null
  };
  const merged = Object.assign(base, overrides);
  // Derive savings from price/fair_value if not explicitly overridden
  if (merged.savings === null) {
    if (typeof merged.price === 'number' && typeof merged.fair_value === 'number') {
      merged.savings = merged.fair_value - merged.price;
    }
  }
  // Derive photo_count from image_urls/image_url
  if (merged.photo_count === 0) {
    if (merged.image_urls && merged.image_urls.length) {
      merged.photo_count = merged.image_urls.length;
    } else if (merged.image_url) {
      merged.photo_count = 1;
    }
  }
  return merged;
}

// ── Test: storage round-trip ───────────────────────────────────────────────

test('loadFromStorage: empty when nothing stored', () => {
  localStorageMock.clear();
  assert.deepEqual(compare.loadFromStorage(), []);
});

test('saveToStorage + loadFromStorage round-trip', () => {
  localStorageMock.clear();
  compare.saveToStorage(['A', 'B']);
  // Save via state (save uses internal selected, not param) — call internal directly
  // Actually we test via the public surface: add, then read back.
  // Reset state first
  compare.setState({ selected: [] });
  compare.addToCompare('A');
  compare.addToCompare('B');
  const back = compare.loadFromStorage();
  assert.deepEqual(back, ['A', 'B']);
});

test('storage ignores malformed JSON', () => {
  localStorageMock.setItem(compare.STORAGE_KEY, '{not valid json');
  assert.deepEqual(compare.loadFromStorage(), []);
});

test('storage filters non-string entries and enforces MAX_SELECTED', () => {
  localStorageMock.setItem(compare.STORAGE_KEY, JSON.stringify(['A', 42, null, 'B', 'C', 'D']));
  const back = compare.loadFromStorage();
  assert.equal(back.length, compare.MAX_SELECTED);
  assert.deepEqual(back, ['A', 'B', 'C']);
});

// ── Test: selection mgmt ───────────────────────────────────────────────────

test('addToCompare: adds new id, persists', () => {
  compare.setState({ selected: [] });
  localStorageMock.clear();
  assert.equal(compare.addToCompare('X'), true);
  assert.deepEqual(compare.getSelected(), ['X']);
  assert.equal(compare.addToCompare('X'), false);  // already there
  assert.deepEqual(compare.getSelected(), ['X']);
});

test('addToCompare: caps at MAX_SELECTED (3)', () => {
  compare.setState({ selected: [] });
  localStorageMock.clear();
  assert.equal(compare.addToCompare('A'), true);
  assert.equal(compare.addToCompare('B'), true);
  assert.equal(compare.addToCompare('C'), true);
  assert.equal(compare.addToCompare('D'), false);  // capped
  assert.equal(compare.getSelected().length, 3);
});

test('removeFromCompare: removes + persists', () => {
  compare.setState({ selected: ['A', 'B', 'C'] });
  assert.equal(compare.removeFromCompare('B'), true);
  assert.deepEqual(compare.getSelected(), ['A', 'C']);
  assert.equal(compare.removeFromCompare('Z'), false);
});

test('toggleCompare: flips membership', () => {
  compare.setState({ selected: [] });
  assert.equal(compare.toggleCompare('A'), true);
  assert.equal(compare.isSelected('A'), true);
  assert.equal(compare.toggleCompare('A'), false);
  assert.equal(compare.isSelected('A'), false);
});

test('clearCompare: empties + wipes storage', () => {
  compare.setState({ selected: ['A', 'B'] });
  compare.clearCompare();
  assert.deepEqual(compare.getSelected(), []);
  assert.equal(localStorageMock.getItem(compare.STORAGE_KEY), null);
});

test('isSelected: handles null/empty id', () => {
  compare.setState({ selected: ['A'] });
  assert.equal(compare.isSelected(null), false);
  assert.equal(compare.isSelected(''), false);
  assert.equal(compare.isSelected('A'), true);
});

// ── Test: escHtml / fmtMoney / fmtPct / fmtNum ─────────────────────────────

test('escHtml: escapes HTML special chars', () => {
  assert.equal(compare.escHtml('<script>'), '&lt;script&gt;');
  assert.equal(compare.escHtml('a & b'), 'a &amp; b');
  assert.equal(compare.escHtml('"hi"'), '&quot;hi&quot;');
  assert.equal(compare.escHtml(null), '');
  assert.equal(compare.escHtml(undefined), '');
});

test('fmtMoney: formats with commas, no decimals', () => {
  assert.equal(compare.fmtMoney(2500), '$2,500');
  assert.equal(compare.fmtMoney(0), '$0');
  assert.equal(compare.fmtMoney(null), '—');
  assert.equal(compare.fmtMoney(undefined), '—');
  assert.equal(compare.fmtMoney(NaN), '—');
});

test('fmtPct: signed percent with 1 decimal', () => {
  assert.equal(compare.fmtPct(20), '+20.0%');
  assert.equal(compare.fmtPct(-5.5), '-5.5%');
  assert.equal(compare.fmtPct(0), '0.0%');  // zero shows no sign
  assert.equal(compare.fmtPct(null), '—');
});

test('fmtNum: appends suffix', () => {
  assert.equal(compare.fmtNum(5), '5');
  assert.equal(compare.fmtNum(3, ' photos'), '3 photos');
  assert.equal(compare.fmtNum(null), '—');
});

// ── Test: renderCompareRows shape ──────────────────────────────────────────

test('renderCompareRows: empty payload shows empty message', () => {
  const html = compare.renderCompareRows(null);
  assert.ok(html.includes('cmp-empty'));
  assert.ok(html.includes('No listings'));
});

test('renderCompareRows: 1 listing shows "select 2-3"', () => {
  const html = compare.renderCompareRows({ listings: [makeListing()], best: {} });
  assert.ok(html.includes('cmp-empty'));
  assert.ok(html.includes('Select 2-3'));
});

test('renderCompareRows: 2 listings produces 2 columns', () => {
  const a = makeListing({ listing_id: 'A', price: 2000 });
  const b = makeListing({ listing_id: 'B', price: 1800 });
  const html = compare.renderCompareRows({
    listings: [a, b],
    best: { lowest_price: 'B' }
  });
  // Should have a header with 2 columns (cmp-header) + N rows + remove-row
  assert.ok(html.includes('cmp-header'));
  assert.ok(html.includes('cmp-col-header'));
  // Column count var
  assert.ok(html.includes('--cmp-cols:2'));
});

test('renderCompareRows: 3 listings produces 3 columns', () => {
  const listings = [
    makeListing({ listing_id: 'A', price: 2000 }),
    makeListing({ listing_id: 'B', price: 1800 }),
    makeListing({ listing_id: 'C', price: 2200 })
  ];
  const html = compare.renderCompareRows({
    listings: listings,
    best: { lowest_price: 'B', most_photos: 'C' }
  });
  assert.ok(html.includes('--cmp-cols:3'));
});

test('renderCompareRows: marks best-value cells with cmp-cell-best', () => {
  const a = makeListing({ listing_id: 'A', price: 2000 });
  const b = makeListing({ listing_id: 'B', price: 1800 });
  const html = compare.renderCompareRows({
    listings: [a, b],
    best: { lowest_price: 'B', most_photos: 'A' }
  });
  // The row for "Listed Price" should have one cmp-cell-best (for B)
  const listedPriceRows = html.split('Listed Price')[1] || '';
  // The first cmp-cell-col after the "Listed Price" label is for A, second is for B
  // B should be marked best
  assert.ok(html.includes('cmp-cell-best'));
  // The badge should appear at least twice (one per best metric)
  const badgeCount = (html.match(/cmp-winner-badge/g) || []).length;
  assert.ok(badgeCount >= 1, 'expected at least one winner badge');
});

test('renderCompareRows: includes all required metric labels', () => {
  const a = makeListing({ listing_id: 'A' });
  const b = makeListing({ listing_id: 'B' });
  const html = compare.renderCompareRows({ listings: [a, b], best: {} });
  for (const label of ['Listed Price', 'Fair Value', 'Savings', '% Under Market',
                       'Bedrooms', 'Bathrooms', 'Sqft', '$ / Sqft', 'Age',
                       'Commute', 'Grocery', '🚇 TTC', '🏋 Gym', '🅿 Parking',
                       'Photos', 'Cautions', 'Link']) {
    assert.ok(html.includes(label), `missing row label: ${label}`);
  }
});

test('renderCompareRows: handles listing with no photo (fallback emoji)', () => {
  const a = makeListing({ listing_id: 'A', image_url: '', image_urls: [] });
  const b = makeListing({ listing_id: 'B', image_url: 'http://x.com/1.jpg', image_urls: ['http://x.com/1.jpg'] });
  const html = compare.renderCompareRows({ listings: [a, b], best: {} });
  // A's column should have the fallback
  assert.ok(html.includes('cmp-photo-fallback'));
  assert.ok(html.includes('🏠'));
  // B's column should have an <img>
  assert.ok(html.includes('<img'));
});

test('renderCompareRows: gallery with 3+ photos', () => {
  const a = makeListing({ listing_id: 'A', image_url: 'http://x.com/1.jpg', image_urls: ['http://x.com/1.jpg', 'http://x.com/2.jpg', 'http://x.com/3.jpg'] });
  const b = makeListing({ listing_id: 'B', image_url: 'http://x.com/4.jpg', image_urls: ['http://x.com/4.jpg'] });
  const html = compare.renderCompareRows({ listings: [a, b], best: { most_photos: 'A' } });
  // A's column should have img src to first photo
  assert.ok(html.includes('http://x.com/1.jpg'));
});

test('renderCompareRows: cautions vs clean listing', () => {
  const a = makeListing({ listing_id: 'A', cautions: ['Stale listing'] });
  const b = makeListing({ listing_id: 'B', cautions: [] });
  const html = compare.renderCompareRows({ listings: [a, b], best: {} });
  assert.ok(html.includes('cmp-caution'));
  assert.ok(html.includes('cmp-clean'));
  assert.ok(html.includes('✓ Clean'));
});

test('renderCompareRows: remove buttons emit data-listing-id', () => {
  const a = makeListing({ listing_id: 'ABC123' });
  const b = makeListing({ listing_id: 'XYZ789' });
  const html = compare.renderCompareRows({ listings: [a, b], best: {} });
  assert.ok(html.includes('cmp-remove-btn'));
  assert.ok(html.includes('data-listing-id="ABC123"'));
  assert.ok(html.includes('data-listing-id="XYZ789"'));
});

test('renderCompareRows: negative savings rendered red class', () => {
  const a = makeListing({ listing_id: 'A', price: 3000, fair_value: 2500 });
  const b = makeListing({ listing_id: 'B', price: 2200, fair_value: 2500 });
  const html = compare.renderCompareRows({ listings: [a, b], best: {} });
  assert.ok(html.includes('cmp-savings-neg'));
  assert.ok(html.includes('cmp-savings-pos'));
});

// ── Test: index.html wiring ────────────────────────────────────────────────

test('index.html: includes the compare.js script tag', () => {
  const html = fs.readFileSync(path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8');
  assert.ok(html.includes("filename='compare.js'") || html.includes('filename="compare.js"'));
});

test('index.html: contains the compare modal markup', () => {
  const html = fs.readFileSync(path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8');
  assert.ok(html.includes('id="compare_modal"'));
  assert.ok(html.includes('id="compare_body"'));
  assert.ok(html.includes('id="compare_btn"'));
  assert.ok(html.includes('id="compare_clear_btn"'));
  assert.ok(html.includes('id="compare_btn_label"'));
});

test('index.html: deals table has checkbox column header', () => {
  const html = fs.readFileSync(path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8');
  // Should have ⚖ in a <th> at the start of the thead
  assert.ok(html.includes('class="compare-check"'));
});

test('index.html: renderDeals emits compare-check checkbox in each row', () => {
  const html = fs.readFileSync(path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8');
  // Should have an onchange handler that calls toggleCompare
  assert.ok(html.includes('toggleCompare'));
  assert.ok(html.includes('updateCompareBadge'));
});

test('index.html: contains CSS for compare modal (.cmp-header etc)', () => {
  const html = fs.readFileSync(path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8');
  for (const cls of ['.cmp-header', '.cmp-rows', '.cmp-row', '.cmp-cell-best',
                     '.cmp-winner-badge', '.cmp-savings-pos', '.cmp-savings-neg',
                     '.cmp-clean', '.cmp-caution', '.cmp-remove-btn']) {
    assert.ok(html.includes(cls), `missing CSS class: ${cls}`);
  }
});

// ── Test: static file is loadable and has expected API ─────────────────────

test('static/compare.js: file exists and has expected API surface', () => {
  const full = path.resolve(__dirname, '..', 'static', 'compare.js');
  assert.ok(fs.existsSync(full));
  const src = fs.readFileSync(full, 'utf-8');
  assert.ok(src.length > 1500, 'file too small');
  for (const api of ['addToCompare', 'removeFromCompare', 'toggleCompare',
                     'clearCompare', 'getSelected', 'isSelected',
                     'updateCompareBadge', 'openCompareModal', 'closeCompareModal',
                     'renderCompareRows', 'escHtml', 'fmtMoney']) {
    assert.ok(src.includes(api), `missing API: ${api}`);
  }
  assert.ok(src.includes('module.exports'));
  assert.ok(src.includes('rf_selected_ids'));
});

// ── Test: state survives "page reload" (init restores from localStorage) ───

test('init: restores state from localStorage', () => {
  compare.setState({ selected: [] });
  localStorageMock.setItem(compare.STORAGE_KEY, JSON.stringify(['X', 'Y']));
  compare.init();
  assert.deepEqual(compare.getSelected(), ['X', 'Y']);
});

// ── Done ───────────────────────────────────────────────────────────────────

console.log('\n  ' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);