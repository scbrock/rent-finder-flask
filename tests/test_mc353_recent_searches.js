// MC-353: Tests for recent_searches.js (Node).
//
// Hand-rolled localStorage + window + document mocks. Module is loaded
// via require(). Same IIFE pattern as the other static modules so the
// same code runs in browser (window.__recentSearches) and Node
// (module.exports).

const assert = require('assert');
const path = require('path');

// Mock storage: behaves like a minimal localStorage. Fresh per test.
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

function createMockWindow() {
  const handlers = {};
  return {
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
    innerWidth: 1024,
    __rs_storage_wired: false,
    confirm: null,
  };
}

function createMockDocument() {
  const elements = {};
  return {
    elements,
    getElementById(id) { return elements[id] || null; },
    querySelectorAll() { return []; },
    _mkEl(id, attrs) {
      const el = Object.assign({
        id,
        checked: false,
        disabled: false,
        value: '',
        style: {},
        dataset: {},
        textContent: '',
        innerHTML: '',
        attrs: {},
        classList: {
          _set: new Set(),
          add(c) { this._set.add(c); },
          remove(c) { this._set.delete(c); },
          toggle(c, on) {
            const has = this._set.has(c);
            if (on === undefined ? !has : !!on) this._set.add(c);
            else this._set.delete(c);
          },
          contains(c) { return this._set.has(c); },
        },
        setAttribute(k, v) { this.attrs[k] = v; },
        getAttribute(k) { return this.attrs[k]; },
        addEventListener() {},
        querySelector() { return null; },
        querySelectorAll() { return []; },
        getBoundingClientRect() { return { top: 100, bottom: 130, left: 0, right: 120, width: 340, height: 240 }; },
        contains() { return false; },
      }, attrs || {});
      elements[id] = el;
      return el;
    },
  };
}

const modPath = path.resolve(__dirname, '..', 'static', 'recent_searches.js');
const rs = require(modPath);

// -------------------------------------------------------------------
// Pure helpers — _escHtml
// -------------------------------------------------------------------
function testEscHtml() {
  const { _escHtml } = rs;
  assert.strictEqual(_escHtml('<script>alert(1)</script>'),
    '&lt;script&gt;alert(1)&lt;/script&gt;');
  assert.strictEqual(_escHtml('Tom & Jerry'), 'Tom &amp; Jerry');
  assert.strictEqual(_escHtml('"quoted"'), '&quot;quoted&quot;');
  assert.strictEqual(_escHtml(null), '');
  assert.strictEqual(_escHtml(undefined), '');
  assert.strictEqual(_escHtml(42), '42');
}
testEscHtml();

// -------------------------------------------------------------------
// Pure helpers — _canonicalFilters
// -------------------------------------------------------------------
function testCanonicalFiltersBasic() {
  const { _canonicalFilters } = rs;
  const out = _canonicalFilters({
    beds_min: '2', price_max: '2500', neighbourhood: 'Downtown',
    bogus_key: 'x',
  });
  assert.strictEqual(out.beds_min, '2');
  assert.strictEqual(out.price_max, '2500');
  assert.strictEqual(out.neighbourhood, 'Downtown');
  assert.strictEqual(out.bogus_key, undefined);
}
testCanonicalFiltersBasic();

function testCanonicalFiltersStripsEmpty() {
  const { _canonicalFilters } = rs;
  const out = _canonicalFilters({
    beds_min: '', price_max: '', neighbourhood: null, region: undefined,
  });
  // Empty strings and null / undefined are all stripped.
  assert.strictEqual(Object.keys(out).length, 0);
}
testCanonicalFiltersStripsEmpty();

function testCanonicalFiltersKeepsZeroNumeric() {
  // '0' is a valid value (e.g. price_max=0 means "free"). buildParams()
  // also treats a string '0' as truthy and round-trips it. Match that
  // behavior so the saved-search dedup key is consistent with what the
  // URL bar sees.
  const { _canonicalFilters } = rs;
  const out = _canonicalFilters({ price_max: '0' });
  assert.strictEqual(out.price_max, '0');
}
testCanonicalFiltersKeepsZeroNumeric();

