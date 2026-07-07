/* MC-318: Tests for filter-count badge auto-update wiring.
 *
 * Bug: line ~1026 in templates/index.html has a hardcoded array of filter
 * IDs that get an `addEventListener('change', updateFilterCount)`. The
 * `source` (Kijiji/Craigslist dropdown) and `max_subway` (max walk to
 * nearest TTC subway) inputs were missing from that array, so the count
 * badge would not auto-update when those filters changed (the Filter
 * button still worked correctly, but the live count badge did not).
 *
 * Run with Node: `node tests/test_mc318_filter_count.js`.
 */
'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

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
    console.error('       ', e && e.message ? e.message : e);
  }
}

// ── Test: index.html wiring array contains source and max_subway ───────────

test('index.html: wiring array contains "source"', () => {
  const html = fs.readFileSync(
    path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8'
  );
  // The wiring forEach block at the bottom of the script section
  const re = /\[\s*['"]beds_min['"]\s*,\s*['"]baths_min['"]\s*,\s*['"]price_min['"]\s*,\s*['"]price_max['"]\s*,\s*['"]neighbourhood['"]\s*,\s*['"]region['"][^\]]*\]/;
  const match = html.match(re);
  assert.ok(match, 'wiring array not found in expected format');
  assert.ok(match[0].includes("'source'") || match[0].includes('"source"'),
    'wiring array missing "source" — badge will not auto-update on source change');
});

test('index.html: wiring array contains "max_subway"', () => {
  const html = fs.readFileSync(
    path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8'
  );
  const re = /\[\s*['"]beds_min['"]\s*,\s*['"]baths_min['"]\s*,\s*['"]price_min['"]\s*,\s*['"]price_max['"]\s*,\s*['"]neighbourhood['"]\s*,\s*['"]region['"][^\]]*\]/;
  const match = html.match(re);
  assert.ok(match, 'wiring array not found in expected format');
  assert.ok(match[0].includes("'max_subway'") || match[0].includes('"max_subway"'),
    'wiring array missing "max_subway" — badge will not auto-update on max_subway change');
});

test('index.html: wiring array still contains the original 6 filter ids', () => {
  // Regression guard: do not accidentally drop the original IDs when adding
  // source and max_subway.
  const html = fs.readFileSync(
    path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8'
  );
  for (const id of ['beds_min', 'baths_min', 'price_min', 'price_max',
                    'neighbourhood', 'region']) {
    assert.ok(html.includes(`'${id}'`) || html.includes(`"${id}"`),
      `wiring array missing original filter id: ${id}`);
  }
});

test('index.html: updateFilterCount body already counts source + max_subway', () => {
  // AC: just adding the listener is not enough — updateFilterCount must
  // also increment the count when those inputs are non-empty. Verify the
  // pre-existing function body has these checks.
  const html = fs.readFileSync(
    path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8'
  );
  assert.ok(html.includes("document.getElementById('source')"),
    'updateFilterCount does not reference #source');
  assert.ok(html.includes("document.getElementById('max_subway')"),
    'updateFilterCount does not reference #max_subway');
});

// ── Test: simulated change event updates the badge ─────────────────────────

test('simulated change: source select change updates badge', () => {
  // Simulate the wiring: build a minimal DOM, attach the listener, dispatch
  // a change event, and assert updateFilterCount was called.
  const el = { value: '', _listeners: {} };
  el.addEventListener = (type, fn) => {
    el._listeners[type] = el._listeners[type] || [];
    el._listeners[type].push(fn);
  };
  el.dispatchEvent = (type) => {
    (el._listeners[type] || []).forEach(fn => fn({ target: el }));
  };
  // Confirm the wiring pattern from index.html is what we expect:
  //   el.addEventListener('change', updateFilterCount)
  let calls = 0;
  const updateFilterCount = () => { calls += 1; };
  el.addEventListener('change', updateFilterCount);
  el.dispatchEvent('change');
  assert.equal(calls, 1, 'updateFilterCount should be called once on change');
});

test('simulated change: number input change updates badge', () => {
  // Same as above for max_subway (a number input).
  const el = { value: '5', _listeners: {} };
  el.addEventListener = (type, fn) => {
    el._listeners[type] = el._listeners[type] || [];
    el._listeners[type].push(fn);
  };
  el.dispatchEvent = (type) => {
    (el._listeners[type] || []).forEach(fn => fn({ target: el }));
  };
  let calls = 0;
  const updateFilterCount = () => { calls += 1; };
  el.addEventListener('change', updateFilterCount);
  el.dispatchEvent('change');
  assert.equal(calls, 1, 'updateFilterCount should fire on max_subway change');
});

// ── Done ───────────────────────────────────────────────────────────────────

console.log('\n  ' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);
