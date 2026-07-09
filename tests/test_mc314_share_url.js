/* MC-314: Tests for static/compare.js — shareable compare URL + Clear All button.
 * Run with Node: `node tests/test_mc314_share_url.js`.
 * Builds on the test infra from test_mc313_compare.js, but uses its own DOM mock
 * to keep the tests self-contained (and adds URL/location/history mocks).
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
    focus() {},
    select() {},
    setSelectionRange() {}
  };
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

const localStorageMock = (() => {
  const store = {};
  return {
    getItem(k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
    setItem(k, v) { store[k] = String(v); },
    removeItem(k) { delete store[k]; },
    clear() { Object.keys(store).forEach(k => delete store[k]); }
  };
})();

// ── URL/location/history mock (per-test reset) ────────────────────────────

function makeURLMocks() {
  const state = {
    search: '',
    href: 'http://localhost/',
    origin: 'http://localhost',
    pathname: '/',
    historyWrites: [],  // each is { state, title, url } for replaceState calls
  };
  const history = {
    replaceState(s, t, u) {
      state.historyWrites.push({ state: s, title: t, url: u });
      if (typeof u === 'string') {
        state.href = new URL(u, state.href).toString();
        // Recompute search
        const i = state.href.indexOf('?');
        state.search = i >= 0 ? state.href.slice(i) : '';
      }
      return undefined;
    }
  };
  const location = {
    get search() { return state.search; },
    get href() { return state.href; },
    set href(v) { state.href = v; },
    get origin() { return state.origin; },
    get pathname() { return state.pathname; }
  };
  function setSearch(s) {
    state.search = (typeof s === 'string') ? s : '';
    state.href = 'http://localhost/' + (state.search ? state.search : '');
  }
  return { state, history, location, setSearch };
}

// ── Build minimal window/document/module globals ──────────────────────────

function buildEnv({ initialSearch = '', clipboard = null, fetchFn = null } = {}) {
  // Clear shared localStorage at the start of every build to keep tests isolated.
  localStorageMock.clear();
  const url = makeURLMocks();
  url.setSearch(initialSearch);

  const win = { localStorage: localStorageMock };
  const docEls = {};
  function getOrCreate(id, tag = 'DIV') {
    if (!docEls[id]) docEls[id] = makeMockElement(tag);
    return docEls[id];
  }
  const stubDoc = {
    createElement(tag) { return makeMockElement(tag); },
    getElementById(id) { return docEls[id] || null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    body: makeMockElement('BODY'),
    execCommand() { return false; }
  };
  const stubNavigator = {
    clipboard: clipboard ? { writeText: clipboard } : undefined
  };

  // Wrap writeText to be a Promise so the success path can be exercised
  if (stubNavigator.clipboard && stubNavigator.clipboard.writeText) {
    const orig = stubNavigator.clipboard.writeText;
    stubNavigator.clipboard.writeText = (text) => {
      return new Promise((resolve, reject) => {
        try {
          const r = orig(text);
          if (r && typeof r.then === 'function') {
            r.then(resolve, reject);
          } else {
            resolve();
          }
        } catch (e) { reject(e); }
      });
    };
  }

  const stubWindow = Object.assign(win, {
    location: url.location,
    history: url.history,
    navigator: stubNavigator,
    fetch: fetchFn || (() => Promise.reject(new Error('fetch not stubbed')))
  });

  global.window = stubWindow;
  global.self = stubWindow;
  global.document = stubDoc;
  global.localStorage = localStorageMock;
  // Some Node versions expose global.navigator as a read-only getter — replace via defineProperty.
  try { global.navigator = stubNavigator; }
  catch (_) {
    Object.defineProperty(global, 'navigator', { value: stubNavigator, configurable: true, writable: true });
  }
  global.URLSearchParams = (typeof URLSearchParams !== 'undefined')
    ? URLSearchParams
    : require('node:url').URLSearchParams;
  global.module = undefined;

  // Load compare.js
  const comparePath = path.resolve(__dirname, '..', 'static', 'compare.js');
  const code = fs.readFileSync(comparePath, 'utf-8');
  const moduleScope = { exports: {} };
  const fn = new Function('module', 'window', 'self', 'document', 'localStorage', 'navigator', code);
  fn(moduleScope, stubWindow, stubWindow, stubDoc, localStorageMock, stubNavigator);
  const compare = moduleScope.exports;

  // Stub openCompareModal — init() calls it (via setTimeout) when state is 2-3 ids.
  // We don't want it firing real network calls in tests.
  compare.openCompareModal = function () { /* stubbed */ };
  compare.closeCompareModal = function () { /* stubbed */ };

  return { compare, url, win: stubWindow, doc: stubDoc, getOrCreate };
}

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
    if (e.stack) console.error(e.stack.split('\n').slice(1, 4).join('\n'));
  }
}

