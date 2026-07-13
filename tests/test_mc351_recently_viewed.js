// MC-351: Tests for recently_viewed.js (Node).
//
// Hand-rolled localStorage + window + document mocks. Module is loaded
// via require(). Same IIFE pattern as the other static modules so the
// same code runs in browser (window.__recentlyViewed) and Node
// (module.exports).

const assert = require('assert');
const path = require('path');

// Mock storage that behaves like a minimal localStorage. We instantiate
// a fresh one per test so cross-test pollution is impossible.
function createMockStorage() {
  const data = {};
  return {
    data,
    getItem(k) { return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null; },
    setItem(k, v) { data[k] = String(v); },
    removeItem(k) { delete data[k]; },
    clear() { for (const k of Object.keys(data)) delete data[k]; },
  };
}

// Mock window: addEventListener tracking for storage + click + keydown
// events, plus root-level confirm() and open() hooks for the popover.
function createMockWindow() {
  const handlers = {};
  const win = {
    handlers,
    addEventListener(ev, fn) {
      if (!handlers[ev]) handlers[ev] = [];
      handlers[ev].push(fn);
    },
    removeEventListener(ev, fn) {
      if (!handlers[ev]) return;
      handlers[ev] = handlers[ev].filter(h => h !== fn);
    },
    fireStorageEvent(detail) {
      (handlers.storage || []).forEach(fn => fn(detail));
    },
    fireClickEvent(target) {
      (handlers.click || []).forEach(fn => fn({ target }));
    },
    fireKeydown(key) {
      (handlers.keydown || []).forEach(fn => fn({ key }));
    },
    innerWidth: 1024,
    __rf_storage_wired: false,
    __rv_storage_wired: false,
    confirm: null,
    open: null,
  };
  return win;
}

// Mock document: tracks getElementById queries + style mutations so we
// can assert that the popover flips display:none on open/close.
function createMockDocument() {
  const elements = {};
  const mkEl = (id, attrs) => {
    if (!elements[id]) {
      elements[id] = {
        id, checked: false, disabled: false, value: '',
        style: {}, dataset: {}, textContent: '', innerHTML: '',
        classList: { _set: new Set(), add(c){this._set.add(c);}, remove(c){this._set.delete(c);},
                     toggle(c, on){const has = this._set.has(c); if (on === undefined ? !has : !!on) this._set.add(c); else this._set.delete(c);},
                     contains(c){return this._set.has(c);} },
        children: [],
        appendChild(c){ this.children.push(c); },
        setAttribute(k, v) { this.attrs = this.attrs || {}; this.attrs[k] = v; },
        getAttribute(k) { return (this.attrs || {})[k]; },
        addEventListener(ev, fn) { this._ev = this._ev || {}; this._ev[ev] = fn; },
        querySelector(sel) {
          if (sel === '.rv-close') return { addEventListener: () => {} };
          if (sel === '.rv-clear-btn') return { addEventListener: () => {} };
          if (sel === '.rv-view-all') return { addEventListener: () => {} };
          return null;
        },
        querySelectorAll() { return []; },
        getBoundingClientRect() { return { top: 100, bottom: 130, left: 0, right: 120, width: 340, height: 240 }; },
        contains() { return false; },
        attrs: {},
      };
      Object.assign(elements[id], attrs || {});
    }
    return elements[id];
  };
  return {
    elements,
    getElementById: (id) => (elements[id] || null),
    _mkEl: mkEl,
  };
}

const modPath = path.resolve(__dirname, '..', 'static', 'recently_viewed.js');
const rv = require(modPath);

// -------------------------------------------------------------------
// Pure helpers
// -------------------------------------------------------------------
function testEscHtml() {
  const {_escHtml} = rv;
  assert.strictEqual(_escHtml('<script>alert(1)</script>'),
    '&lt;script&gt;alert(1)&lt;/script&gt;');
  assert.strictEqual(_escHtml('Tom & Jerry'), 'Tom &amp; Jerry');
  assert.strictEqual(_escHtml('"quoted"'), '&quot;quoted&quot;');
  assert.strictEqual(_escHtml(null), '');
  assert.strictEqual(_escHtml(undefined), '');
  assert.strictEqual(_escHtml(42), '42');
}
testEscHtml();