function testCanonicalFiltersConvertsBooleans() {
  const { _canonicalFilters } = rs;
  const out = _canonicalFilters({
    hide_stale: true, only_new: false, is_new: true,
  });
  assert.strictEqual(out.hide_stale, 'true');
  assert.strictEqual(out.only_new, undefined);  // false → '' → dropped
  assert.strictEqual(out.is_new, 'true');
  assert.strictEqual(Object.keys(out).length, 2);
}
testCanonicalFiltersConvertsBooleans();

// -------------------------------------------------------------------
// Pure helpers — serializeFilters (deterministic / dedup-stable)
// -------------------------------------------------------------------
function testSerializeFiltersDeterministic() {
  const { serializeFilters } = rs;
  const a = { beds_min: '2', price_max: '2500' };
  const b = { price_max: '2500', beds_min: '2' };
  assert.strictEqual(serializeFilters(a), serializeFilters(b));
}
testSerializeFiltersDeterministic();

function testSerializeFiltersIgnoresUnknown() {
  const { serializeFilters } = rs;
  const a = { beds_min: '2' };
  const b = { beds_min: '2', random_garbage: 'ignored' };
  assert.strictEqual(serializeFilters(a), serializeFilters(b));
}
testSerializeFiltersIgnoresUnknown();

// -------------------------------------------------------------------
// Pure helpers — buildLabel
// -------------------------------------------------------------------
function testBuildLabelAllDeals() {
  const { buildLabel } = rs;
  // Empty / non-object inputs fall back to a default "All deals" baseline.
  assert.strictEqual(buildLabel(null), 'All deals');
  assert.strictEqual(buildLabel('not-an-object'), 'All deals');
  assert.strictEqual(buildLabel(undefined), 'All deals');
  // Empty filters object gets the full default label (with location + sort).
  const empty = buildLabel({});
  assert.ok(empty.includes('All'), 'default label has All, got: ' + empty);
  assert.ok(empty.includes('best deal'), 'default label mentions sort, got: ' + empty);
}
testBuildLabelAllDeals();

function testBuildLabelBedsStudio() {
  const { buildLabel } = rs;
  const label = buildLabel({ beds_min: '0' });
  assert.ok(label.includes('Studio'), 'studio label, got: ' + label);
}
testBuildLabelBedsStudio();

function testBuildLabelBedsNumber() {
  const { buildLabel } = rs;
  const label = buildLabel({ beds_min: '2', price_max: '2500' });
  assert.ok(label.includes('2BR'), 'has 2BR, got: ' + label);
  assert.ok(label.includes('$2,500'), 'has $2,500, got: ' + label);
}
testBuildLabelBedsNumber();

function testBuildLabelNeighbourhoodWins() {
  const { buildLabel } = rs;
  const label = buildLabel({ neighbourhood: 'Annex', region: 'Downtown' });
  assert.ok(label.includes('Annex'), 'neighbourhood wins over region');
  assert.ok(!label.includes('Downtown'), 'region not used');
}
testBuildLabelNeighbourhoodWins();

function testBuildLabelRegionFallback() {
  const { buildLabel } = rs;
  const label = buildLabel({ region: 'Midtown' });
  assert.ok(label.includes('Midtown'), 'region used when no nbhd');
}
testBuildLabelRegionFallback();

function testBuildLabelSortDefault() {
  const { buildLabel } = rs;
  const label = buildLabel({ beds_min: '2' });
  assert.ok(label.includes('best deal'), 'default sort shows in label');
}
testBuildLabelSortDefault();

function testBuildLabelSortExplicit() {
  const { buildLabel } = rs;
  const label = buildLabel({ beds_min: '2', sort: 'price' });
  assert.ok(label.includes('price'), 'sort=price shown, got: ' + label);
}
testBuildLabelSortExplicit();

function testBuildLabelToggleAdornments() {
  const { buildLabel } = rs;
  const label = buildLabel({ beds_min: '1', hide_stale: 'true', is_new: 'true' });
  assert.ok(label.includes('hide stale'), 'hide_stale chip, got: ' + label);
  assert.ok(label.includes('only new'), 'is_new chip, got: ' + label);
}
testBuildLabelToggleAdornments();

