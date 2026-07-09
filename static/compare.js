/* MC-313 + MC-314: Side-by-side deal comparison + shareable compare URL.
 *
 * Public API (also exposed via window.__compare and module.exports for Node tests):
 *   addToCompare(listingId)           — toggle-on (add + persist)
 *   removeFromCompare(listingId)      — toggle-off (remove + persist)
 *   toggleCompare(listingId)          — flip selection
 *   clearCompare()                    — wipe all selected + persist
 *   getSelected()                     — returns string[] of listing_ids in selection order
 *   isSelected(listingId)             — boolean
 *   updateCompareBadge()              — refresh the "Compare N" button label/visibility
 *   updateClearAllButton()            — MC-314: refresh the filter-bar Clear All button visibility
 *   openCompareModal()                — fetch /api/compare + render modal
 *   closeCompareModal()               — hide modal
 *   renderCompareRows(payload)        — pure render fn for testability
 *   parseURLSelection(searchString)   — MC-314: parse ?cmp=<ids> query param
 *   encodeSelection(ids)              — MC-314: encode ids for ?cmp= URL param
 *   buildShareURL()                   — MC-314: build full shareable URL
 *   restoreFromURL(searchString)      — MC-314: hydrate state from URL (precedence: URL > localStorage)
 *   clearURLParam()                   — MC-314: strip ?cmp= from URL (history.replaceState)
 *   copyShareLink()                   — MC-314: copy share URL to clipboard (with fallback)
 *
 * State persistence: localStorage key 'rf_selected_ids' (JSON array, ordered).
 * Limit: 3 ids enforced at add-time; older selections kept if user clears one slot.
 */