function testFmtPrice() {
  const {_fmtPrice} = rv;
  assert.strictEqual(_fmtPrice(1500), '$1,500');
  assert.strictEqual(_fmtPrice(0), '');
  assert.strictEqual(_fmtPrice(-100), '');
  assert.strictEqual(_fmtPrice(NaN), '');
  assert.strictEqual(_fmtPrice('not a number'), '');
  assert.strictEqual(_fmtPrice(1234567), '$1,234,567');
}
testFmtPrice();

function testFmtBedsBaths() {
  const {_fmtBedsBaths} = rv;
  assert.strictEqual(_fmtBedsBaths(0, 1), 'Studio · 1BA');
  assert.strictEqual(_fmtBedsBaths(1, 1), '1BR · 1BA');
  assert.strictEqual(_fmtBedsBaths(2, 0), '2BR');
  assert.strictEqual(_fmtBedsBaths(2, 1.5), '2BR · 1.5BA');
  assert.strictEqual(_fmtBedsBaths(null, null), '');
  assert.strictEqual(_fmtBedsBaths('', ''), '');
  // Studio with no baths
  assert.strictEqual(_fmtBedsBaths(0, null), 'Studio');
  // Just baths
  assert.strictEqual(_fmtBedsBaths(null, 2), '2BA');
  // Non-finite values
  assert.strictEqual(_fmtBedsBaths(NaN, NaN), '');
  assert.strictEqual(_fmtBedsBaths(0, 2.5), 'Studio · 2.5BA');
}
testFmtBedsBaths();

function testFmtViewedAgo() {
  const {_fmtViewedAgo} = rv;
  const now = 1700000000000;
  assert.strictEqual(_fmtViewedAgo(now, now), 'just now');
  assert.strictEqual(_fmtViewedAgo(now - 5 * 1000, now), 'just now');
  assert.strictEqual(_fmtViewedAgo(now - 5 * 60 * 1000, now), '5m ago');
  assert.strictEqual(_fmtViewedAgo(now - 3 * 3600 * 1000, now), '3h ago');
  assert.strictEqual(_fmtViewedAgo(now - 2 * 86400 * 1000, now), '2d ago');
  // Future timestamp (clock skew) clamps to "just now"
  assert.strictEqual(_fmtViewedAgo(now + 60 * 1000, now), 'just now');
  // Garbage input
  assert.strictEqual(_fmtViewedAgo('not-a-number', now), '');
  assert.strictEqual(_fmtViewedAgo(NaN, now), '');
}
testFmtViewedAgo();

// -------------------------------------------------------------------
// Safe parse / storage fallback
// -------------------------------------------------------------------
function testSafeParseStorage() {
  const {_safeParseStorage} = rv;
  assert.deepStrictEqual(_safeParseStorage(''), {});
  assert.deepStrictEqual(_safeParseStorage(null), {});
  assert.deepStrictEqual(_safeParseStorage(undefined), {});
  assert.deepStrictEqual(_safeParseStorage('not json'), {});

  // Object form: {id: ms}
  const now = 1700000000000;
  const obj = _safeParseStorage('{"abc":' + now + '}');
  assert.strictEqual(obj.abc, now);

  // Array form: legacy bare array
  const arr = _safeParseStorage('["a","b"]');
  assert.strictEqual(typeof arr.a, 'number');
  assert.strictEqual(typeof arr.b, 'number');

  // Object with non-numeric values is filtered out
  const filtered = _safeParseStorage('{"a":1,"b":"str","c":null,"d":-1}');
  assert.strictEqual(typeof filtered.a, 'number');
  assert.strictEqual(filtered.b, undefined);
  assert.strictEqual(filtered.c, undefined);
  assert.strictEqual(filtered.d, undefined);
}
testSafeParseStorage();

// -------------------------------------------------------------------
// createView() lifecycle
// -------------------------------------------------------------------
function testCreateViewBasic() {
  const storage = createMockStorage();
  const v = rv.createView({ storage });

  assert.strictEqual(v.getCount(), 0);
  assert.deepStrictEqual(v.getRecent(), []);
}
testCreateViewBasic();