function testBuildLabelLengthCap() {
  const { buildLabel } = rs;
  // A long neighbourhood + many toggles should still produce a label <120 chars.
  const label = buildLabel({
    beds_min: '3',
    neighbourhood: 'A Very Long Neighbourhood Name That Should Be Trimmed',
    region: 'Midtown',
    source: 'kijiji',
    sort: 'pct_under',
    hide_stale: 'true',
    is_new: 'true',
    price_dropped: 'true',
    has_image: 'true',
    has_parking: 'true',
    min_pct_under: '20',
  });
  assert.ok(label.length <= 110, 'label is truncated, got ' + label.length + ' chars');
}
testBuildLabelLengthCap();

// -------------------------------------------------------------------
// Pure helpers — _fmtAgo
// -------------------------------------------------------------------
function testFmtAgo() {
  const { _fmtAgo } = rs;
  const now = 1700000000000;
  assert.strictEqual(_fmtAgo(now, now), 'just now');
  assert.strictEqual(_fmtAgo(now - 5 * 1000, now), 'just now');
  assert.strictEqual(_fmtAgo(now - 5 * 60 * 1000, now), '5m ago');
  assert.strictEqual(_fmtAgo(now - 3 * 3600 * 1000, now), '3h ago');
  assert.strictEqual(_fmtAgo(now - 25 * 3600 * 1000, now), 'yesterday');
  assert.strictEqual(_fmtAgo(now - 2 * 86400 * 1000, now), '2d ago');
  assert.strictEqual(_fmtAgo(now - 1 * 86400 * 1000, now), 'yesterday');
  // Future timestamp clamps to "just now"
  assert.strictEqual(_fmtAgo(now + 60 * 1000, now), 'just now');
  // Garbage input
  assert.strictEqual(_fmtAgo('not-a-number', now), '');
  assert.strictEqual(_fmtAgo(NaN, now), '');
}
testFmtAgo();

// -------------------------------------------------------------------
// Pure helpers — _safeParse
// -------------------------------------------------------------------
function testSafeParse() {
  const { _safeParse } = rs;
  assert.deepStrictEqual(_safeParse(''), []);
  assert.deepStrictEqual(_safeParse(null), []);
  assert.deepStrictEqual(_safeParse(undefined), []);
  assert.deepStrictEqual(_safeParse('not json'), []);

  // Empty array of objects
  assert.deepStrictEqual(_safeParse('[]'), []);

  // Array with malformed entries is filtered
  const filtered = _safeParse(JSON.stringify([
    { filters: { beds_min: '2' }, label: 'Two BR', savedAtMs: 1000 },
    { filters: {}, label: 'empty' },                            // dropped (no filters)
    null,                                                       // dropped
    'a string entry',                                           // dropped
    { filters: { price_max: '3000' }, savedAtMs: 2000 },         // label auto-generated
  ]));
  assert.strictEqual(filtered.length, 2);
  assert.strictEqual(filtered[0].label, 'Two BR');
  assert.ok(filtered[1].label.length > 0, 'auto label populated');
}
testSafeParse();

// -------------------------------------------------------------------
// createView() — basic lifecycle
// -------------------------------------------------------------------
function testCreateViewEmpty() {
  const storage = createMockStorage();
  const v = rs.createView({ storage });
  assert.strictEqual(v.count(), 0);
  assert.deepStrictEqual(v.getAll(), []);
  assert.deepStrictEqual(v.getRecent(5), []);
}
testCreateViewEmpty();

function testSaveCurrentNewestFirst() {
  const storage = createMockStorage();
  const v = rs.createView({ storage });

  v.saveCurrent({ beds_min: '1' });
  v.saveCurrent({ beds_min: '2' });
  v.saveCurrent({ beds_min: '3' });
  const all = v.getAll();
  assert.strictEqual(all.length, 3);
  assert.strictEqual(all[0].filters.beds_min, '3', 'most recent first');
  assert.strictEqual(all[2].filters.beds_min, '1');
}
testSaveCurrentNewestFirst();

function testSaveCurrentCapAtFive() {
  const storage = createMockStorage();
  const v = rs.createView({ storage });

  for (let i = 0; i < 8; i++) {
    v.saveCurrent({ beds_min: String(i) });
  }
  const all = v.getAll();
  assert.strictEqual(all.length, 5);
  // Only the last 5 are kept; beds_min=7 is the most-recent
  assert.strictEqual(all[0].filters.beds_min, '7');
  assert.strictEqual(all[4].filters.beds_min, '3');
}
testSaveCurrentCapAtFive();

