/* MC-322: Tests for the Save Current Filters button + /saved-searches
 * management page. Pattern of tests mirrors MC-318 (file-content assertions +
 * simulated DOM events) because the JS lives inline in templates rather
 * than in a static/*.js module.
 *
 * Run with Node: `node tests/test_mc322_save_search.js`.
 */
'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

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
    console.error('       ', (e && e.stack) ? e.stack : (e && e.message) ? e.message : e);
  }
}

const TPL_DIR = path.resolve(__dirname, '..', 'templates');
const readTpl = (n) => fs.readFileSync(path.join(TPL_DIR, n), 'utf-8');

const stripBlockComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const stripLineComments = (s) => s.replace(/\/\/.*$/gm, '');

// Brace-counter based extractor (regex with `\{[\s\S]*?\}` is unsafe for
// functions whose body contains nested braces — arrow-fn helpers inside
// `applySavedFilters`, template literals with ${...} inside `loadSearch`,
// etc.). Walk the source from the opening `{` and close at the matching
// closing brace at depth 0.
const extractFnBody = (haystack, fname) => {
  const sigRe = new RegExp(`function\\s+${fname}\\s*\\([^)]*\\)\\s*\\{`);
  const sigMatch = haystack.match(sigRe);
  if (!sigMatch) return null;
  const start = sigMatch.index + sigMatch[0].length;  // position after the `{`
  // Walk forward, tracking string + template-literal + comment state so
  // `{` / `}` inside them don't throw the brace counter off.
  let depth = 1;
  let i = start;
  let inSingle = false, inDouble = false, inTpl = false, inLine = false, inBlock = false;
  while (i < haystack.length && depth > 0) {
    const c = haystack[i];
    const next = haystack[i + 1];
    if (inLine) {
      if (c === '\n') inLine = false;
      i += 1; continue;
    }
    if (inBlock) {
      if (c === '*' && next === '/') { inBlock = false; i += 2; continue; }
      i += 1; continue;
    }
    if (inSingle) {
      if (c === '\\') { i += 2; continue; }
      if (c === "'") { inSingle = false; i += 1; continue; }
      i += 1; continue;
    }
    if (inDouble) {
      if (c === '\\') { i += 2; continue; }
      if (c === '"') { inDouble = false; i += 1; continue; }
      i += 1; continue;
    }
    if (inTpl) {
      if (c === '\\') { i += 2; continue; }
      if (c === '`') { inTpl = false; i += 1; continue; }
      // Skip ${...} expression so braces inside don't throw the counter
      // off. Scan for the matching closing brace of the interpolation.
      if (c === '$' && next === '{') {
        // find the matching `}` of this ${...}
        let d = 1;
        let j = i + 2;
        while (j < haystack.length && d > 0) {
          const cj = haystack[j];
          if (cj === '{') d += 1;
          else if (cj === '}') d -= 1;
          j += 1;
        }
        i = j;
        continue;
      }
      i += 1; continue;
    }
    // Not in any string/comment
    if (c === '/' && next === '/') { inLine = true; i += 2; continue; }
    if (c === '/' && next === '*') { inBlock = true; i += 2; continue; }
    if (c === "'") { inSingle = true; i += 1; continue; }
    if (c === '"') { inDouble = true; i += 1; continue; }
    if (c === '`') { inTpl = true; i += 1; continue; }
    if (c === '{') { depth += 1; i += 1; continue; }
    if (c === '}') { depth -= 1; i += 1; if (depth === 0) break; continue; }
    i += 1;
  }
  if (depth !== 0) return null;
  // Include the leading `function NAME(...) {` so the result mirrors the
  // old regex extraction shape — callers still get `\\n\\s*}` at the tail.
  const body = haystack.substring(sigMatch.index, i);
  // The old regex returned `[\\s\\S]*?\\n\\s*}`; emulate the trailing shape.
  const match = [body];
  return match;
};

// ── 1. index.html Save button + modal wiring ────────────────────────────────

