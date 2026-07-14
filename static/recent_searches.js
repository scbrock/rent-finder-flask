// MC-353: 'Recent searches ▾' dropdown in the filter bar.
//
// Stores an Array<{filters, label, savedAtMs}> in localStorage under
// 'rf_recent_searches' (cap: 5, newest-first, dedup by JSON serialization
// of the filter object). The module is lightweight + browser-only — no
// backend writes, no SQLite, no email/name. Distinct from MC-322's
// named-saved-searches page: this is "the last few filters I clicked
// through" — anonymous + ephemeral — whereas MC-322 is "filter combos I
// want to be notified about by email."
//
// Public API (returned from createView(opts)):
//   init(opts?)                                — set up debounce + cross-tab sync
//   saveCurrent(filters, opts?)                — push the active filter set
//                                                 onto the history (dedup
//                                                 against the most-recent
//                                                 entry, capped at 5)
//   getAll()                                   — newest-first list
//   getRecent(n=5)                             — cap helper
//   count()                                    — current length
//   removeAt(idx)                              — drop a single entry
//   clearAll()                                 — wipe everything (with confirm)
//   buildLabel(filters)                        — human-readable label from filters
//   serializeFilters(filters) -> string        — canonical JSON for dedup
//   renderEntry(entry, opts?) -> string        — HTML for a single popover row
//   attachPopover(triggerEl, containerEl)      — wire the trigger button
//   closePopover() / togglePopover()
//   listenStorage(handlerFn)                   — cross-tab sync via storage event
//   restoreFromObject(filters, opts?)          — apply a saved filter set
//
// Self-contained IIFE. Browser: window.__recentSearches. Node tests:
// module.exports = factory().

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.__recentSearches = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {

  const DEFAULT_STORAGE_KEY = 'rf_recent_searches';
  const DEFAULT_MAX_ENTRIES = 5;
  const DEFAULT_DEBOUNCE_MS = 1000;
  const DEFAULT_NOW_MS = function () { return Date.now(); };

  // Keys we round-trip in serialize/deserialize/label. Anything not in this
  // list is dropped so the dedup key stays stable across builds.
  const ROUND_TRIP_KEYS = [
    'beds_min', 'baths_min', 'price_min', 'price_max',
    'neighbourhood', 'region', 'source', 'sort',
    'max_subway', 'max_commute', 'hide_stale', 'is_new',
    'price_dropped', 'has_image', 'has_parking',
    'commute_dest', 'price_per_sqft_max', 'min_pct_under',
  ];

  // ---------------------------------------------------------------------
  // Pure helpers — testable directly via factory().
  // ---------------------------------------------------------------------

  function _escHtml(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function _isPlainObject(v) {
    return v && typeof v === 'object' && !Array.isArray(v);
  }

  function _canonicalFilters(filters) {
    // Strip non-string/non-empty values, drop unknown keys, sort the
    // resulting entries by key for a deterministic serialization order.
    const out = {};
    if (!_isPlainObject(filters)) return out;
    ROUND_TRIP_KEYS.forEach(function (k) {
      if (Object.prototype.hasOwnProperty.call(filters, k)) {
        let v = filters[k];
        if (v == null) return;
        if (typeof v === 'boolean') v = v ? 'true' : '';
        v = String(v);
        if (v === '' || v === 'undefined' || v === 'null') return;
        out[k] = v;
      }
    });
    return out;
  }

  function serializeFilters(filters) {
    const canon = _canonicalFilters(filters);
    return JSON.stringify(canon, Object.keys(canon).sort());
  }

  function _fmtAgo(savedAtMs, nowMs) {
    if (typeof savedAtMs !== 'number' || !isFinite(savedAtMs)) return '';
    const now = (typeof nowMs === 'number' && isFinite(nowMs)) ? nowMs : DEFAULT_NOW_MS();
    const deltaSec = Math.max(0, Math.floor((now - savedAtMs) / 1000));
    if (deltaSec < 60) return 'just now';
    if (deltaSec < 3600) return Math.floor(deltaSec / 60) + 'm ago';
    if (deltaSec < 86400) {
      const h = Math.floor(deltaSec / 3600);
      if (h < 24 && h >= 20) return 'yesterday';
      return h + 'h ago';
    }
    const d = Math.floor(deltaSec / 86400);
    if (d === 1) return 'yesterday';
    if (d < 7) return d + 'd ago';
    if (d < 30) return Math.floor(d / 7) + 'w ago';
    return Math.floor(d / 30) + 'mo ago';
  }

  function _sortLabel(val) {
    switch (val) {
      case 'score': return 'best deal';
      case 'price': return 'price';
      case 'price_asc': return 'price low\u2191';
      case 'days_ago': return 'newest';
      case 'commute': return 'commute';
      case 'pct_under': return '% under';
      case 'sqft': return 'sqft';
      default: return val || '';
    }
  }

  // Build a human-readable label like "Downtown 2BR ≤ $2,500 sorted by best deal"
  // or "Toronto: studio, 1BR" or "All deals". Falls back to a short
  // summary when no specific keys are set.
  function buildLabel(filters) {
    if (!_isPlainObject(filters)) return 'All deals';
    const parts = [];

    // Beds (e.g., "2BR" or "Studio")
    const bm = filters.beds_min;
    if (bm && /^\d+$/.test(String(bm))) {
      parts.push(String(bm) === '0' ? 'Studio' : (String(bm) + 'BR'));
    }

    // Baths
    const ba = filters.baths_min;
    if (ba && /^\d+$/.test(String(ba))) {
      parts.push('\u2265' + String(ba) + 'BA');
    }

    // Price max (most common filter)
    const pm = filters.price_max;
    if (pm && !isNaN(parseFloat(pm))) {
      const n = Math.round(parseFloat(pm));
      parts.push('\u2264$' + n.toLocaleString('en-US'));
    }

    // Price min
    const pmi = filters.price_min;
    if (pmi && !isNaN(parseFloat(pmi))) {
      const n = Math.round(parseFloat(pmi));
      parts.push('\u2265$' + n.toLocaleString('en-US'));
    }

    // Neighbourhood or region
    if (filters.neighbourhood && typeof filters.neighbourhood === 'string' && filters.neighbourhood.trim()) {
      parts.push('in ' + filters.neighbourhood.trim());
    } else if (filters.region && typeof filters.region === 'string' && filters.region.trim()) {
      parts.push('in ' + filters.region.trim());
    } else {
      parts.push('All Toronto');
    }

    let label = parts.join(' ');

    // Source filter
    if (filters.source && filters.source !== 'all' && filters.source !== '') {
      label += ' (' + filters.source + ')';
    }

    // Sort (when not default 'score')
    const sort = filters.sort;
    if (sort && sort !== 'score') {
      label += ' sorted by ' + _sortLabel(sort);
    } else {
      label += ' sorted by best deal';
    }

    // Toggles (only when active — keep label compact)
    const toggleLabels = [];
    if (filters.hide_stale === 'true') toggleLabels.push('hide stale');
    if (filters.is_new === 'true') toggleLabels.push('only new');
    if (filters.price_dropped === 'true') toggleLabels.push('price drops');
    if (filters.has_image === 'true') toggleLabels.push('with photos');
    if (filters.has_parking === 'true') toggleLabels.push('parking');
    if (filters.min_pct_under) toggleLabels.push('\u2265' + filters.min_pct_under + '% under');
    if (filters.price_per_sqft_max) toggleLabels.push('\u2264$' + filters.price_per_sqft_max + '/sqft');
    if (toggleLabels.length) label += ' · ' + toggleLabels.join(', ');

    // Trim long labels so the popover row stays one line on desktop.
    if (label.length > 110) label = label.slice(0, 107) + '\u2026';
    return label;
  }

  // ---------------------------------------------------------------------
  // Storage helpers — read/write a sanitized Array<{filters, label, savedAtMs}>.
  // ---------------------------------------------------------------------

  function _sanitizeEntry(entry) {
    if (!_isPlainObject(entry)) return null;
    const filters = _canonicalFilters(entry.filters || {});
    if (Object.keys(filters).length === 0) return null;
    const savedAt = (typeof entry.savedAtMs === 'number' && isFinite(entry.savedAtMs) && entry.savedAtMs > 0)
      ? entry.savedAtMs : DEFAULT_NOW_MS();
    const label = typeof entry.label === 'string' && entry.label.length ? entry.label : buildLabel(filters);
    return { filters: filters, label: label, savedAtMs: savedAt };
  }

  function _safeParse(raw) {
    if (typeof raw !== 'string' || !raw) return [];
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        const out = [];
        parsed.forEach(function (e) {
          const cleaned = _sanitizeEntry(e);
          if (cleaned) out.push(cleaned);
        });
        return out;
      }
    } catch (e) { /* swallow */ }
    return [];
  }

  function _readState(storage, key) {
    if (!storage || typeof storage.getItem !== 'function') return [];
    try { return _safeParse(storage.getItem(key)); }
    catch (e) { return []; }
  }

  function _writeState(storage, key, list) {
    if (!storage || typeof storage.setItem !== 'function') return false;
    try {
      storage.setItem(key, JSON.stringify(list));
      return true;
    } catch (e) { return false; }
  }

  // ---------------------------------------------------------------------
  // createView() instance factory.
  // ---------------------------------------------------------------------

  function createView(opts) {
    opts = opts || {};
    const storageKey = opts.storageKey || DEFAULT_STORAGE_KEY;
    const maxEntries = (typeof opts.maxEntries === 'number' && opts.maxEntries > 0) ? opts.maxEntries : DEFAULT_MAX_ENTRIES;
    const debounceMs = (typeof opts.debounceMs === 'number' && opts.debounceMs >= 0) ? opts.debounceMs : DEFAULT_DEBOUNCE_MS;

    const storage = opts.storage
      || (typeof root !== 'undefined' && root && root.localStorage)
      || (typeof globalThis !== 'undefined' && globalThis && globalThis.localStorage) || null;
    const win = opts.window
      || (typeof root !== 'undefined' && root && root.addEventListener ? root : null);
    const doc = opts.document
      || (typeof root !== 'undefined' && root && root.document)
      || (typeof globalThis !== 'undefined' && globalThis && globalThis.document) || null;

    // In-memory cache so callers don't hit localStorage on every read.
    let state = _readState(storage, storageKey);

    // Popover attachment state.
    let _triggerEl = null;
    let _containerEl = null;
    let _outsideClickHandler = null;
    let _keydownHandler = null;
    let _restoreHooks = [];   // [{apply: function(filters)}]

    // Debounce state for saveCurrent() — coalesce a flurry of filter changes
    // into one write so the popover only sees the final state.
    let _pendingTimer = null;
    let _pendingFilters = null;

    function _persist() {
      _writeState(storage, storageKey, state);
    }

    function _applyCanonical(filters) {
      const canon = _canonicalFilters(filters || {});
      const label = buildLabel(canon);
      return { filters: canon, label: label, savedAtMs: DEFAULT_NOW_MS() };
    }

    function saveCurrent(filters, opts2) {
      const o = opts2 || {};
      if (!_isPlainObject(filters)) return false;
      const entry = _applyCanonical(filters);
      // Skip empty filter sets so an idle bar doesn't fill the history with
      // an "All deals" entry every page load.
      if (Object.keys(entry.filters).length === 0 && !o.force) return false;
      const sig = serializeFilters(entry.filters);
      // Dedup against the most-recent entry — if the active filter combo
      // matches, just bump the timestamp and return without shifting the
      // list position.
      if (state.length && serializeFilters(state[0].filters) === sig) {
        state[0].savedAtMs = entry.savedAtMs;
        state[0].label = entry.label;
        _persist();
        return true;
      }
      // Prepend, cap at maxEntries.
      state.unshift(entry);
      if (state.length > maxEntries) state = state.slice(0, maxEntries);
      _persist();
      return true;
    }

    function saveCurrentDebounced(filters, opts2) {
      _pendingFilters = filters;
      if (_pendingTimer) {
        try { clearTimeout(_pendingTimer); } catch (e) { /* swallow */ }
      }
      _pendingTimer = setTimeout(function () {
        _pendingTimer = null;
        const f = _pendingFilters;
        _pendingFilters = null;
        if (f) saveCurrent(f, opts2);
      }, debounceMs);
    }

    function cancelPending() {
      _pendingTimer = null;
      _pendingFilters = null;
    }

    function getAll() { return state.slice(); }

    function getRecent(n) {
      const cap = (typeof n === 'number' && n > 0) ? n : maxEntries;
      return state.slice(0, cap);
    }

    function count() { return state.length; }

    function removeAt(idx) {
      if (typeof idx !== 'number' || idx < 0 || idx >= state.length) return false;
      state.splice(idx, 1);
      _persist();
      return true;
    }

    function clearAll() {
      state = [];
      _persist();
    }

    // ---------------------------------------------------------------
    // Popover rendering.
    // ---------------------------------------------------------------
    function renderEntry(entry, opts2) {
      if (!entry) return '';
      if (!_isPlainObject(entry.filters) || Object.keys(entry.filters).length === 0) return '';
      const sig = serializeFilters(entry.filters);
      const label = entry.label || buildLabel(entry.filters);
      const ago = _fmtAgo(entry.savedAtMs, (opts2 && opts2.nowMs) || DEFAULT_NOW_MS());
      const idx = (opts2 && typeof opts2.idx === 'number') ? opts2.idx : -1;
      return (
        '<div class="rs-entry" data-sig="' + _escHtml(sig) + '" data-idx="' + idx + '">' +
          '<div class="rs-body">' +
            '<div class="rs-label">' + _escHtml(label) + '</div>' +
            (ago ? '<div class="rs-ago">' + _escHtml(ago) + '</div>' : '') +
          '</div>' +
          '<button type="button" class="rs-delete" data-idx="' + idx + '" '
            + 'aria-label="Remove this saved search" title="Remove">\u2715</button>' +
        '</div>'
      );
    }

    function _buildEntriesHtml(nowMs) {
      const recent = getRecent(maxEntries);
      if (!recent.length) {
        return '<div class="rs-empty">No recent filter combinations yet</div>';
      }
      const rows = [];
      for (let i = 0; i < recent.length; i++) {
        rows.push(renderEntry(recent[i], { nowMs: nowMs, idx: i }));
      }
      rows.push(
        '<div class="rs-footer">' +
          '<button type="button" class="rs-clear-btn">Clear all</button>' +
          '<span class="rs-count-note">' + state.length + ' of ' + maxEntries + ' saved</span>' +
        '</div>'
      );
      return rows.join('');
    }

    function _applySavedFilters(filters) {
      // Hook into the page's existing restore pipeline when one is wired
      // (applySavedFilters or parseQueryParams). Without a hook, the
      // restoreFromObject helper exists for callers to handle the round-trip
      // themselves.
      if (!_restoreHooks.length) return false;
      _restoreHooks.forEach(function (h) {
        try {
          if (h && typeof h.apply === 'function') h.apply(filters);
        } catch (e) { /* swallow */ }
      });
      return true;
    }

    function restoreFromObject(filters, opts2) {
      const o = opts2 || {};
      const canon = _canonicalFilters(filters || {});
      if (!Object.keys(canon).length) return false;
      // 1) Synthesize a URL string the existing parseQueryParams() understands
      //    so all the form-input writes happen through the same code path.
      const params = new URLSearchParams();
      Object.keys(canon).forEach(function (k) {
        params.set(k, canon[k]);
      });
      // 2) Update the URL bar so the share-link / refresh flow stays
      //    consistent.
      try {
        if (typeof win !== 'undefined' && win && win.history && typeof win.history.replaceState === 'function') {
          const newUrl = params.toString() ? '?' + params.toString() : (win.location && win.location.pathname) || '/';
          win.history.replaceState({}, '', newUrl);
        }
      } catch (e) { /* swallow */ }
      // 3) Run any registered hook (callers wire applySavedFilters here).
      _applySavedFilters(canon);
      // 4) Manually dispatch change events so updateFilterCount + loadDeals
      //    fire even when the value hasn't moved (programmatic .value = X
      //    does NOT fire change events on its own).
      if (!o.skipEvents && doc && typeof doc.querySelectorAll === 'function') {
        const inputs = [
          'beds_min', 'baths_min', 'price_min', 'price_max',
          'neighbourhood', 'region', 'source', 'sort_by',
          'max_subway', 'max_commute', 'commute_dest',
          'max_price_per_sqft', 'min_pct_under',
        ];
        inputs.forEach(function (id) {
          const el = doc.getElementById(id);
          if (!el) return;
          try {
            el.dispatchEvent(new Event('change', { bubbles: true }));
          } catch (e) { /* swallow */ }
        });
        const toggles = [
          'hide_stale', 'only_new', 'price_dropped', 'has_image', 'has_parking',
        ];
        toggles.forEach(function (id) {
          const el = doc.getElementById(id);
          if (!el) return;
          try {
            el.dispatchEvent(new Event('change', { bubbles: true }));
          } catch (e) { /* swallow */ }
        });
      }
      return true;
    }

    function onRestore(hook) {
      if (hook && typeof hook.apply === 'function') {
        _restoreHooks.push(hook);
      }
      return api;
    }

    function _openPopover() {
      if (!_containerEl) return false;
      const now = DEFAULT_NOW_MS();
      const entriesHtml = _buildEntriesHtml(now);
      _containerEl.innerHTML = (
        '<button type="button" class="rs-close" aria-label="Close popover">\u00d7</button>' +
        '<div class="rs-header">Recent filter searches</div>' +
        '<div class="rs-entries">' + entriesHtml + '</div>'
      );
      _containerEl.setAttribute('data-state', 'open');
      _containerEl.style.display = '';

      // Position the popover under the trigger button. position: fixed so
      // the popover escapes any ancestor with overflow:hidden.
      if (_triggerEl && typeof _triggerEl.getBoundingClientRect === 'function'
          && typeof _containerEl.getBoundingClientRect === 'function') {
        try {
          const tr = _triggerEl.getBoundingClientRect();
          const pr = _containerEl.getBoundingClientRect();
          const top = Math.max(8, tr.bottom + 6);
          const vw = (typeof win !== 'undefined' && win && win.innerWidth) ? win.innerWidth : 1024;
          const left = Math.max(8, Math.min(vw - pr.width - 8, tr.right - pr.width));
          _containerEl.style.position = 'fixed';
          _containerEl.style.top = top + 'px';
          _containerEl.style.left = left + 'px';
        } catch (e) { /* swallow */ }
      }

      // Wire up the close button.
      const closeBtn = _containerEl.querySelector('.rs-close');
      if (closeBtn) closeBtn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        closePopover();
      });

      // Wire up the Clear-all footer button.
      const clearBtn = _containerEl.querySelector('.rs-clear-btn');
      if (clearBtn) clearBtn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const globalRoot = (typeof root !== 'undefined') ? root : null;
        const proceed = !globalRoot || typeof globalRoot.confirm !== 'function'
          ? true
          : globalRoot.confirm('Forget all recent filter searches?');
        if (proceed) {
          clearAll();
          closePopover();
        }
      });

      // Wire up per-entry click (restore) + delete button.
      const entries = _containerEl.querySelectorAll('.rs-entry');
      entries.forEach(function (entryEl) {
        entryEl.addEventListener('click', function (ev) {
          // Don't double-fire when the delete button is the target.
          if (ev.target && ev.target.classList && ev.target.classList.contains('rs-delete')) return;
          const sig = entryEl.getAttribute('data-sig');
          if (!sig) return;
          const idx = parseInt(entryEl.getAttribute('data-idx'), 10);
          const entry = (typeof idx === 'number' && idx >= 0 && idx < state.length) ? state[idx] : null;
          if (!entry) return;
          restoreFromObject(entry.filters);
          closePopover();
        });
      });

      const delBtns = _containerEl.querySelectorAll('.rs-delete');
      delBtns.forEach(function (btn) {
        btn.addEventListener('click', function (ev) {
          ev.preventDefault();
          ev.stopPropagation();
          const idx = parseInt(btn.getAttribute('data-idx'), 10);
          if (typeof idx !== 'number' || isNaN(idx)) return;
          if (removeAt(idx)) {
            // Re-render so the entry disappears immediately.
            _openPopover();
          }
        });
      });

      // Outside-click dismiss.
      if (win && typeof win.addEventListener === 'function') {
        _outsideClickHandler = function (ev) {
          if (!_containerEl) return;
          if (ev.target === _triggerEl || (_triggerEl && _triggerEl.contains(ev.target))) return;
          if (_containerEl.contains(ev.target)) return;
          closePopover();
        };
        win.addEventListener('click', _outsideClickHandler);
      }
      return true;
    }

    function closePopover() {
      if (!_containerEl) return;
      _containerEl.setAttribute('data-state', 'closed');
      _containerEl.style.display = 'none';
      if (_outsideClickHandler && win && typeof win.removeEventListener === 'function') {
        win.removeEventListener('click', _outsideClickHandler);
      }
      _outsideClickHandler = null;
    }

    function togglePopover() {
      if (!_containerEl) return;
      if (_containerEl.getAttribute('data-state') === 'open') closePopover();
      else _openPopover();
    }

    function attachPopover(triggerEl, containerEl) {
      if (!triggerEl || !containerEl) return api;
      _triggerEl = triggerEl;
      _containerEl = containerEl;

      triggerEl.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        togglePopover();
      });

      // Escape-key dismissal.
      if (win && typeof win.addEventListener === 'function') {
        _keydownHandler = function (ev) {
          if (ev && ev.key === 'Escape' && _containerEl
              && _containerEl.getAttribute('data-state') === 'open') {
            closePopover();
          }
        };
        win.addEventListener('keydown', _keydownHandler);
      }

      refresh();
      return api;
    }

    function listenStorage(handler) {
      if (typeof handler !== 'function') return api;
      if (win && typeof win.addEventListener === 'function'
          && !win.__rs_storage_wired) {
        win.addEventListener('storage', function (ev) {
          if (!ev || ev.key !== storageKey) return;
          state = _readState(storage, storageKey);
          try { handler({ type: 'storage', key: storageKey, state: state }); }
          catch (e) { /* swallow */ }
        });
        win.__rs_storage_wired = true;
      }
      return api;
    }

    function refresh() {
      // Disable the trigger when there are no entries — empty popovers are
      // pointless and a disabled button is clearer than a click that opens
      // a "No recent filter combinations yet" message.
      if (_triggerEl && !_triggerEl.disabled === false) {
        // no-op (so we don't fight an inline disabled attribute set elsewhere)
      }
      if (_triggerEl) {
        _triggerEl.disabled = (state.length === 0);
        _triggerEl.setAttribute('data-count', String(state.length));
      }
      if (_containerEl && _containerEl.getAttribute('data-state') === 'open') {
        _openPopover();
      }
    }

    const api = {
      init: function (o) {
        if (o && typeof o.debounceMs === 'number') { /* no-op for now */ }
        return api;
      },
      saveCurrent: saveCurrent,
      saveCurrentDebounced: saveCurrentDebounced,
      cancelPending: cancelPending,
      getAll: getAll,
      getRecent: getRecent,
      count: count,
      removeAt: removeAt,
      clearAll: clearAll,
      buildLabel: buildLabel,
      serializeFilters: serializeFilters,
      renderEntry: renderEntry,
      attachPopover: attachPopover,
      closePopover: closePopover,
      togglePopover: togglePopover,
      listenStorage: listenStorage,
      restoreFromObject: restoreFromObject,
      onRestore: onRestore,
      refresh: refresh,
      // Exposed for tests
      _escHtml: _escHtml,
      _canonicalFilters: _canonicalFilters,
      _fmtAgo: _fmtAgo,
      _safeParse: _safeParse,
      _storageKey: storageKey,
      _maxEntries: maxEntries,
      _debounceMs: debounceMs,
    };
    return api;
  }

  return {
    DEFAULT_STORAGE_KEY: DEFAULT_STORAGE_KEY,
    DEFAULT_MAX_ENTRIES: DEFAULT_MAX_ENTRIES,
    DEFAULT_DEBOUNCE_MS: DEFAULT_DEBOUNCE_MS,
    ROUND_TRIP_KEYS: ROUND_TRIP_KEYS,
    createView: createView,
    buildLabel: buildLabel,
    serializeFilters: serializeFilters,
    _escHtml: _escHtml,
    _canonicalFilters: _canonicalFilters,
    _fmtAgo: _fmtAgo,
    _safeParse: _safeParse,
  };
}));