function testSaveCurrentDedup() {
  const storage = createMockStorage();
  const v = rs.createView({ storage });

  v.saveCurrent({ beds_min: '2', price_max: '2500' });
  v.saveCurrent({ beds_min: '1' });
  // Re-applying the SAME filter set as the most-recent (beds_min=1)
  // should NOT push a duplicate — count stays at 2 and order is stable.
  v.saveCurrent({ beds_min: '1' });
  const all = v.getAll();
  assert.strictEqual(all.length, 2, 'no duplicate on identical recent set');
  assert.strictEqual(all[0].filters.beds_min, '1', 'most-recent stays on top');
}
testSaveCurrentDedup();

function testSaveCurrentSkipsEmpty() {
  const storage = createMockStorage();
  const v = rs.createView({ storage });
  // Empty filter set is skipped (no spam on page load).
  assert.strictEqual(v.saveCurrent({}), false);
  assert.strictEqual(v.count(), 0);
  // Force=true bypasses the empty check
  assert.strictEqual(v.saveCurrent({}, { force: true }), true);
  assert.strictEqual(v.count(), 1);
}
testSaveCurrentSkipsEmpty();

function testSaveCurrentPersists() {
  const storage = createMockStorage();
  const v = rs.createView({ storage });
  v.saveCurrent({ beds_min: '2', price_max: '2500' });
  // Re-read from the raw storage to confirm write happened
  const raw = storage.getItem('rf_recent_searches');
  assert.ok(raw, 'storage write happened');
  const parsed = JSON.parse(raw);
  assert.strictEqual(parsed.length, 1);
  assert.strictEqual(parsed[0].filters.beds_min, '2');
}
testSaveCurrentPersists();

function testRemoveAt() {
  const storage = createMockStorage();
  const v = rs.createView({ storage });
  v.saveCurrent({ beds_min: '1' });
  v.saveCurrent({ beds_min: '2' });
  v.saveCurrent({ beds_min: '3' });
  assert.strictEqual(v.count(), 3);
  // Remove the middle entry
  assert.strictEqual(v.removeAt(1), true);
  assert.strictEqual(v.count(), 2);
  assert.strictEqual(v.getAll()[0].filters.beds_min, '3');
  assert.strictEqual(v.getAll()[1].filters.beds_min, '1');
  // Out-of-range returns false
  assert.strictEqual(v.removeAt(99), false);
  assert.strictEqual(v.removeAt(-1), false);
}
testRemoveAt();

function testClearAll() {
  const storage = createMockStorage();
  const v = rs.createView({ storage });
  v.saveCurrent({ beds_min: '1' });
  v.saveCurrent({ beds_min: '2' });
  assert.strictEqual(v.count(), 2);
  v.clearAll();
  assert.strictEqual(v.count(), 0);
  // Storage is wiped
  assert.deepStrictEqual(JSON.parse(storage.getItem('rf_recent_searches')), []);
}
testClearAll();

// -------------------------------------------------------------------
// Module exports + IIFE wrapper shape
// -------------------------------------------------------------------
function testModuleExports() {
  assert.strictEqual(rs.DEFAULT_STORAGE_KEY, 'rf_recent_searches');
  assert.strictEqual(rs.DEFAULT_MAX_ENTRIES, 5);
  assert.strictEqual(typeof rs.DEFAULT_DEBOUNCE_MS, 'number');
  assert.ok(Array.isArray(rs.ROUND_TRIP_KEYS));
  assert.strictEqual(rs.ROUND_TRIP_KEYS.length > 0, true);
  assert.strictEqual(typeof rs.createView, 'function');
  assert.strictEqual(typeof rs.buildLabel, 'function');
  assert.strictEqual(typeof rs.serializeFilters, 'function');

  const src = require('fs').readFileSync(modPath, 'utf8');
  assert.ok(src.includes("root.__recentSearches = factory()"),
    'module registers window.__recentSearches when not in CommonJS context');
  assert.ok(src.includes('function (root, factory)'),
    'uses (function (root, factory) ...) wrapper');
  assert.ok(src.includes("module.exports = factory()"),
    'falls back to module.exports for Node');
  assert.ok(src.includes("typeof self !== 'undefined' ? self : this"),
    'detects browser root via self/this');
  assert.ok(src.trim().endsWith('}));'), 'IIFE is closed');
  assert.ok(src.includes("rf_recent_searches"),
    'storage key constant referenced in source');
}
testModuleExports();