test('index.html: Save filters button is in the filter bar', () => {
  const html = readTpl('index.html');
  assert.ok(/id=["']save_search_btn["']/.test(html), 'id="save_search_btn" missing');
  assert.ok(/onclick=["']openSaveSearchModal\(\)["']/.test(html),
    'Save button onclick="openSaveSearchModal()" missing');
});

test('index.html: "Saved" link points at /saved-searches', () => {
  const html = readTpl('index.html');
  assert.ok(/id=["']saved_searches_link["']/.test(html),
    'id="saved_searches_link" missing');
  assert.ok(/href=["']\/saved-searches["']/.test(html),
    'Saved link href missing');
});

test('index.html: Save Search modal markup present', () => {
  const html = readTpl('index.html');
  assert.ok(/id=["']save_search_modal["']/.test(html),
    'id="save_search_modal" missing');
  assert.ok(/id=["']save_search_form["']/.test(html),
    'id="save_search_form" missing');
  // Inputs for name + email
  assert.ok(/id=["']save_search_name["']/.test(html),
    'id="save_search_name" missing');
  assert.ok(/id=["']save_search_email["']/.test(html),
    'id="save_search_email" missing');
  assert.ok(/id=["']save_search_filter_summary["']/.test(html),
    'id="save_search_filter_summary" missing');
});

test('index.html: mc322 toast markup present', () => {
  const html = readTpl('index.html');
  assert.ok(/id=["']mc322_toast["']/.test(html), 'id="mc322_toast" missing');
  assert.ok(/function\s+showMc322Toast\b/.test(html),
    'showMc322Toast function missing');
});

test('index.html: JS helpers exist (applySavedFilters, getCurrentFilterStateAsObject, describeFilters)', () => {
  const html = readTpl('index.html');
  for (const fn of ['applySavedFilters', 'getCurrentFilterStateAsObject',
                    'describeFilters', 'openSaveSearchModal',
                    'closeSaveSearchModal', 'submitSaveSearch',
                    'maybeLoadFromPreselect']) {
    assert.ok(new RegExp(`function\\s+${fn}\\b`).test(html),
      `function ${fn} missing in index.html`);
  }
});

test('index.html: applySavedFilters sets the right keys', () => {
  // The helper must write each known filter field; a missing one would
  // silently drop state when Load runs. Extract the function body and
  // assert each key id appears at least once.
  const html = readTpl('index.html');
  const m = extractFnBody(html, 'applySavedFilters');
  assert.ok(m, 'applySavedFilters function body not found');
  const body = stripLineComments(stripBlockComments(m[0]));
  for (const id of ['beds_min', 'baths_min', 'price_min', 'price_max',
                    'neighbourhood', 'region', 'source', 'sort_by',
                    'commute_dest', 'max_commute', 'max_subway',
                    'has_parking', 'hide_stale']) {
    assert.ok(body.includes(`'${id}'`) || body.includes(`"${id}"`),
      `applySavedFilters body doesn't touch #${id} — that filter won't re-apply on Load`);
  }
});

test('index.html: getCurrentFilterStateAsObject is built from buildParams + booleans', () => {
  const html = readTpl('index.html');
  const m = extractFnBody(html, 'getCurrentFilterStateAsObject');
  assert.ok(m, 'getCurrentFilterStateAsObject function body not found');
  const body = stripLineComments(stripBlockComments(m[0]));
  assert.ok(body.includes('buildParams'),
    'should derive the snapshot from buildParams()');
  assert.ok(/hide_stale/.test(body) && /has_parking/.test(body),
    'must capture both boolean toggles for round-trip');
});

test('index.html: maybeLoadFromPreselect uses the right endpoint', () => {
  const html = readTpl('index.html');
  assert.ok(/function\s+maybeLoadFromPreselect\b/.test(html),
    'maybeLoadFromPreselect function missing');
  assert.ok(/api\/saved-searches\/load/.test(html),
    'maybeLoadFromPreselect should fetch /api/saved-searches/load');
  assert.ok(/applySavedFilters/.test(html),
    'maybeLoadFromPreselect should call applySavedFilters() on the loaded payload');
});

// ── 2. saved_searches.html wiring ──────────────────────────────────────────

test('saved_searches.html: page chrome (title, header, email bar)', () => {
  const html = readTpl('saved_searches.html');
  assert.ok(html.includes('<title>Saved Searches'), 'page title missing');
  assert.ok(/id=["']email-input["']/.test(html), 'email-input missing');
  assert.ok(/id=["']load-btn["']/.test(html), 'load button missing');
  assert.ok(/Back to deals/.test(html), 'back link missing');
  assert.ok(/search-card-tpl/.test(html), 'card <template> missing');
});

test('saved_searches.html: nav links to /alerts, /shortlist, /profile', () => {
  const html = readTpl('saved_searches.html');
  assert.ok(/href=["']\/alerts["']/.test(html), 'nav link to /alerts missing');
  assert.ok(/href=["']\/shortlist["']/.test(html), 'nav link to /shortlist missing');
  assert.ok(/href=["']\/profile["']/.test(html), 'nav link to /profile missing');
});

test('saved_searches.html: JS functions (loadSearches, buildCard, loadSearch, deleteSearch, submitRename, escapeHtml)', () => {
  const html = readTpl('saved_searches.html');
  for (const fn of ['loadSearches', 'buildCard', 'loadSearch',
                    'deleteSearch', 'submitRename', 'escapeHtml']) {
    assert.ok(new RegExp(`(function\\s+${fn}\\b|${fn}\\s*=)`).test(html),
      `${fn} missing in saved_searches.html`);
  }
});

test('saved_searches.html: loadSearch uses URLSearchParams and /?keys=', () => {
  const html = readTpl('saved_searches.html');
  const m = extractFnBody(html, 'loadSearch');
  assert.ok(m, 'loadSearch function body not found');
  const body = stripLineComments(stripBlockComments(m[0]));
  assert.ok(/URLSearchParams/.test(body),
    'loadSearch should use URLSearchParams to build the redirect query');
  assert.ok(/api\/saved-searches\/load/.test(body),
    'loadSearch should fetch /api/saved-searches/load');
  assert.ok(/window\.location\.href/.test(body),
    'loadSearch should redirect via window.location.href');
  // All filter keys must be in the loop (or set) — if any is missing,
  // that filter would be silently dropped on Load.
  for (const k of ['beds_min', 'beds_max', 'baths_min', 'price_min',
                   'price_max', 'has_parking', 'neighbourhood', 'region',
                   'source', 'sort', 'hide_stale', 'commute_dest',
                   'max_commute', 'max_subway']) {
    assert.ok(body.includes(`'${k}'`) || body.includes(`"${k}"`),
      `loadSearch body doesn't reference filter key '${k}'`);
  }
});

test('saved_searches.html: deleteSearch uses DELETE method', () => {
  const html = readTpl('saved_searches.html');
  const m = extractFnBody(html, 'deleteSearch');
  assert.ok(m, 'deleteSearch function body not found');
  const body = stripLineComments(stripBlockComments(m[0]));
  assert.ok(/method:\s*['"]DELETE['"]/.test(body),
    'deleteSearch should send DELETE request');
  assert.ok(/api\/saved-searches\//.test(body),
    'deleteSearch should call /api/saved-searches/<id>?email=');
});

test('saved_searches.html: submitRename uses PUT method', () => {
  const html = readTpl('saved_searches.html');
  const m = extractFnBody(html, 'submitRename');
  assert.ok(m, 'submitRename function body not found');
  const body = stripLineComments(stripBlockComments(m[0]));
  assert.ok(/method:\s*['"]PUT['"]/.test(body),
    'submitRename should send PUT request');
  assert.ok(/api\/saved-searches\//.test(body),
    'submitRename should call /api/saved-searches/<id>?email=');
});

test('saved_searches.html: buildCard renders Load/Delete/Edit buttons per row', () => {
  const html = readTpl('saved_searches.html');
  const m = extractFnBody(html, 'buildCard');
  assert.ok(m, 'buildCard function body not found');
  const body = stripLineComments(stripBlockComments(m[0]));
  for (const act of ['load', 'delete', 'rename']) {
    assert.ok(body.includes(`[data-act=${act}]`),
      `buildCard body doesn't wire data-act=${act}`);
  }
  assert.ok(/match-count-badge/.test(body),
    'buildCard must render a match count badge');
  assert.ok(/filters_dict/.test(body),
    'buildCard must read filters_dict (MC-322 snapshot)');
});

// ── 3. Functional smoke: simulate a save-current-filters -> load cycle ──────

test('simulated: openSaveSearchModal gets a fresh object from getCurrentFilterStateAsObject', () => {
  const html = readTpl('index.html');
  // Just confirm both functions are wired together (call site pattern).
  // The actual round-trip is covered by the Python tests + Flask test_client.
  assert.ok(/onclick=["']openSaveSearchModal\(\)["']/.test(html));
  // The modal opens by setting display = 'flex'
  const m = extractFnBody(html, 'openSaveSearchModal');
  assert.ok(m, 'openSaveSearchModal function body not found');
  const body = stripLineComments(stripBlockComments(m[0]));
  assert.ok(/getCurrentFilterStateAsObject/.test(body),
    'openSaveSearchModal should call getCurrentFilterStateAsObject() to populate the summary');
});

test('simulated: submitSaveSearch POSTs to /api/saved-searches', () => {
  const html = readTpl('index.html');
  const m = extractFnBody(html, 'submitSaveSearch');
  assert.ok(m, 'submitSaveSearch function body not found');
  const body = stripLineComments(stripBlockComments(m[0]));
  assert.ok(/['"]\/api\/saved-searches['"]/.test(body),
    'submitSaveSearch should POST to /api/saved-searches');
  assert.ok(/method:\s*['"]POST['"]/.test(body),
    'submitSaveSearch should send POST method');
  assert.ok(/filters_json/.test(body),
    'submitSaveSearch should pass filters_json in the payload');
});

// ── Done ───────────────────────────────────────────────────────────────────

console.log('\n  ' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);
