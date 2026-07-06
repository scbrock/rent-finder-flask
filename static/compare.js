/* MC-313: Side-by-side deal comparison.
 *
 * Public API (also exposed via window.__compare and module.exports for Node tests):
 *   addToCompare(listingId)           — toggle-on (add + persist)
 *   removeFromCompare(listingId)      — toggle-off (remove + persist)
 *   toggleCompare(listingId)          — flip selection
 *   clearCompare()                    — wipe all selected + persist
 *   getSelected()                     — returns string[] of listing_ids in selection order
 *   isSelected(listingId)             — boolean
 *   updateCompareBadge()              — refresh the "Compare N" button label/visibility
 *   openCompareModal()                — fetch /api/compare + render modal
 *   closeCompareModal()               — hide modal
 *   renderCompareRows(payload)        — pure render fn for testability
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
    updateCompareBadge();
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