// -------------------------------------------------------------------
// renderEntry() output shape
// -------------------------------------------------------------------
function testRenderEntryShape() {
  const storage = createMockStorage();
  const v = rs.createView({ storage });
  const html = v.renderEntry({
    filters: { beds_min: '2', price_max: '2500' },
    label: 'Test entry',
    savedAtMs: 1700000000000,
  }, { nowMs: 1700000005000, idx: 0 });

  assert.ok(html.includes('rs-entry'), 'has entry wrapper');
  assert.ok(html.includes('rs-label'), 'has label span');
  assert.ok(html.includes('Test entry'), 'label text rendered');
  assert.ok(html.includes('rs-ago'), 'has ago span');
  assert.ok(html.includes('rs-delete'), 'has delete button');
  assert.ok(html.includes('data-idx="0"'), 'data-idx attribute set');
}
testRenderEntryShape();

function testRenderEntryEscapesUserDerivableStrings() {
  const storage = createMockStorage();
  const v = rs.createView({ storage });
  const html = v.renderEntry({
    filters: { neighbourhood: '<script>alert(1)</script>' },
    label: '<img onerror=alert(1) src=x>',
    savedAtMs: 1000,
  }, { nowMs: 5000, idx: 0 });
  // None of these dangerous strings should appear unescaped.
  assert.ok(!html.includes('<script>alert'), 'script tag escaped');
  assert.ok(!html.includes('<img onerror'), 'img tag escaped');
  // Escaped forms ARE allowed
  assert.ok(html.includes('&lt;script&gt;'), 'has escaped script entity');
  assert.ok(html.includes('&lt;img'), 'has escaped img entity');
}
testRenderEntryEscapesUserDerivableStrings();

function testRenderEntryEmptyEntry() {
  const storage = createMockStorage();
  const v = rs.createView({ storage });
  assert.strictEqual(v.renderEntry(null), '');
  assert.strictEqual(v.renderEntry({}), '');
}
testRenderEntryEmptyEntry();

// -------------------------------------------------------------------
// listenStorage() — fires once + idempotent
// -------------------------------------------------------------------
function testListenStorage() {
  const storage = createMockStorage();
  const win = createMockWindow();
  const v = rs.createView({ storage, window: win });
  let fired = 0;
  v.listenStorage(function () { fired++; });
  // Own handler wired
  assert.ok(Array.isArray(win.handlers.storage), 'storage handler wired');
  // Fire it
  win.fireStorageEvent({ key: 'rf_recent_searches' });
  assert.strictEqual(fired, 1, 'listener fires');
  // Wrong key is ignored
  win.fireStorageEvent({ key: 'something_else' });
  assert.strictEqual(fired, 1, 'wrong key is no-op');
  // Second register does not wire a second handler
  v.listenStorage(function () {});
  assert.strictEqual(win.handlers.storage.length, 1,
    'no double-wire on subsequent listenStorage calls');
}
testListenStorage();

// -------------------------------------------------------------------
// attachPopover() — opens/closes/toggles
// -------------------------------------------------------------------
function testAttachPopoverOpenClose() {
  const storage = createMockStorage();
  const win = createMockWindow();
  const doc = createMockDocument();

  const trigger = doc._mkEl('recent_searches_btn', {
    addEventListener(ev, fn) { this._ev = this._ev || {}; this._ev[ev] = fn; },
    getBoundingClientRect: function () { return { top: 50, bottom: 80, left: 0, right: 100, width: 100, height: 30 }; },
    contains() { return false; },
  });
  const container = doc._mkEl('recent_searches_popover', {
    querySelector(sel) {
      if (sel === '.rs-close') return { addEventListener: () => {} };
      if (sel === '.rs-clear-btn') return { addEventListener: () => {} };
      return null;
    },
    querySelectorAll() { return []; },
    getBoundingClientRect: function () { return { top: 0, bottom: 80, left: 0, right: 340, width: 340, height: 240 }; },
    contains() { return false; },
    innerHTML: '',
  });
  global.document = doc;
  try {
    const v = rs.createView({ storage, window: win, document: doc });
    // Pre-populate via saveCurrent (the in-memory cache is updated too).
    v.saveCurrent({ beds_min: '2' }, { /* skip auto-label so we can assert */ });
    v.attachPopover(trigger, container);

    // Initially closed
    assert.strictEqual(container.attrs['data-state'], undefined, 'starts closed');

    // Click trigger to open
    trigger._ev.click({ preventDefault: () => {}, stopPropagation: () => {} });
    assert.strictEqual(container.attrs['data-state'], 'open', 'opens on trigger click');
    assert.ok(container.innerHTML.includes('Recent filter searches'),
      'popover header rendered');
    assert.ok(container.innerHTML.includes('2BR'),
      'entry label rendered');
    assert.ok(container.innerHTML.includes('rs-footer'),
      'footer rendered');
    assert.notStrictEqual(container.style.display, 'none', 'display cleared when open');

    // Click outside dismisses
    win.handlers.click.forEach(h => h({ target: {} }));
    assert.strictEqual(container.attrs['data-state'], 'closed', 'closes on outside click');
    assert.strictEqual(container.style.display, 'none', 'display:none when closed');

    // Open again, then Escape dismisses
    trigger._ev.click({ preventDefault: () => {}, stopPropagation: () => {} });
    assert.strictEqual(container.attrs['data-state'], 'open');
    win.handlers.keydown.forEach(h => h({ key: 'Escape' }));
    assert.strictEqual(container.attrs['data-state'], 'closed', 'closes on Escape');
  } finally {
    delete global.document;
  }
}
testAttachPopoverOpenClose();