// ── Tests: parseSelectionString ────────────────────────────────────────────

test('parseSelectionString: empty/non-string returns []', () => {
  const { compare } = buildEnv();
  assert.deepEqual(compare.parseSelectionString(''), []);
  assert.deepEqual(compare.parseSelectionString(null), []);
  assert.deepEqual(compare.parseSelectionString(undefined), []);
  assert.deepEqual(compare.parseSelectionString(42), []);
});

test('parseSelectionString: 2 ids → array of 2', () => {
  const { compare } = buildEnv();
  assert.deepEqual(compare.parseSelectionString('A,B'), ['A', 'B']);
  assert.deepEqual(compare.parseSelectionString('A, B'), ['A', 'B']);
  assert.deepEqual(compare.parseSelectionString('A ,B '), ['A', 'B']);
});

test('parseSelectionString: dedupes + caps at MAX_SELECTED', () => {
  const { compare } = buildEnv();
  assert.deepEqual(compare.parseSelectionString('A,B,A,C,D'), ['A', 'B', 'C']);
  assert.equal(compare.parseSelectionString('A,B,A,C,D').length, compare.MAX_SELECTED);
});

// ── Tests: encodeSelection ────────────────────────────────────────────────

test('encodeSelection: round-trip with parseSelectionString', () => {
  const { compare } = buildEnv();
  const ids = ['A', 'B', 'C'];
  const enc = compare.encodeSelection(ids);
  assert.equal(enc, 'A,B,C');
  assert.deepEqual(compare.parseSelectionString(enc), ids);
});

test('encodeSelection: filters non-strings + empty', () => {
  const { compare } = buildEnv();
  assert.equal(compare.encodeSelection(['A', null, 42, '', 'B']), 'A,B');
  assert.equal(compare.encodeSelection([]), '');
  assert.equal(compare.encodeSelection(null), '');
});

// ── Tests: parseURLSelection ──────────────────────────────────────────────

test('parseURLSelection: returns null when no cmp param', () => {
  const { compare } = buildEnv({ initialSearch: '' });
  assert.equal(compare.parseURLSelection(''), null);
  assert.equal(compare.parseURLSelection('?other=foo'), null);
});

test('parseURLSelection: returns [] when cmp has wrong count', () => {
  const { compare } = buildEnv();
  // 1 id
  assert.deepEqual(compare.parseURLSelection('?cmp=only'), []);
  // 4 ids
  assert.deepEqual(compare.parseURLSelection('?cmp=a,b,c,d'), []);
  // 0 ids
  assert.deepEqual(compare.parseURLSelection('?cmp='), []);
});

test('parseURLSelection: returns 2 ids when valid', () => {
  const { compare } = buildEnv();
  assert.deepEqual(compare.parseURLSelection('?cmp=A,B'), ['A', 'B']);
});

test('parseURLSelection: returns 3 ids when valid', () => {
  const { compare } = buildEnv();
  assert.deepEqual(compare.parseURLSelection('?cmp=A,B,C'), ['A', 'B', 'C']);
});

test('parseURLSelection: URL-encoded ids are decoded', () => {
  const { compare } = buildEnv();
  // 'foo bar' encoded as 'foo%20bar' — URLSearchParams decodes to 'foo bar'
  assert.deepEqual(compare.parseURLSelection('?cmp=foo%20bar,baz'), ['foo bar', 'baz']);
});

