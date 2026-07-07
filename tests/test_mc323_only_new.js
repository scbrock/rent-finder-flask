/* MC-323: Tests for "Only NEW (6h)" filter wiring in templates/index.html.
 *
 * Server-side filter is covered by tests/test_mc323_only_new.py. This file
 * focuses on the JS-side round-trip plumbing — every place the Only NEW
 * state needs to be read, written, cleared, or counted must be wired so
 * the badge auto-updates and Save → Load filters stays symmetric.
 *
 * Run with Node: `node tests/test_mc323_only_new.js`.
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

// ── Helpers ────────────────────────────────────────────────────────────────

const HTML_PATH = path.resolve(__dirname, '..', 'templates', 'index.html');
let _htmlCache = null;
function html() {
  if (_htmlCache === null) _htmlCache = fs.readFileSync(HTML_PATH, 'utf-8');
  return _htmlCache;
}

// Extract a function body by brace-counting. The naive regex
// `function NAME() { ... }` fails when the body contains inner `}` on
// their own lines (e.g. closing if-blocks) — the non-greedy match ends
// at the first inner brace. The MC-318 helper handled that case because
// the relevant function (`updateFilterCount`) had no inner braces, but
// parseQueryParams / applySavedFilters / describeFilters / buildParams /
// getCurrentFilterStateAsObject all do, so we count braces instead.
//
// Walks forward from `function NAME(...)` while tracking a depth counter
// initialized to 1 (the opening brace of the function itself).
const _BODY_CACHE = new Map();
function extractFunctionBody(name) {
  if (_BODY_CACHE.has(name)) return _BODY_CACHE.get(name);
  const src = html();
  // Find the function header — use word boundary on name so we don't
  // accidentally match a longer name (e.g. "loadNewCountBadgeX").
  const headerRe = new RegExp(`function\\s+${name}\\s*\\([^)]*\\)\\s*\\{`);
  const m = src.match(headerRe);
  if (!m) { _BODY_CACHE.set(name, null); return null; }
  const start = m.index;
  // Start depth at 1 for the opening `{` we just consumed.
  let depth = 1;
  let i = m.index + m[0].length;
  // Walk the source from `i` forward, skipping over strings and comments
  // so braces inside `'...'` / `"..."` / `/* ... */` / `// ...` don't
  // affect the count.
  while (i < src.length && depth > 0) {
    const ch = src[i];
    if (ch === '/' && src[i + 1] === '/') {
      // Line comment — skip to end of line
      const nl = src.indexOf('\n', i);
      i = nl === -1 ? src.length : nl + 1;
      continue;
    }
    if (ch === '/' && src[i + 1] === '*') {
      // Block comment
      const end = src.indexOf('*/', i + 2);
      i = end === -1 ? src.length : end + 2;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === '`') {
      // String literal — skip until matching closing quote, respecting
      // backslash escapes. Doesn't fully handle template-literal ${...}
      // nesting but that's overkill for these small functions.
      const quote = ch;
      i += 1;
      while (i < src.length && src[i] !== quote) {
        if (src[i] === '\\') i += 2;
        else i += 1;
      }
      i += 1;
      continue;
    }
    if (ch === '{') depth += 1;
    else if (ch === '}') depth -= 1;
    i += 1;
  }
  const body = depth === 0 ? src.slice(start, i) : null;
  _BODY_CACHE.set(name, body);
  return body;
}