function testGetCountViaLv() {
  // When window.__listingViewed is present, the module delegates to it
  // (ac1). We attach a mock lv onto the IIFE root before the test and
  // verify that getCount() routes through it.
  // The factory closes over `root` at module-load time, so we need to
  // set the property on the actual root binding used by Node (this).
  const storage = createMockStorage();
  global.__listingViewed = {
    count: function () { return 17; },
    getAllViewed: function () {
      return [{ id: 'x', viewedAt: 1000 }, { id: 'y', viewedAt: 500 }];
    },
  };
  try {
    const v = rv.createView({ storage });
    assert.strictEqual(v.getCount(), 17, 'count delegates to window.__listingViewed');
    const recent = v.getRecent(2);
    assert.deepStrictEqual(recent.map(r => r.id), ['x', 'y']);
  } finally {
    delete global.__listingViewed;
  }
}
testGetCountViaLv();

function testGetRecentSortOrder() {
  // Direct-storage path: ids inserted in mixed order, getRecent returns
  // them newest-first by viewedAt timestamp.
  const storage = createMockStorage();
  const v = rv.createView({ storage });

  storage.data['rf_viewed_ids'] = JSON.stringify({
    oldest: 1000, middle: 2000, newest: 3000,
  });
  const recent = v.getRecent(10);
  assert.deepStrictEqual(recent.map(r => r.id), ['newest', 'middle', 'oldest']);
}
testGetRecentSortOrder();

function testGetRecentLimit() {
  const storage = createMockStorage();
  const v = rv.createView({ storage });

  // Build a storage with 15 ids; limit to 5
  const obj = {};
  for (let i = 0; i < 15; i++) obj['id_' + i] = 1000 + i;
  storage.data['rf_viewed_ids'] = JSON.stringify(obj);
  const recent = v.getRecent(5);
  assert.strictEqual(recent.length, 5);
  // The most recent 5 (ids 10..14) come back
  assert.deepStrictEqual(recent.map(r => r.id), ['id_14', 'id_13', 'id_12', 'id_11', 'id_10']);
}
testGetRecentLimit();

// -------------------------------------------------------------------
// setDeals() + renderEntry() integration
// -------------------------------------------------------------------
function testSetDealsLookup() {
  const storage = createMockStorage();
  const v = rv.createView({ storage });

  // setDeals() builds an id->deal index so renderEntry can hydrate entries.
  const deals = [
    { listing_id: 'a1', price: 1500, neighbourhood: 'Annex', beds: 1, baths: 1, image_url: 'http://x/a.jpg', pct_under: 12 },
    { listing_id: 'b2', price: 2200, neighbourhood: 'King West', beds: 2, baths: 1, pct_under: 0 },
    { listing_id: 'c3', price: 0, neighbourhood: '', beds: null, baths: null }, // sparse row
  ];
  v.setDeals(deals);

  // Add an id to storage
  storage.data['rf_viewed_ids'] = JSON.stringify({ a1: 1000, b2: 2000 });
  const recent = v.getRecent(10);
  assert.strictEqual(recent.length, 2);

  // Rendering 'a1' should pick up the deal via the lookup
  const htmlA = v.renderEntry({ listing_id: 'a1', price: 1500, neighbourhood: 'Annex', beds: 1, baths: 1, image_url: 'http://x/a.jpg', pct_under: 12.4, pct_under_fmt: '12.4%' }, 1000);
  assert.ok(htmlA.includes('rv-thumb'), 'has thumbnail wrapper');
  assert.ok(htmlA.includes('http://x/a.jpg'), 'has image url');
  assert.ok(htmlA.includes('$1,500'), 'has formatted price');
  assert.ok(htmlA.includes('Annex'), 'has neighbourhood');
  assert.ok(htmlA.includes('1BR'), 'has beds string');
  assert.ok(htmlA.includes('1BA'), 'has baths string');
  assert.ok(htmlA.includes('12.4%'), 'has pct chip');
  assert.ok(htmlA.includes('viewed'));
  assert.ok(htmlA.includes('Open deal'), 'has open-deal link');
  assert.ok(htmlA.includes('/d/a1'), 'has /d/<id> link');

  // Empty deal is falsy → empty string
  assert.strictEqual(v.renderEntry(null, 1000), '');
  assert.strictEqual(v.renderEntry({}, 1000), '');
}
testSetDealsLookup();