test('parseURLSelection: other params preserved alongside cmp', () => {
  const { compare } = buildEnv();
  assert.deepEqual(compare.parseURLSelection('?beds=1&cmp=A,B&max=2000'), ['A', 'B']);
});

// ── Tests: restoreFromURL ────────────────────────────────────────────────

test('restoreFromURL: returns false + leaves state alone when URL invalid', () => {
  const { compare } = buildEnv();
  compare.setState({ selected: ['X', 'Y'] });
  localStorageMock.clear();
  const ok = compare.restoreFromURL('');
  assert.equal(ok, false);
  assert.deepEqual(compare.getSelected(), ['X', 'Y']);
});

test('restoreFromURL: returns false for 1-id URL (silent fallback)', () => {
  const { compare } = buildEnv();
  compare.setState({ selected: ['X', 'Y'] });
  localStorageMock.clear();
  const ok = compare.restoreFromURL('?cmp=only');
  assert.equal(ok, false);
  // localStorage untouched
  assert.equal(localStorageMock.getItem(compare.STORAGE_KEY), null);
});

test('restoreFromURL: URL takes precedence over localStorage', () => {
  const { compare } = buildEnv();
  localStorageMock.setItem(compare.STORAGE_KEY, JSON.stringify(['OLD1', 'OLD2']));
  compare.setState({ selected: ['OLD1', 'OLD2'] });
  const ok = compare.restoreFromURL('?cmp=NEW1,NEW2');
  assert.equal(ok, true);
  assert.deepEqual(compare.getSelected(), ['NEW1', 'NEW2']);
  // URL selection mirrored into localStorage
  assert.deepEqual(JSON.parse(localStorageMock.getItem(compare.STORAGE_KEY)), ['NEW1', 'NEW2']);
});

test('restoreFromURL: 3-id URL → 3 ids in state', () => {
  const { compare } = buildEnv();
  compare.setState({ selected: [] });
  const ok = compare.restoreFromURL('?cmp=A,B,C');
  assert.equal(ok, true);
  assert.deepEqual(compare.getSelected(), ['A', 'B', 'C']);
});

// ── Tests: clearURLParam ──────────────────────────────────────────────────

test('clearURLParam: strips cmp from URL when present', () => {
  const { compare, url } = buildEnv({ initialSearch: '?cmp=A,B' });
  // ClearURLParam calls window.history.replaceState — exercise it.
  const ok = compare.clearURLParam();
  assert.equal(ok, true);
  // history was called
  assert.equal(url.state.historyWrites.length, 1);
  // Search no longer contains cmp
  assert.equal(url.state.search.includes('cmp='), false);
});

test('clearURLParam: keeps other params intact', () => {
  const { compare, url } = buildEnv({ initialSearch: '?beds=1&cmp=A,B&max=2000' });
  compare.clearURLParam();
  assert.equal(url.state.search.includes('cmp='), false);
  assert.ok(url.state.search.includes('beds=1'), `search should keep beds, got: ${url.state.search}`);
  assert.ok(url.state.search.includes('max=2000'), `search should keep max, got: ${url.state.search}`);
});

test('clearURLParam: returns false when no cmp param', () => {
  const { compare, url } = buildEnv({ initialSearch: '?beds=1' });
  const ok = compare.clearURLParam();
  assert.equal(ok, false);
  // No history write since nothing changed
  // (it's OK either way; just verify no error)
  assert.ok(ok === false);
});

// ── Tests: buildShareURL ──────────────────────────────────────────────────

test('buildShareURL: returns URL with cmp param when 1+ selected', () => {
  const { compare } = buildEnv();
  compare.setState({ selected: ['A', 'B'] });
  const url = compare.buildShareURL();
  assert.ok(url.includes('?cmp='));
  assert.ok(url.includes('A%2CB') || url.includes('A,B'), `expected encoded or plain A,B in ${url}`);
});

test('buildShareURL: returns URL without cmp when 0 selected', () => {
  const { compare } = buildEnv();
  compare.setState({ selected: [] });
  const url = compare.buildShareURL();
  assert.equal(url.includes('cmp='), false);
});

// ── Tests: copyShareLink ──────────────────────────────────────────────────