(function (root) {
  'use strict';

  var STORAGE_KEY = 'rf_selected_ids';
  var MAX_SELECTED = 3;

  var state = {
    selected: [],   // array of listing_id strings
    lastPayload: null  // last /api/compare response, for re-render in tests
  };

  // ---- storage helpers -----------------------------------------------------

  function loadFromStorage() {
    try {
      var raw = (root && root.localStorage) ? root.localStorage.getItem(STORAGE_KEY) : null;
      if (!raw) return [];
      var parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(function (x) { return typeof x === 'string' && x.length > 0; }).slice(0, MAX_SELECTED);
    } catch (e) {
      return [];
    }
  }

  function saveToStorage() {
    try {
      if (root && root.localStorage) {
        root.localStorage.setItem(STORAGE_KEY, JSON.stringify(state.selected));
      }
    } catch (e) { /* quota or private mode — silent */ }
  }

  function resetStorage() {
    try {
      if (root && root.localStorage) {
        root.localStorage.removeItem(STORAGE_KEY);
      }
    } catch (e) {}
  }

  // ---- selection mgmt ------------------------------------------------------

  function getSelected() {
    return state.selected.slice();
  }

  function isSelected(id) {
    if (!id) return false;
    return state.selected.indexOf(id) !== -1;
  }

  function addToCompare(id) {
    if (!id) return false;
    if (state.selected.indexOf(id) !== -1) return false;  // already there
    if (state.selected.length >= MAX_SELECTED) return false;
    state.selected.push(id);
    saveToStorage();
    return true;
  }

  function removeFromCompare(id) {
    var idx = state.selected.indexOf(id);
    if (idx === -1) return false;
    state.selected.splice(idx, 1);
    saveToStorage();
    return true;
  }

  function toggleCompare(id) {
    if (!id) return false;
    if (isSelected(id)) {
      removeFromCompare(id);
      return false;
    }
    return addToCompare(id);
  }

  function clearCompare() {
    state.selected = [];
    resetStorage();
    updateClearAllButton();
  }

  // ---- URL encode/decode (MC-314) -----------------------------------------

  // URLSearchParams parsing: returns string[] of valid ids of length 2..MAX_SELECTED, or [].
  // `cap` defaults to MAX_SELECTED — pass Infinity to disable (used by parseURLSelection to
  // detect over-long URLs so we can silently fall back instead of truncating).
  function parseSelectionString(s, cap) {
    var limit = (cap === undefined) ? MAX_SELECTED : cap;
    if (typeof s !== 'string' || !s) return [];
    var raw = s.split(',').map(function (x) { return x.trim(); }).filter(function (x) { return x.length > 0; });
    // Filter: only non-empty string entries (defensive)
    var clean = raw.filter(function (x) { return typeof x === 'string' && x.length > 0; });
    // Dedupe while preserving order
    var seen = {};
    var out = [];
    for (var i = 0; i < clean.length; i++) {
      if (!seen[clean[i]]) {
        seen[clean[i]] = true;
        out.push(clean[i]);
      }
    }
    if (limit === Infinity || limit < 0) return out;
    return out.slice(0, limit);
  }

  function encodeSelection(ids) {
    if (!Array.isArray(ids)) return '';
    var clean = ids.filter(function (x) { return typeof x === 'string' && x.length > 0; });
    return clean.join(',');
  }

  // Parses window.location.search string. Returns array of 2..MAX_SELECTED ids
  // if valid, otherwise returns null (lets caller distinguish "absent" from "invalid").
  // Accepts optional second argument to bypass window lookup (testable in Node).
  //
  // Returns:
  //   null  - no `cmp` param at all (silent fallback to localStorage is correct)
  //   []    - `cmp` is present but invalid count (<2 or >MAX_SELECTED) (silent fallback)
  //   [...] - valid selection (length 2..MAX_SELECTED)
  function parseURLSelection(searchString) {
    var source = (searchString === undefined || searchString === null)
      ? ((typeof window !== 'undefined' && window.location && window.location.search) || '')
      : searchString;
    if (!source) return null;
    var qs = source;
    if (qs.charAt(0) === '?') qs = qs.slice(1);
    try {
      var params = new URLSearchParams(qs);
      if (!params.has('cmp')) return null;
      var raw = params.get('cmp');
      var ids = parseSelectionString(raw, Infinity);
      // Strict: must be in [2, MAX_SELECTED]. Truncating silently would let
      // users accidentally share a 4-id link and unknowingly compare the wrong 3.
      if (ids.length < 2 || ids.length > MAX_SELECTED) {
        return [];
      }
      return ids;
    } catch (e) {
      return null;
    }
  }

  // Returns true iff URL had a valid (2..MAX_SELECTED) cmp param.
  function restoreFromURL(searchString) {
    var ids = parseURLSelection(searchString);
    if (ids && ids.length >= 2 && ids.length <= MAX_SELECTED) {
      state.selected = ids.slice(0, MAX_SELECTED);
      saveToStorage();  // mirror URL selection into localStorage for next page load
      return true;
    }
    return false;
  }

  // Strip ?cmp= from the address bar via history.replaceState.
  function clearURLParam() {
    try {
      if (typeof window === 'undefined' || !window.history || !window.history.replaceState) return false;
      var url = window.location.href;
      var split = url.split('?');
      if (split.length < 2) return false;
      var base = split[0];
      var qs = split.slice(1).join('?');
      var params = new URLSearchParams(qs);
      if (!params.has('cmp')) return false;  // nothing to clear
      params.delete('cmp');
      var newQs = params.toString();
      var newUrl = newQs ? (base + '?' + newQs) : base;
      window.history.replaceState({}, '', newUrl);
      return true;
    } catch (e) {
      return false;
    }
  }

  function buildShareURL() {
    var ids = getSelected();
    var url = '';
    if (typeof window !== 'undefined' && window.location) {
      url = window.location.origin + window.location.pathname;
    }
    if (ids.length > 0) {
      url += '?cmp=' + encodeURIComponent(encodeSelection(ids));
    }
    return url;
  }

  // ---- Copy share link (MC-314) -------------------------------------------

  // Tries clipboard API, then execCommand fallback, then prompt fallback.
  // Returns: 'ok' (clipboard), 'exec' (fallback select+execCommand succeeded),
  // 'prompt' (last-resort window.prompt shown), 'noop' (no api at all).
  function copyShareLink() {
    var url = buildShareURL();
    if (!url) return 'noop';
    // Modern Clipboard API
    if (typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      try {
        navigator.clipboard.writeText(url).then(function () {
          flashCopyButton('ok');
        }).catch(function () {
          var r = fallbackCopy(url);
          flashCopyButton(r);
        });
        return 'ok';
      } catch (e) {
        // fallthrough
      }
    }
    return fallbackCopy(url);
  }

  function fallbackCopy(url) {
    try {
      if (typeof document === 'undefined') return 'noop';
      var input = document.createElement('input');
      input.type = 'text';
      input.value = url;
      // Position off-screen so the user doesn't see flash
      input.style.position = 'fixed';
      input.style.left = '-9999px';
      input.style.top = '0';
      input.setAttribute('readonly', '');
      input.setAttribute('aria-hidden', 'true');
      document.body.appendChild(input);
      input.focus();
      input.select();
      input.setSelectionRange(0, url.length);
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      document.body.removeChild(input);
      if (ok) {
        flashCopyButton('exec');
        return 'exec';
      }
    } catch (e) {
      // fallthrough to prompt
    }
    // Last resort: window.prompt so the user can copy manually
    try {
      if (typeof window !== 'undefined' && typeof window.prompt === 'function') {
        window.prompt('Copy this compare URL:', url);
        flashCopyButton('prompt');
        return 'prompt';
      }
    } catch (e) {}
    return 'noop';
  }

  // Reads/writes the share button label. Default label is "Copy Link".
  function flashCopyButton(kind) {
    var btn = document.getElementById('cmp_share_btn');
    if (!btn) return;
    if (!btn.dataset.origText) {
      btn.dataset.origText = btn.textContent || 'Copy Link';
    }
    var label = '✓ Copied!';
    if (kind === 'prompt') label = 'Copy URL below';
    if (kind === 'noop') label = 'Copy failed';
    btn.textContent = label;
    setTimeout(function () {
      btn.textContent = btn.dataset.origText || 'Copy Link';
    }, 1800);
  }

  // ---- UI updates ----------------------------------------------------------

  function updateCompareBadge() {
    var btn = document.getElementById('compare_btn');
    var lbl = document.getElementById('compare_btn_label');
    if (!btn) return;
    var n = state.selected.length;
    if (n < 2) {
      btn.style.display = 'none';
    } else {
      btn.style.display = '';
    }
    if (lbl) lbl.textContent = 'Compare ' + n;
    updateClearAllButton();
  }

  // MC-314: show the filter-bar "Clear All Selected" button when 1+ selected.
  // (Compare button shows only with 2+, but Clear All is useful even with 1.)
  function updateClearAllButton() {
    var btn = document.getElementById('clear_all_btn');
    if (!btn) return;
    var n = state.selected.length;
    if (n >= 1) {
      btn.style.display = '';
    } else {
      btn.style.display = 'none';
    }
    var lbl = document.getElementById('clear_all_btn_label');
    if (lbl) lbl.textContent = 'Clear All (' + n + ')';
  }

  function syncRowCheckboxes() {
    var checks = document.querySelectorAll('.compare-check');
    for (var i = 0; i < checks.length; i++) {
      var c = checks[i];
      var id = c.getAttribute('data-listing-id') || '';
      c.checked = isSelected(id);
    }
  }

  // ---- pure render fn ------------------------------------------------------

  function escHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function fmtMoney(n) {
    if (n === null || n === undefined || isNaN(n)) return '—';
    return '$' + Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 });
  }

  function fmtPct(n) {
    if (n === null || n === undefined || isNaN(n)) return '—';
    var sign = n > 0 ? '+' : '';
    return sign + Number(n).toFixed(1) + '%';
  }

  function fmtNum(n, suffix) {
    if (n === null || n === undefined || isNaN(n)) return '—';
    return String(n) + (suffix || '');
  }

  function renderPhoto(d) {
    var firstImg = '';
    var urls = (d.image_urls && d.image_urls.length) ? d.image_urls : ((d.image_url) ? [d.image_url] : []);
    if (urls.length > 0) firstImg = urls[0];
    if (!firstImg) {
      return '<div class="cmp-photo cmp-photo-fallback">🏠</div>';
    }
    var esc = firstImg.replace(/"/g, '&quot;');
    return '<div class="cmp-photo"><img src="' + esc + '" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentNode.classList.add(\'cmp-photo-broken\');this.style.display=\'none\';" /></div>';
  }

  // Build the per-column body for one listing. `bestId` is the listing_id of the
  // "best" winner for the row (null if no winner or this column isn't the winner).
  function cell(d, isWinner) {
    var cls = 'cmp-cell' + (isWinner ? ' cmp-cell-best' : '');
    var winnerBadge = isWinner ? '<span class="cmp-winner-badge" title="Best on this metric">★</span>' : '';
    return '<div class="' + cls + '">' + winnerBadge + '</div>';
  }

  // Row builders. Each returns the inner HTML of the row, given the payload
  // (which contains `listings` and `best`).
  function rowHtml(rowLabel, valueFns, payload) {
    var listings = payload.listings || [];
    var best = payload.best || {};
    var cells = listings.map(function (d) {
      var bestId = valueFns.bestKey ? best[valueFns.bestKey] : null;
      var isWinner = (bestId && d.listing_id === bestId);
      var inner = valueFns.fn(d);
      return '<div class="cmp-cell-col">' + cell(d, isWinner) + '<div class="cmp-cell-value">' + inner + '</div></div>';
    }).join('');
    return '<div class="cmp-row"><div class="cmp-row-label">' + escHtml(rowLabel) + '</div>' + cells + '</div>';
  }

  function renderCompareRows(payload) {
    if (!payload || !Array.isArray(payload.listings)) {
      return '<div class="cmp-empty">No listings to compare.</div>';
    }
    var listings = payload.listings;
    if (listings.length < 2) {
      return '<div class="cmp-empty">Select 2-3 listings to compare.</div>';
    }

    var n = listings.length;
    var colsStyle = '<style>.cmp-rows,.cmp-header,.cmp-row,.cmp-remove-row{--cmp-cols:' + n + ';}</style>';

    // Photo + header (title + neighbourhood + price)
    var header = '<div class="cmp-header">' + listings.map(function (d) {
      return '<div class="cmp-col-header">' +
               renderPhoto(d) +
               '<div class="cmp-title">' + escHtml(d.title || d.neighbourhood || 'Listing') + '</div>' +
               '<div class="cmp-neighbourhood">' + escHtml(d.neighbourhood || '—') + (d.region ? ' · ' + escHtml(d.region) : '') + '</div>' +
               '<div class="cmp-price">' + escHtml(d.price_fmt || fmtMoney(d.price)) + '</div>' +
             '</div>';
    }).join('') + '</div>';

    // Value-fn rows. Each entry maps to a metric row in the modal.
    var rows = [];

    rows.push(rowHtml('Listed Price', {
      bestKey: 'lowest_price',
      fn: function (d) { return escHtml(d.price_fmt || fmtMoney(d.price)); }
    }, payload));

    rows.push(rowHtml('Fair Value', {
      bestKey: null,
      fn: function (d) { return escHtml(d.fair_value_fmt || fmtMoney(d.fair_value)); }
    }, payload));

    rows.push(rowHtml('Savings', {
      bestKey: 'smallest_savings_gap',
      fn: function (d) {
        var s = d.savings;
        if (s === null || s === undefined || isNaN(s)) return '—';
        var cls = s >= 0 ? 'cmp-savings-pos' : 'cmp-savings-neg';
        return '<span class="' + cls + '">' + fmtMoney(s) + '/mo</span>';
      }
    }, payload));

    rows.push(rowHtml('% Under Market', {
      bestKey: null,
      fn: function (d) { return escHtml(d.pct_under_fmt || fmtPct(d.pct_under)); }
    }, payload));

    rows.push(rowHtml('Bedrooms', {
      bestKey: null,
      fn: function (d) { return escHtml(d.beds === null || d.beds === undefined ? '—' : String(d.beds)); }
    }, payload));

    rows.push(rowHtml('Bathrooms', {
      bestKey: null,
      fn: function (d) { return escHtml(d.baths === null || d.baths === undefined ? '—' : String(d.baths)); }
    }, payload));

    rows.push(rowHtml('Sqft', {
      bestKey: null,
      fn: function (d) { return escHtml(d.sqft === '' || d.sqft === null || d.sqft === undefined ? '—' : String(d.sqft)); }
    }, payload));

    rows.push(rowHtml('$ / Sqft', {
      bestKey: 'lowest_price_per_sqft',
      fn: function (d) {
        if (d.price_per_sqft === null || d.price_per_sqft === undefined) return '—';
        return '$' + Number(d.price_per_sqft).toFixed(2);
      }
    }, payload));

    rows.push(rowHtml('Age', {
      bestKey: null,
      fn: function (d) { return escHtml(d.days_ago_str || (d.days_ago === null ? '—' : String(d.days_ago) + 'd')); }
    }, payload));

    rows.push(rowHtml('Commute', {
      bestKey: null,
      fn: function (d) {
        var c = d.commute_minutes;
        if (c === null || c === undefined) return '—';
        return Math.round(c) + ' min';
      }
    }, payload));

    rows.push(rowHtml('Grocery', {
      bestKey: null,
      fn: function (d) {
        if (!d.grocery_name) return '—';
        var m = d.grocery_walk_min;
        return escHtml(d.grocery_name) + (m ? ' · ' + Math.round(m) + 'm walk' : '');
      }
    }, payload));

    rows.push(rowHtml('🚇 TTC', {
      bestKey: null,
      fn: function (d) {
        if (!d.station_name) return '—';
        var m = d.station_walk_min;
        return escHtml(d.station_name) + (m ? ' · ' + Math.round(m) + 'm walk' : '');
      }
    }, payload));

    rows.push(rowHtml('🏋 Gym', {
      bestKey: null,
      fn: function (d) {
        if (!d.gym_name) return '—';
        var m = d.gym_walk_min;
        return escHtml(d.gym_name) + (m ? ' · ' + Math.round(m) + 'm walk' : '');
      }
    }, payload));

    rows.push(rowHtml('🅿 Parking', {
      bestKey: null,
      fn: function (d) {
        if (!d.parking_name) return '—';
        var m = d.parking_walk_min;
        return escHtml(d.parking_name) + (m ? ' · ' + Math.round(m) + 'm walk' : '');
      }
    }, payload));

    rows.push(rowHtml('Photos', {
      bestKey: 'most_photos',
      fn: function (d) { return fmtNum(d.photo_count || 0); }
    }, payload));

    rows.push(rowHtml('Cautions', {
      bestKey: null,
      fn: function (d) {
        var c = d.cautions || [];
        if (!c.length) return '<span class="cmp-clean">✓ Clean</span>';
        return c.map(function (x) { return '<span class="cmp-caution">' + escHtml(x) + '</span>'; }).join('');
      }
    }, payload));

    rows.push(rowHtml('Link', {
      bestKey: null,
      fn: function (d) {
        var url = escHtml(d.link || '');
        return '<a href="' + url + '" target="_blank" rel="noopener" class="cmp-link">View ↗</a>';
      }
    }, payload));

    var remove = '<div class="cmp-remove-row">' + listings.map(function (d) {
      return '<button type="button" class="cmp-remove-btn" data-listing-id="' + escHtml(d.listing_id) + '">Remove</button>';
    }).join('') + '</div>';

    return colsStyle + header + '<div class="cmp-rows">' + rows.join('') + '</div>' + remove;
  }

  // ---- modal open/close ----------------------------------------------------

  function openCompareModal() {
    if (state.selected.length < 2) return;  // require >=2
    var modal = document.getElementById('compare_modal');
    var body = document.getElementById('compare_body');
    var errEl = document.getElementById('compare_error');
    if (!modal || !body) return;
    if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
    body.innerHTML = '<div class="cmp-loading">Loading comparison…</div>';
    modal.style.display = 'flex';

    var ids = state.selected.join(',');
    fetch('/api/compare?ids=' + encodeURIComponent(ids), { credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
      .then(function (res) {
        if (res.status !== 200) {
          if (errEl) {
            errEl.textContent = (res.body && res.body.error) ? res.body.error : ('HTTP ' + res.status);
            errEl.style.display = 'block';
          }
          body.innerHTML = '';
          return;
        }
        state.lastPayload = res.body;
        body.innerHTML = renderCompareRows(res.body);
        // Wire remove buttons
        var btns = body.querySelectorAll('.cmp-remove-btn');
        for (var i = 0; i < btns.length; i++) {
          btns[i].addEventListener('click', function (e) {
            var lid = e.currentTarget.getAttribute('data-listing-id');
            removeFromCompare(lid);
            updateCompareBadge();
            syncRowCheckboxes();
            if (state.selected.length < 2) {
              closeCompareModal();
            } else {
              openCompareModal();  // re-fetch with remaining ids
            }
          });
        }
      })
      .catch(function (err) {
        if (errEl) {
          errEl.textContent = 'Failed to load: ' + (err.message || 'network error');
          errEl.style.display = 'block';
        }
        body.innerHTML = '';
      });
  }

  function closeCompareModal() {
    var modal = document.getElementById('compare_modal');
    if (modal) modal.style.display = 'none';
  }

  // ---- init ----------------------------------------------------------------

  function init() {
    state.selected = loadFromStorage();
    // MC-314: URL takes precedence over localStorage. If URL has 2..MAX_SELECTED
    // valid ids, override localStorage and clean the URL so subsequent updates
    // don't keep reverting. If URL has invalid form, silently fall back.
    var urlSearch = (typeof window !== 'undefined' && window.location && window.location.search) || '';
    var fromURL = restoreFromURL(urlSearch);
    if (fromURL) {
      clearURLParam();
    }
    updateCompareBadge();
    // Auto-open modal when state has 2..MAX_SELECTED ids (typical on URL restore).
    if (state.selected.length >= 2) {
      // Defer so any DOM build completes first; safe to delay slightly.
      setTimeout(function () {
        try { openCompareModal(); } catch (e) { /* silent */ }
      }, 0);
    }
  }

  // Expose ------------------------------------------------------------------

  var api = {
    STORAGE_KEY: STORAGE_KEY,
    MAX_SELECTED: MAX_SELECTED,
    init: init,
    addToCompare: addToCompare,
    removeFromCompare: removeFromCompare,
    toggleCompare: toggleCompare,
    clearCompare: clearCompare,
    getSelected: getSelected,
    isSelected: isSelected,
    updateCompareBadge: updateCompareBadge,
    updateClearAllButton: updateClearAllButton,
    syncRowCheckboxes: syncRowCheckboxes,
    openCompareModal: openCompareModal,
    closeCompareModal: closeCompareModal,
    renderCompareRows: renderCompareRows,
    loadFromStorage: loadFromStorage,
    saveToStorage: saveToStorage,
    resetStorage: resetStorage,
    escHtml: escHtml,
    fmtMoney: fmtMoney,
    fmtPct: fmtPct,
    fmtNum: fmtNum,
    // MC-314:
    parseSelectionString: parseSelectionString,
    encodeSelection: encodeSelection,
    parseURLSelection: parseURLSelection,
    restoreFromURL: restoreFromURL,
    clearURLParam: clearURLParam,
    buildShareURL: buildShareURL,
    copyShareLink: copyShareLink,
    fallbackCopy: fallbackCopy,
    flashCopyButton: flashCopyButton,
    getState: function () { return { selected: state.selected.slice(), lastPayload: state.lastPayload }; },
    setState: function (s) {  // test-only helper
      if (s && Array.isArray(s.selected)) state.selected = s.selected.slice();
      state.lastPayload = s && s.lastPayload !== undefined ? s.lastPayload : state.lastPayload;
    }
  };

  if (typeof window !== 'undefined') {
    window.__compare = api;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (root && typeof root === 'object') {
    root.__compare = api;
  }
})(typeof self !== 'undefined' ? self : (typeof window !== 'undefined' ? window : null));