function testRenderEntryEscapesUserDerivableStrings() {
  const storage = createMockStorage();
  const v = rv.createView({ storage });

  const evil = {
    listing_id: 'evil<>id',
    price: 1234,
    neighbourhood: '<script>alert("n")</script>',
    beds: 2,
    baths: 1,
    image_url: 'javascript:alert(1)',
    pct_under: 15,
    pct_under_fmt: '<img onerror=alert(1) src=x>',
  };
  const html = v.renderEntry(evil, 1000);
  // None of these dangerous characters should appear unescaped:
  assert.ok(!html.includes('<script>alert'), 'script tag escaped');
  assert.ok(!html.includes('<img onerror'), 'img tag escaped');
  assert.ok(!html.includes('javascript:alert'), 'javascript: url escaped');
  // Escaped forms ARE allowed
  assert.ok(html.includes('&lt;script&gt;') || html.includes('&lt;img'), 'has escaped entity');
}
testRenderEntryEscapesUserDerivableStrings();

function testRenderEntryStudio() {
  const storage = createMockStorage();
  const v = rv.createView({ storage });
  const studio = { listing_id: 'stud1', price: 1500, neighbourhood: 'Harbourfront', beds: 0, baths: 1 };
  const html = v.renderEntry(studio, 0);
  assert.ok(html.includes('Studio'), 'beds=0 renders as Studio');
  assert.ok(html.includes('1BA'), 'baths still rendered');
}
testRenderEntryStudio();

function testRenderEntryNoImage() {
  const storage = createMockStorage();
  const v = rv.createView({ storage });
  const noimg = { listing_id: 'ni1', price: 1500, neighbourhood: 'Etobicoke', beds: 1, baths: 1, image_url: '' };
  const html = v.renderEntry(noimg, 0);
  assert.ok(!html.includes('rv-thumb-img'), 'no <img> tag without image');
  assert.ok(html.includes('rv-thumb-fallback'), 'fallback emoji present');
}
testRenderEntryNoImage();

function testRenderEntryNoPctChipWhenZero() {
  const storage = createMockStorage();
  const v = rv.createView({ storage });
  const atMarket = { listing_id: 'am1', price: 2000, neighbourhood: 'Midtown', beds: 2, baths: 1, pct_under: 0 };
  const html = v.renderEntry(atMarket, 0);
  assert.ok(!html.includes('rv-pct-chip'), 'no pct chip when pct_under === 0');
}
testRenderEntryNoPctChipWhenZero();

// -------------------------------------------------------------------
// listenStorage() delegation + fallback
// -------------------------------------------------------------------
function testListenStorageDelegatesToLv() {
  const storage = createMockStorage();
  const win = createMockWindow();
  // Mock lv module exposed at the IIFE root.
  const lvCalls = [];
  global.__listingViewed = {
    listenStorage: function (cb) { lvCalls.push(cb); },
  };
  try {
    const v = rv.createView({ storage, window: win });
    const myCb = function () {};
    v.listenStorage(myCb);
    // Must delegate, NOT wire its own storage handler
    assert.strictEqual(lvCalls.length, 1, 'delegated to lv.listenStorage');
    assert.strictEqual(win.handlers.storage, undefined,
      'no fallback handler wired when lv is present');
  } finally {
    delete global.__listingViewed;
  }
}
testListenStorageDelegatesToLv();

function testListenStorageFallbackWhenLvMissing() {
  const storage = createMockStorage();
  const win = createMockWindow();
  const v = rv.createView({ storage, window: win });
  let fired = false;
  v.listenStorage(function () { fired = true; });
  // lv is absent → wire own storage handler
  assert.ok(Array.isArray(win.handlers.storage), 'own handler wired');
  win.fireStorageEvent({ key: 'rf_viewed_ids' });
  assert.ok(fired, 'listener fires from own handler');
  // Second register should be idempotent (no double-wire)
  v.listenStorage(function () {});
  assert.strictEqual(win.handlers.storage.length, 1,
    'no additional storage handlers wired on subsequent listenStorage calls');
  // Wrong key is ignored
  fired = false;
  win.fireStorageEvent({ key: 'something_else' });
  assert.strictEqual(fired, false);
}
testListenStorageFallbackWhenLvMissing();