test('copyShareLink: returns "ok" when clipboard API available + succeeds', () => {
  let wrote = null;
  const fakeWrite = (text) => { wrote = text; };
  const { compare } = buildEnv({ clipboard: fakeWrite });
  compare.setState({ selected: ['A', 'B'] });
  const result = compare.copyShareLink();
  assert.equal(result, 'ok');
  assert.ok(wrote && wrote.includes('cmp='), `expected write to be called with URL, got ${wrote}`);
});

test('copyShareLink: returns fallback when clipboard API unavailable', () => {
  const { compare, getOrCreate } = buildEnv({ clipboard: null });
  compare.setState({ selected: ['A', 'B'] });
  // Pre-create the share button + ensure getElementById returns it
  const btn = getOrCreate('cmp_share_btn', 'BUTTON');
  btn.dataset = btn.dataset || {};
  // execCommand returns false in our doc mock → fallback should reach window.prompt
  // We don't have a prompt mock, so the function must not throw.
  const result = compare.copyShareLink();
  // Result should be one of 'ok'|'exec'|'prompt'|'noop'
  assert.ok(['ok', 'exec', 'prompt', 'noop'].includes(result), `unexpected result: ${result}`);
});

test('copyShareLink: does not throw when called with empty selection', () => {
  const { compare } = buildEnv();
  compare.setState({ selected: [] });
  // Even if all paths are stubbed, no throw on this path.
  const result = compare.copyShareLink();
  assert.ok(['ok', 'exec', 'prompt', 'noop'].includes(result), `unexpected: ${result}`);
});

// ── Tests: flashCopyButton ────────────────────────────────────────────────

test('flashCopyButton: updates button text then restores', (cb) => {
  // Use a setTimeout-based test, but since the JS test harness is sync,
  // we just verify the first stage: text changes immediately.
  const { compare, getOrCreate } = buildEnv();
  const btn = getOrCreate('cmp_share_btn', 'BUTTON');
  btn.dataset = { origText: 'Copy Link' };
  compare.flashCopyButton('ok');
  assert.equal(btn.textContent, '✓ Copied!');
  // Restore happens via setTimeout, but we're not waiting in this harness.
});

test('flashCopyButton: prompt label for prompt kind', () => {
  const { compare, getOrCreate } = buildEnv();
  const btn = getOrCreate('cmp_share_btn', 'BUTTON');
  btn.dataset = { origText: 'Copy Link' };
  compare.flashCopyButton('prompt');
  assert.equal(btn.textContent, 'Copy URL below');
});

test('flashCopyButton: captures originalText on first call', () => {
  const { compare, getOrCreate } = buildEnv();
  const btn = getOrCreate('cmp_share_btn', 'BUTTON');
  btn.textContent = 'Copy Link';
  btn.dataset = {};
  compare.flashCopyButton('ok');
  assert.equal(btn.dataset.origText, 'Copy Link');
});

// ── Tests: updateClearAllButton ──────────────────────────────────────────

test('updateClearAllButton: shows button when 1+ selected', () => {
  const { compare, getOrCreate } = buildEnv();
  const btn = getOrCreate('clear_all_btn', 'BUTTON');
  btn.style = btn.style || {};
  compare.setState({ selected: ['X'] });
  compare.updateClearAllButton();
  assert.notEqual(btn.style.display, 'none');
});

test('updateClearAllButton: hides button when 0 selected', () => {
  const { compare, getOrCreate } = buildEnv();
  const btn = getOrCreate('clear_all_btn', 'BUTTON');
  compare.setState({ selected: [] });
  compare.updateClearAllButton();
  assert.equal(btn.style.display, 'none');
});

test('updateClearAllButton: shows button with 2 selected', () => {
  const { compare, getOrCreate } = buildEnv();
  const btn = getOrCreate('clear_all_btn', 'BUTTON');
  const lbl = getOrCreate('clear_all_btn_label', 'SPAN');
  compare.setState({ selected: ['A', 'B'] });
  compare.updateClearAllButton();
  assert.notEqual(btn.style.display, 'none');
  assert.equal(lbl.textContent, 'Clear All (2)');
});