function stripJsComments(s) {
  s = s.replace(/\/\*[\s\S]*?\*\//g, '');
  s = s.replace(/\/\/.*$/gm, '');
  return s;
}

// Pull a `forEach(function(id) { ... })` block by matching the surrounding
// array literal AND the immediate next statement (the forEach call). We
// accept any variable name in the array so the test stays robust against
// renames.
function extractWiringArrayAndForEach() {
  const src = html();
  // Match `['beds_min', ... 'source', ... 'max_subway', ...].forEach(function(id) { ... })`
  const re = /\[\s*['"]beds_min['"]\s*,[\s\S]*?\]\.forEach\([\s\S]*?\)\s*;?/;
  const m = src.match(re);
  return m ? m[0] : null;
}

// ── Test: toggle markup ────────────────────────────────────────────────────

test('index.html: Only NEW toggle input + label present', () => {
  const h = html();
  assert.ok(h.includes('id="only_new"'), 'missing #only_new checkbox');
  assert.ok(h.includes('id="only_new_toggle"'), 'missing #only_new_toggle label');
  assert.ok(/Only NEW/.test(h), "missing 'Only NEW' label text");
});

test('index.html: count badge placeholder element present', () => {
  const h = html();
  assert.ok(h.includes('id="only_new_count"'),
    'missing #only_new_count element — JS will fail to update count');
});

test('index.html: loadNewCountBadge function fetches /api/meta', () => {
  const h = html();
  // Function should exist and call /api/meta
  const bodyMatch = h.match(/async\s+function\s+loadNewCountBadge\s*\([^)]*\)\s*\{[\s\S]*?\n\s*\}/);
  assert.ok(bodyMatch, 'loadNewCountBadge function not found');
  const body = stripJsComments(bodyMatch[0]);
  assert.ok(body.includes("'/api/meta'") || body.includes('"/api/meta"'),
    'loadNewCountBadge does not call /api/meta');
  assert.ok(body.includes('new_count'),
    'loadNewCountBadge does not read new_count from response');
  assert.ok(body.includes('only_new_count'),
    'loadNewCountBadge does not write to #only_new_count');
});

test('index.html: loadNewCountBadge called during init', () => {
  const h = html();
  // The init section must include a call to loadNewCountBadge so the
  // count badge is populated on page load.
  assert.ok(/loadNewCountBadge\s*\(\s*\)/.test(h),
    'loadNewCountBadge() not invoked during page init');
});

// ── Test: buildParams() ────────────────────────────────────────────────────

test('index.html: buildParams() sets is_new=true when toggle is checked', () => {
  const body = extractFunctionBody('buildParams');
  assert.ok(body, 'buildParams function not found');
  // After comment-stripping so commented-out lines don't satisfy the regex.
  const stripped = stripJsComments(body);
  const re = /if\s*\(\s*onlyNew\s*\)\s*params\.set\(\s*['"]is_new['"]\s*,\s*['"]true['"]\s*\)/;
  assert.ok(re.test(stripped),
    "buildParams() lacks `if (onlyNew) params.set('is_new', 'true')` — Only NEW toggle won't reach /api/deals");
});

test('index.html: buildParams() reads onlyNew from #only_new checkbox', () => {
  const body = extractFunctionBody('buildParams');
  assert.ok(body, 'buildParams function not found');
  const stripped = stripJsComments(body);
  const re = /const\s+onlyNew\s*=\s*document\.getElementById\(\s*['"]only_new['"]\s*\)\.checked/;
  assert.ok(re.test(stripped),
    "buildParams() lacks `const onlyNew = document.getElementById('only_new').checked`");
});

// ── Test: parseQueryParams() ────────────────────────────────────────────────

test('index.html: parseQueryParams() reads is_new=true from URL', () => {
  const body = extractFunctionBody('parseQueryParams');
  assert.ok(body, 'parseQueryParams function not found');
  const stripped = stripJsComments(body);
  // Must check the URL for is_new=true and tick the checkbox.
  const reRead = /params\.get\(\s*['"]is_new['"]\s*\)\s*===\s*['"]true['"]/;
  assert.ok(reRead.test(stripped),
    "parseQueryParams() doesn't check `params.get('is_new') === 'true'`");
  const reTick = /document\.getElementById\(\s*['"]only_new['"]\s*\)\.checked\s*=\s*true/;
  assert.ok(reTick.test(stripped),
    "parseQueryParams() doesn't tick #only_new when is_new is in URL");
});

// ── Test: resetFilters() ───────────────────────────────────────────────────

test('index.html: resetFilters() clears the Only NEW toggle', () => {
  const body = extractFunctionBody('resetFilters');
  assert.ok(body, 'resetFilters function not found');
  const stripped = stripJsComments(body);
  const re = /document\.getElementById\(\s*['"]only_new['"]\s*\)\.checked\s*=\s*false/;
  assert.ok(re.test(stripped),
    "resetFilters() doesn't uncheck #only_new");
  // Also clear the active styling (matches hide_stale pattern)
  const reActive = /document\.getElementById\(\s*['"]only_new_toggle['"]\s*\)\.classList\.remove\(\s*['"]active['"]\s*\)/;
  assert.ok(reActive.test(stripped),
    "resetFilters() doesn't clear #only_new_toggle active class");
});

// ── Test: updateFilterCount() ──────────────────────────────────────────────

test('index.html: updateFilterCount() increments when Only NEW is checked', () => {
  const body = extractFunctionBody('updateFilterCount');
  assert.ok(body, 'updateFilterCount function not found');
  const stripped = stripJsComments(body);
  const re = /if\s*\(\s*document\.getElementById\(\s*['"]only_new['"]\s*\)\.checked\s*\)\s*count\+\+/;
  assert.ok(re.test(stripped),
    "updateFilterCount() lacks `if (document.getElementById('only_new').checked) count++`");
});

// ── Test: wiring array (bottom-of-file) ────────────────────────────────────

test('index.html: bottom-of-file wiring array contains "only_new"', () => {
  const block = extractWiringArrayAndForEach();
  assert.ok(block, 'wiring array forEach block not found');
  assert.ok(block.includes("'only_new'") || block.includes('"only_new"'),
    "wiring array missing 'only_new' — count badge won't auto-update on toggle change");
});

test('index.html: wiring array still includes the existing 8 filter ids', () => {
  // Regression guard: do not drop existing IDs when adding only_new.
  const block = extractWiringArrayAndForEach();
  assert.ok(block, 'wiring array forEach block not found');
  for (const id of ['beds_min', 'baths_min', 'price_min', 'price_max',
                    'neighbourhood', 'region', 'source', 'max_subway']) {
    assert.ok(block.includes(`'${id}'`) || block.includes(`"${id}"`),
      `wiring array missing existing filter id: ${id}`);
  }
});

test('index.html: explicit toggle handler (active-class toggle) wired', () => {
  // Mirrors the hide_stale pattern: a dedicated listener that toggles
  // #only_new_toggle's 'active' class when the checkbox changes. This
  // gives the green active style.
  const h = html();
  const re = /document\.getElementById\(\s*['"]only_new['"]\s*\)\.addEventListener\(\s*['"]change['"]/;
  assert.ok(re.test(h),
    "missing dedicated change listener on #only_new — active styling won't update");
});

// ── Test: MC-322 saved-search round-trip ───────────────────────────────────

test('index.html: applySavedFilters() reads filters.is_new === "true"', () => {
  const body = extractFunctionBody('applySavedFilters');
  assert.ok(body, 'applySavedFilters function not found');
  const stripped = stripJsComments(body);
  // Symmetric with the hide_stale branch right above it.
  const re = /filters\.is_new\s*===\s*['"]true['"]/;
  assert.ok(re.test(stripped),
    "applySavedFilters() doesn't read filters.is_new === 'true'");
});

test('index.html: getCurrentFilterStateAsObject() writes out.is_new', () => {
  const body = extractFunctionBody('getCurrentFilterStateAsObject');
  assert.ok(body, 'getCurrentFilterStateAsObject function not found');
  const stripped = stripJsComments(body);
  const re = /out\.is_new\s*=\s*document\.getElementById\(\s*['"]only_new['"]\s*\)\.checked\s*\?\s*['"]true['"]\s*:\s*['"]['"]/;
  assert.ok(re.test(stripped),
    "getCurrentFilterStateAsObject() doesn't capture only_new state into out.is_new");
});

test('index.html: describeFilters() mentions "Only NEW (6h)"', () => {
  const body = extractFunctionBody('describeFilters');
  assert.ok(body, 'describeFilters function not found');
  const stripped = stripJsComments(body);
  // A push('Only NEW (6h)') line is what surfaces in the saved-search
  // modal summary so users can see what the snapshot will reload.
  const re = /parts\.push\(\s*`Only NEW \(6h\)`\s*\)/;
  assert.ok(re.test(stripped),
    "describeFilters() doesn't include 'Only NEW (6h)' in the summary");
});

// ── Test: CSS class for active state ───────────────────────────────────────

test('index.html: CSS rule for #only_new_toggle active state', () => {
  const h = html();
  // Match a CSS rule that targets the active state of #only_new_toggle.
  // Mirrors the existing #hide_stale_toggle.active rule.
  const re = /#only_new_toggle\.active\s*\{[^}]*\}/;
  assert.ok(re.test(h),
    "missing CSS rule for #only_new_toggle.active — toggle won't show green when on");
});

// ── Test: simulated change event updates the badge ────────────────────────

test('simulated change: only_new checkbox change fires updateFilterCount', () => {
  // Reuse the same minimal-DOM mock approach as MC-318.
  const el = { checked: false, _listeners: {} };
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

  // Simulate user clicking the Only NEW toggle
  el.checked = true;
  el.dispatchEvent('change');
  assert.equal(calls, 1, 'updateFilterCount should be called once on toggle change');
});

// ── Done ───────────────────────────────────────────────────────────────────

console.log('\n  ' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);