// -------------------------------------------------------------------
// refresh() — disables trigger when empty + updates count badge
// -------------------------------------------------------------------
function testRefreshUpdatesCount() {
  const storage = createMockStorage();
  const doc = createMockDocument();
  const btn = doc._mkEl('recent_searches_btn', {
    disabled: true,
    getBoundingClientRect: function () { return { top: 50, bottom: 80, left: 0, right: 100, width: 100, height: 30 }; },
    contains() { return false; },
    addEventListener() {},
  });
  const pop = doc._mkEl('recent_searches_popover', {
    innerHTML: '',
    contains() { return false; },
  });
  doc._mkEl('recent_searches_count', { textContent: '0' });

  global.document = doc;
  try {
    const v = rs.createView({ storage, document: doc });
    v.attachPopover(btn, pop);

    // Initially disabled (count=0)
    assert.strictEqual(btn.disabled, true, 'disabled when empty');
    assert.strictEqual(btn.attrs['data-count'], '0');

    // Save two entries
    v.saveCurrent({ beds_min: '1' });
    v.saveCurrent({ beds_min: '2' });
    v.refresh();
    assert.strictEqual(btn.disabled, false, 'enabled after first save');
    assert.strictEqual(btn.attrs['data-count'], '2', 'data-count reflects list length');
  } finally {
    delete global.document;
  }
}
testRefreshUpdatesCount();

// -------------------------------------------------------------------
// restoreFromObject() — round-trips through canonical form
// -------------------------------------------------------------------
function testRestoreFromObjectCanonicalizes() {
  const storage = createMockStorage();
  const win = createMockWindow();
  const doc = createMockDocument();
  global.document = doc;
  try {
    const v = rs.createView({ storage, window: win, document: doc });
    // Pre-populate form inputs the caller's event dispatch loop will read.
    doc._mkEl('beds_min', { value: '99' });
    doc._mkEl('price_max', { value: '9999' });
    doc._mkEl('neighbourhood', { value: '' });
    let restoredFilters = null;
    v.onRestore({ apply: function (f) { restoredFilters = f; } });

    const result = v.restoreFromObject({
      beds_min: '2', price_max: '2500', bogus_key: 'ignored',
    }, { skipEvents: true });  // skip event dispatch — doc is a mock with no event ctor

    assert.strictEqual(result, true);
    assert.deepStrictEqual(restoredFilters, { beds_min: '2', price_max: '2500' });
  } finally {
    delete global.document;
  }
}
testRestoreFromObjectCanonicalizes();

function testRestoreFromObjectSkipsEmpty() {
  const storage = createMockStorage();
  const v = rs.createView({ storage });
  let called = 0;
  v.onRestore({ apply: function () { called++; } });
  const r = v.restoreFromObject({}, { skipEvents: true });
  assert.strictEqual(r, false);
  assert.strictEqual(called, 0);
}
testRestoreFromObjectSkipsEmpty();

console.log('Passed: 30 / Failed: 0 / Total: 30');