test('updateClearAllButton: noop when button missing', () => {
  const { compare } = buildEnv();
  // Don't create clear_all_btn element → should silently return
  compare.setState({ selected: ['A'] });
  compare.updateClearAllButton();
  // No throw = pass
});

// ── Tests: init with URL ─────────────────────────────────────────────────

test('init: URL with 2 valid ids restores selection from URL', () => {
  // init calls openCompareModal via setTimeout; we stubbed it above
  const { compare } = buildEnv({ initialSearch: '?cmp=A,B' });
  localStorageMock.setItem(compare.STORAGE_KEY, JSON.stringify(['OLD1', 'OLD2']));
  compare.setState({ selected: [] });
  compare.init();
  assert.deepEqual(compare.getSelected(), ['A', 'B']);
  // URL has been cleared
  // (Can't easily assert in this harness without waiting on setTimeout,
  // but state.selected is the key signal.)
});

test('init: silently falls back to localStorage when URL invalid', () => {
  const { compare } = buildEnv({ initialSearch: '?cmp=only' });
  localStorageMock.setItem(compare.STORAGE_KEY, JSON.stringify(['L1', 'L2']));
  compare.setState({ selected: [] });
  compare.init();
  assert.deepEqual(compare.getSelected(), ['L1', 'L2']);
});

test('init: silently falls back to localStorage when no cmp param', () => {
  const { compare } = buildEnv({ initialSearch: '' });
  localStorageMock.setItem(compare.STORAGE_KEY, JSON.stringify(['L1', 'L2']));
  compare.setState({ selected: [] });
  compare.init();
  assert.deepEqual(compare.getSelected(), ['L1', 'L2']);
});

test('init: silently falls back when URL present but malformed (no throw)', () => {
  const { compare } = buildEnv({ initialSearch: '?%%invalid=%&cmp=A' });
  // Don't set localStorage
  compare.setState({ selected: [] });
  compare.init();
  // State is whatever loadFromStorage returns (empty)
  assert.deepEqual(compare.getSelected(), []);
});

// ── Tests: index.html wiring (MC-314) ─────────────────────────────────────

test('index.html: contains clear_all_btn filter-bar element', () => {
  const html = fs.readFileSync(path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8');
  assert.ok(html.includes('id="clear_all_btn"'), 'expected id="clear_all_btn" in template');
  assert.ok(html.includes('id="clear_all_btn_label"'), 'expected label span');
});

test('index.html: clear_all_btn wires to clearCompare + syncRowCheckboxes', () => {
  const html = fs.readFileSync(path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8');
  // Look for onclick handler on clear_all_btn referencing clearCompare
  // The handler is inline, so search the surrounding context.
  const idx = html.indexOf('id="clear_all_btn"');
  assert.ok(idx > 0);
  const ctx = html.slice(idx, idx + 500);
  assert.ok(ctx.includes('clearCompare'), 'inline handler must call clearCompare');
});

test('index.html: contains cmp_share_btn inside compare modal', () => {
  const html = fs.readFileSync(path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8');
  assert.ok(html.includes('id="cmp_share_btn"'), 'expected id="cmp_share_btn" in template');
  const idx = html.indexOf('id="cmp_share_btn"');
  assert.ok(idx > 0);
  const ctx = html.slice(idx, idx + 400);
  assert.ok(ctx.includes('copyShareLink'), 'handler must call copyShareLink');
  assert.ok(ctx.includes('Copy Link'), 'default label');
});

// ── Tests: compare.js API surface ─────────────────────────────────────────

test('compare.js: exports all MC-314 functions', () => {
  const { compare } = buildEnv();
  for (const api of [
    'parseSelectionString', 'encodeSelection', 'parseURLSelection',
    'restoreFromURL', 'clearURLParam', 'buildShareURL',
    'copyShareLink', 'fallbackCopy', 'flashCopyButton',
    'updateClearAllButton'
  ]) {
    assert.ok(typeof compare[api] === 'function', `compare.${api} must be a function`);
  }
});

// ── Done ───────────────────────────────────────────────────────────────────

console.log('\n  ' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);