// -------------------------------------------------------------------
// clearAll() fallback when lv is missing
// -------------------------------------------------------------------
function testClearAllFallback() {
  const storage = createMockStorage();
  const v = rv.createView({ storage });
  storage.data['rf_viewed_ids'] = JSON.stringify({ a: 1000, b: 2000 });
  assert.strictEqual(v.getCount(), 2);
  v.clearAll();
  // Storage is wiped to '{}' (same shape MC-350 writes).
  assert.strictEqual(storage.data['rf_viewed_ids'], '{}');
  assert.strictEqual(v.getCount(), 0);
}
testClearAllFallback();

function testClearAllDelegatesToLv() {
  const storage = createMockStorage();
  const lvCalls = [];
  global.__listingViewed = {
    clearAll: function () { lvCalls.push(true); },
  };
  try {
    const v = rv.createView({ storage });
    storage.data['rf_viewed_ids'] = JSON.stringify({ a: 1000 });
    v.clearAll();
    assert.strictEqual(lvCalls.length, 1, 'delegated to lv.clearAll');
    // Storage is not touched by fallback path when lv handled it
    assert.ok(storage.data['rf_viewed_ids']);
  } finally {
    delete global.__listingViewed;
  }
}
testClearAllDelegatesToLv();

// -------------------------------------------------------------------
// refresh() updates the count badge and disables the trigger when empty
// -------------------------------------------------------------------
function testRefreshUpdatesBadge() {
  const storage = createMockStorage();
  const doc = createMockDocument();
  doc.getElementById('recent_viewed_count') ||
    (doc.elements['recent_viewed_count'] = { id: 'recent_viewed_count', textContent: '0' });
  const trigger = doc.elements['recent_viewed_btn'] = {
    id: 'recent_viewed_btn',
    disabled: false,
    textContent: '',
    addEventListener: function () {},
    getBoundingClientRect: function () { return { top: 50, bottom: 80, left: 0, right: 100, width: 100, height: 30 }; },
    contains: function () { return false; },
  };
  const container = doc.elements['recent_viewed_popover'] = {
    id: 'recent_viewed_popover',
    innerHTML: '',
    setAttribute: function (k, v) { this.attrs = this.attrs || {}; this.attrs[k] = v; },
    getAttribute: function (k) { return (this.attrs || {})[k]; },
    addEventListener: function () {},
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    getBoundingClientRect: function () { return { top: 0, bottom: 80, left: 0, right: 340, width: 340, height: 240 }; },
    contains: function () { return false; },
    style: {},
  };
  global.document = doc;
  try {
    const v = rv.createView({ storage, document: doc });
    // attachPopover wires _triggerEl + container so refresh() can update
    // both the badge and the trigger-disabled state.
    v.attachPopover(trigger, container);

    storage.data['rf_viewed_ids'] = JSON.stringify({ a: 1000, b: 2000, c: 3000 });
    v.refresh();
    assert.strictEqual(doc.elements['recent_viewed_count'].textContent, '3');
    assert.strictEqual(trigger.disabled, false);

    // Empty: badge resets to "0" and trigger is disabled
    storage.data['rf_viewed_ids'] = '{}';
    v.refresh();
    assert.strictEqual(doc.elements['recent_viewed_count'].textContent, '0');
    assert.strictEqual(trigger.disabled, true);
  } finally {
    delete global.document;
  }
}
testRefreshUpdatesBadge();

// -------------------------------------------------------------------
// Module exports + IIFE wrapper shape
// -------------------------------------------------------------------
function testModuleExports() {
  assert.strictEqual(rv.DEFAULT_STORAGE_KEY, 'rf_viewed_ids');
  assert.strictEqual(rv.DEFAULT_MAX_ENTRIES, 10);
  assert.strictEqual(typeof rv.createView, 'function');
  assert.strictEqual(typeof rv._escHtml, 'function');
  assert.strictEqual(typeof rv._fmtPrice, 'function');
  assert.strictEqual(typeof rv._fmtBedsBaths, 'function');
  assert.strictEqual(typeof rv._fmtViewedAgo, 'function');
  assert.strictEqual(typeof rv._safeParseStorage, 'function');

  const src = require('fs').readFileSync(modPath, 'utf8');
  assert.ok(src.includes("root.__recentlyViewed = factory()"),
    'module registers window.__recentlyViewed when not in CommonJS context');
  assert.ok(src.includes('function (root, factory)'),
    'uses (function (root, factory) ...) wrapper');
  assert.ok(src.includes("module.exports = factory()"),
    'falls back to module.exports for Node');
  assert.ok(src.includes("typeof self !== 'undefined' ? self : this"),
    'detects browser root via self/this');
  assert.ok(src.trim().endsWith('}));'),
    'IIFE is closed');
}
testModuleExports();

// -------------------------------------------------------------------
// attachPopover() opens, positions, and closes the container
// -------------------------------------------------------------------
function testAttachPopoverOpenClose() {
  const storage = createMockStorage();
  const win = createMockWindow();
  const doc = createMockDocument();

  const trigger = doc.elements['recent_viewed_btn'] = {
    id: 'recent_viewed_btn',
    disabled: false,
    addEventListener: function (ev, fn) { this._ev = this._ev || {}; this._ev[ev] = fn; },
    getBoundingClientRect: function () { return { top: 50, bottom: 80, left: 0, right: 100, width: 100, height: 30 }; },
    contains: function () { return false; },
  };
  const container = doc.elements['recent_viewed_popover'] = {
    id: 'recent_viewed_popover',
    innerHTML: '',
    setAttribute: function (k, v) { this.attrs = this.attrs || {}; this.attrs[k] = v; },
    getAttribute: function (k) { return (this.attrs || {})[k]; },
    addEventListener: function (ev, fn) { this._ev = this._ev || {}; this._ev[ev] = fn; },
    querySelector: function (sel) {
      if (sel === '.rv-close') return { addEventListener: () => {} };
      if (sel === '.rv-clear-btn') return { addEventListener: () => {} };
      if (sel === '.rv-view-all') return { addEventListener: () => {} };
      return null;
    },
    querySelectorAll: function () { return []; },
    getBoundingClientRect: function () { return { top: 0, bottom: 80, left: 0, right: 340, width: 340, height: 240 }; },
    contains: function () { return false; },
    style: {},
  };
  global.document = doc;
  try {
    const v = rv.createView({ storage, window: win, document: doc });
    v.attachPopover(trigger, container);

    // Initial state: badge text + disabled flag (no entries yet)
    assert.strictEqual(container.getAttribute('data-state'), undefined,
      'starts closed');

    // Simulate a click on the trigger to open the popover
    storage.data['rf_viewed_ids'] = JSON.stringify({ a: 1000 });
    trigger._ev.click({ preventDefault: () => {}, stopPropagation: () => {} });
    assert.strictEqual(container.getAttribute('data-state'), 'open',
      'opens on trigger click');
    assert.ok(container.innerHTML.includes('Recently viewed'),
      'popover content rendered');
    assert.ok(container.innerHTML.includes('rv-header'),
      'header is present');
    assert.notStrictEqual(container.style.display, 'none',
      'display cleared when open');

    // Click outside should close
    win.fireClickEvent({}); // generic outside target
    assert.strictEqual(container.getAttribute('data-state'), 'closed',
      'closes on outside-click');
    assert.strictEqual(container.style.display, 'none',
      'display:none when closed');

    // Escape should also close
    trigger._ev.click({ preventDefault: () => {}, stopPropagation: () => {} }); // open again
    // open succeeded
    assert.strictEqual(container.getAttribute('data-state'), 'open');
    win.fireKeydown('Escape');
    assert.strictEqual(container.getAttribute('data-state'), 'closed',
      'closes on Escape');
  } finally {
    delete global.document;
  }
}
testAttachPopoverOpenClose();

console.log('Passed: 20 / Failed: 0 / Total: 20');
