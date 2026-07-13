// MC-351: 'Recently viewed (N)' popover + filter-bar pill.
//
// Builds on MC-350's listing_viewed.js: MC-350 owns the localStorage set of
// "viewed" listing IDs (`rf_viewed_ids` -> {id: viewedAtMs}) and exposes it
// on window.__listingViewed. This module surfaces that data via a
// one-tap popover pinned to the filter bar, so users can re-open a
// recently-toured listing without having to scroll the deals table or
// re-apply a search.
//
// Public API (returned from createView(opts)):
//   init()                                  — currently a no-op (storage read is automatic)
//   getCount()                              — number of viewed ids; mirrors __listingViewed.count()
//   getRecent(n=10)                         — newest-first array of {id, viewedAt}
//   setDeals(deals)                         — populate lookup map so renderEntry can hydrate ids
//   renderEntry(deal, viewedAtMs, nowMs?)   — HTML string for a single popover row
//   attachPopover(triggerEl, containerEl, opts?)  — wire the trigger button to show/hide the popover
//   closePopover()
//   togglePopover()                         — explicit toggle
//   listenStorage(handlerFn)                — cross-tab sync (delegates to MC-350 when present)
//   clearAll()                              — wipes the underlying set; delegates to __listingViewed.clearAll()
//   refresh()                               — force-resync the count badge + popover contents
//
// Standalone fallback: when window.__listingViewed is missing (older
// deployment, test environment, or page loaded before MC-350 script tag),
// the module falls back to reading `rf_viewed_ids` directly so the popover
// still works in isolation. This is the same defensive pattern MC-350
// itself uses for the legacy bare-array storage shape.
//
// Self-contained IIFE. Browser: window.__recentlyViewed. Node tests:
//   module.exports = factory().

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.__recentlyViewed = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {

  const DEFAULT_STORAGE_KEY = 'rf_viewed_ids';
  const DEFAULT_NOW_MS = function () { return Date.now(); };
  const DEFAULT_MAX_ENTRIES = 10;

  // ---------------------------------------------------------------------
  // Pure helpers (testable directly via factory).
  // ---------------------------------------------------------------------

  function _isStringId(id) {
    return typeof id === 'string' && id.length > 0;
  }

  function _escHtml(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function _fmtPrice(price) {
    const n = Number(price);
    if (!isFinite(n) || n <= 0) return '';
    return '$' + Math.round(n).toLocaleString('en-US');
  }

  function _fmtBedsBaths(beds, baths) {
    let bedStr = '';
    if (beds === 0 || beds === '0' || beds === 0.0) {
      bedStr = 'Studio';
    } else if (beds == null || beds === '' || beds === 'None') {
      bedStr = '';
    } else {
      const n = Number(beds);
      bedStr = isFinite(n) && n > 0 ? (n + 'BR') : '';
    }
    let bathStr = '';
    const nb = Number(baths);
    if (isFinite(nb) && nb > 0) {
      bathStr = (bedStr ? ' · ' : '') + nb + 'BA';
    }
    return bedStr + bathStr;
  }

  function _fmtViewedAgo(viewedAtMs, nowMs) {
    if (typeof viewedAtMs !== 'number' || !isFinite(viewedAtMs)) return '';
    const now = (typeof nowMs === 'number' && isFinite(nowMs)) ? nowMs : DEFAULT_NOW_MS();
    const deltaSec = Math.max(0, Math.floor((now - viewedAtMs) / 1000));
    if (deltaSec < 60) return 'just now';
    if (deltaSec < 3600) return Math.floor(deltaSec / 60) + 'm ago';
    if (deltaSec < 86400) return Math.floor(deltaSec / 3600) + 'h ago';
    return Math.floor(deltaSec / 86400) + 'd ago';
  }

  // ---------------------------------------------------------------------
  // Storage fallback. When window.__listingViewed is unavailable we parse
  // the localStorage value directly. Mirrors MC-350's _safeParse logic so
  // the shape contract is the same.
  // ---------------------------------------------------------------------

  function _safeParseStorage(raw) {
    if (typeof raw !== 'string' || !raw) return {};
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        const out = {};
        Object.keys(parsed).forEach(function (k) {
          if (_isStringId(k) && typeof parsed[k] === 'number'
              && isFinite(parsed[k]) && parsed[k] > 0) {
            out[k] = parsed[k];
          }
        });
        return out;
      }
      if (Array.isArray(parsed)) {
        const out = {};
        parsed.forEach(function (k) {
          if (_isStringId(k)) out[k] = DEFAULT_NOW_MS();
        });
        return out;
      }
    } catch (e) { /* swallow */ }
    return {};
  }

  function _readRawState(storage, storageKey) {
    if (!storage || typeof storage.getItem !== 'function') return {};
    try {
      return _safeParseStorage(storage.getItem(storageKey));
    } catch (e) {
      return {};
    }
  }

  // ---------------------------------------------------------------------
  // createView() instance factory.
  // ---------------------------------------------------------------------

  function createView(opts) {
    opts = opts || {};
    const storageKey = opts.storageKey || DEFAULT_STORAGE_KEY;
    const storage = opts.storage
      || (typeof root !== 'undefined' && root && root.localStorage)
      || (typeof globalThis !== 'undefined' && globalThis && globalThis.localStorage) || null;
    const win = opts.window
      || (typeof root !== 'undefined' && root && root.addEventListener ? root : null);
    const doc = opts.document
      || (typeof root !== 'undefined' && root && root.document)
      || (typeof globalThis !== 'undefined' && globalThis && globalThis.document) || null;

    // When MC-350 is loaded, prefer its public API for the canonical state.
    // Lookup order: explicit opts.lv > window root > globalThis (so tests can
    // inject a mock lv via global.__listingViewed without reordering module
    // evaluation). When none is present the module falls back to direct
    // localStorage parsing — same defensive pattern MC-350 uses.
    const lv = (opts && opts.lv)
      || (typeof root !== 'undefined' && root && root.__listingViewed)
      || (typeof globalThis !== 'undefined' && globalThis && globalThis.__listingViewed)
      || null;

    // Local cache of "id -> deal" so renderEntry can hydrate ids present in
    // the viewed set. Populated by setDeals() before the popover opens.
    let _dealsById = {};
    let _dealsList = [];

    // Popover attachment state. attachPopover() populates these.
    let _triggerEl = null;
    let _containerEl = null;
    let _outsideClickHandler = null;
    let _keydownHandler = null;
    let _viewedAllFirstId = null;

    function _getStateFromLv() {
      if (lv && typeof lv.getAllViewed === 'function') return lv.getAllViewed();
      const state = _readRawState(storage, storageKey);
      return Object.keys(state).map(function (k) {
        return { id: k, viewedAt: state[k] };
      }).sort(function (a, b) { return b.viewedAt - a.viewedAt; });
    }

    function _getCountFromLv() {
      if (lv && typeof lv.count === 'function') return lv.count();
      const state = _readRawState(storage, storageKey);
      return Object.keys(state).length;
    }

    function getCount() {
      return _getCountFromLv();
    }

    function getRecent(n) {
      const cap = (typeof n === 'number' && n > 0) ? n : DEFAULT_MAX_ENTRIES;
      return _getStateFromLv().slice(0, cap);
    }

    function setDeals(deals) {
      _dealsList = Array.isArray(deals) ? deals : [];
      _dealsById = {};
      _dealsList.forEach(function (d) {
        if (!d) return;
        const id = d.listing_id || d.link || d.id || '';
        if (_isStringId(id)) _dealsById[id] = d;
      });
    }

    // -----------------------------------------------------------------
    // renderEntry — pure HTML rendering for a single popover row.
    // Returns '' when deal is null/missing a listing_id so callers can
    // filter falsy entries.
    // -----------------------------------------------------------------
    function renderEntry(deal, viewedAtMs, nowMs) {
      if (!deal) return '';
      const id = deal.listing_id || deal.link || deal.id || '';
      if (!_isStringId(id)) return '';

      const safeId = _escHtml(id);
      // Only emit an <img> for safe http(s) image URLs. javascript:/data:
      // URLs from listing data must NEVER make it into a src attribute.
      const rawImg = (deal.image_url && typeof deal.image_url === 'string') ? deal.image_url : '';
      const safeImgUrl = /^https?:\/\//i.test(rawImg) ? _escHtml(rawImg) : '';
      const thumb = safeImgUrl
        ? ('<img class="rv-thumb-img" src="' + safeImgUrl + '" alt="" loading="lazy" width="48" '
            + 'height="36" onerror="this.style.display=' + "'none'" + ';" />')
        : '';
      const thumbFallback = '<div class="rv-thumb-fallback">\uD83C\uDFE0</div>';

      const priceStr = _fmtPrice(deal.price);
      const nbhd = _escHtml(deal.neighbourhood || '');
      const bedsBaths = _escHtml(_fmtBedsBaths(deal.beds, deal.baths));

      let pctChip = '';
      const pct = Number(deal.pct_under);
      if (isFinite(pct) && pct > 0) {
        const pctStr = deal.pct_under_fmt || (pct.toFixed(1) + '%');
        pctChip = '<span class="rv-pct-chip">' + _escHtml(pctStr) + ' under</span>';
      }

      const ago = _fmtViewedAgo(viewedAtMs, nowMs);
      const viewedText = ago ? ('<span class="rv-viewed-ago">viewed ' + _escHtml(ago) + '</span>') : '';

      return (
        '<div class="rv-entry" data-listing-id="' + safeId + '">' +
          '<div class="rv-thumb">' + thumb + thumbFallback + '</div>' +
          '<div class="rv-body">' +
            '<div class="rv-price-line">' + (priceStr || '&nbsp;') + pctChip + '</div>' +
            '<div class="rv-meta">' + nbhd + (nbhd && bedsBaths ? ' · ' : '') + bedsBaths + '</div>' +
            viewedText +
          '</div>' +
          '<a class="rv-open-link" href="/d/' + encodeURIComponent(id) + '" target="_blank" '
            + 'rel="noopener noreferrer">Open deal \u2192</a>' +
        '</div>'
      );
    }

    // -----------------------------------------------------------------
    // Popover lifecycle.
    // -----------------------------------------------------------------
    function _findDealById(id) {
      if (!id) return null;
      if (_dealsById[id]) return _dealsById[id];
      // Fallback: linear scan (small set; cheap).
      for (let i = 0; i < _dealsList.length; i++) {
        const d = _dealsList[i];
        if (d && (d.listing_id === id || d.link === id)) return d;
      }
      return null;
    }

    function _buildEntriesHtml(nowMs) {
      const recent = getRecent(DEFAULT_MAX_ENTRIES);
      if (!recent.length) {
        return '<div class="rv-empty">You haven\'t marked any listings viewed yet</div>';
      }
      const rows = [];
      for (let i = 0; i < recent.length; i++) {
        const item = recent[i];
        if (!item || !item.id) continue;
        const html = renderEntry(_findDealById(item.id), item.viewedAt, nowMs);
        // Render entries even when the deal data is missing — show a small
        // placeholder so the user can still see the id was viewed.
        if (html) {
          rows.push(html);
        } else {
          rows.push(
            '<div class="rv-entry rv-entry--missing" data-listing-id="' + _escHtml(item.id) + '">' +
              '<div class="rv-thumb"><div class="rv-thumb-fallback">\uD83C\uDFE0</div></div>' +
              '<div class="rv-body">' +
                '<div class="rv-price-line">Listing ' + _escHtml(item.id.slice(0, 18)) + '\u2026</div>' +
                '<div class="rv-meta">No longer in current results</div>' +
              '</div>' +
              '<span class="rv-open-link rv-open-link--muted">stale</span>' +
            '</div>'
          );
        }
      }
      let html = rows.join('');
      _viewedAllFirstId = recent[0] && recent[0].id ? recent[0].id : null;
      const clearCount = _getCountFromLv();
      html += (
        '<div class="rv-footer">' +
          '<button type="button" class="rv-clear-btn">Clear all</button>' +
          (clearCount > DEFAULT_MAX_ENTRIES
            ? '<span class="rv-overflow-note">' + clearCount + ' total \u00b7 showing last '
                + DEFAULT_MAX_ENTRIES + '</span>'
            : '') +
          '<a href="#" class="rv-view-all" data-listing-id="' + _escHtml(_viewedAllFirstId || '') + '">View all</a>' +
        '</div>'
      );
      return html;
    }

    function _openPopover() {
      if (!_containerEl) return false;
      const now = DEFAULT_NOW_MS();
      const entriesHtml = _buildEntriesHtml(now);
      _containerEl.innerHTML = (
        '<button type="button" class="rv-close" aria-label="Close popover">\u00d7</button>' +
        '<div class="rv-header">Recently viewed</div>' +
        '<div class="rv-entries">' + entriesHtml + '</div>'
      );
      _containerEl.setAttribute('data-state', 'open');
      _containerEl.style.display = '';

      // Position the popover under the trigger button. We default to
      // `position: fixed` so the popover escapes any ancestor with
      // overflow:hidden and stays attached to the viewport. If a caller
      // prefers absolute positioning, they can override the popover's
      // style.top/left in CSS before attaching.
      if (_triggerEl && typeof _triggerEl.getBoundingClientRect === 'function'
          && typeof _containerEl.getBoundingClientRect === 'function') {
        try {
          const tr = _triggerEl.getBoundingClientRect();
          const pr = _containerEl.getBoundingClientRect();
          const top = Math.max(8, tr.bottom + 6);
          // Right-align the popover with the right edge of the trigger so
          // short filters don't push the popover off-screen.
          const left = Math.max(8, Math.min(
            (typeof win !== 'undefined' && win && win.innerWidth ? win.innerWidth : 1024) - pr.width - 8,
            tr.right - pr.width
          ));
          _containerEl.style.position = 'fixed';
          _containerEl.style.top = top + 'px';
          _containerEl.style.left = left + 'px';
        } catch (e) { /* swallow - fall back to default position */ }
      }

      // Wire up close button.
      const closeBtn = _containerEl.querySelector('.rv-close');
      if (closeBtn) closeBtn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        closePopover();
      });

      // Wire up clear button.
      const clearBtn = _containerEl.querySelector('.rv-clear-btn');
      if (clearBtn) clearBtn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const globalRoot = (typeof root !== 'undefined') ? root : null;
        const proceed = !globalRoot || typeof globalRoot.confirm !== 'function'
          ? true
          : globalRoot.confirm('Forget all viewed listings?');
        if (proceed) {
          clearAll();
          closePopover();
        }
      });

      // Wire up view-all link (open the most-recent deal in a new tab).
      const viewAll = _containerEl.querySelector('.rv-view-all');
      if (viewAll) viewAll.addEventListener('click', function (ev) {
        ev.preventDefault();
        const firstId = viewAll.getAttribute('data-listing-id');
        const globalRoot = (typeof root !== 'undefined') ? root : null;
        if (firstId && globalRoot && typeof globalRoot.open === 'function') {
          globalRoot.open('/d/' + encodeURIComponent(firstId), '_blank', 'noopener,noreferrer');
          closePopover();
        }
      });

      // Open-entry handler: clicking the entry also navigates.
      const entryEls = _containerEl.querySelectorAll('.rv-entry');
      entryEls.forEach(function (entryEl) {
        entryEl.addEventListener('click', function (ev) {
          // Don't double-fire when the user clicks the explicit "Open deal" link.
          if (ev.target && ev.target.tagName === 'A') return;
          const id = entryEl.getAttribute('data-listing-id');
          if (id && typeof root !== 'undefined' && root.open) {
            root.open('/d/' + encodeURIComponent(id), '_blank', 'noopener,noreferrer');
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
        // Use 'click' (not 'mousedown') so users can finish their click.
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
      if (_containerEl.getAttribute('data-state') === 'open') {
        closePopover();
      } else {
        _openPopover();
      }
    }

    function attachPopover(triggerEl, containerEl, options) {
      if (!triggerEl || !containerEl) return api;
      _triggerEl = triggerEl;
      _containerEl = containerEl;
      const opts = options || {};

      // Toggle on trigger click. We use a click handler bound to the
      // button directly; the outside-click handler we install later
      // dismisses on any other click.
      triggerEl.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        togglePopover();
      });

      // Escape-key dismissal (process-wide; only active when popover is
      // open in practice because closePopover is the only consumer).
      if (win && typeof win.addEventListener === 'function') {
        _keydownHandler = function (ev) {
          if (ev && ev.key === 'Escape' && _containerEl
              && _containerEl.getAttribute('data-state') === 'open') {
            closePopover();
          }
        };
        win.addEventListener('keydown', _keydownHandler);
      }

      // Optional getDeals refresh hook — when provided, callers can
      // re-fetch /api/deals right before opening so the popover always
      // shows the freshest data.
      api._getDealsHook = (typeof opts.getDeals === 'function') ? opts.getDeals : null;

      refresh();
      return api;
    }

    function listenStorage(handler) {
      if (typeof handler !== 'function') return api;
      // Delegate to MC-350's listener so we don't double-wire storage
      // events and so the same source of truth notifies both modules.
      if (lv && typeof lv.listenStorage === 'function') {
        lv.listenStorage(handler);
      } else if (win && typeof win.addEventListener === 'function'
                 && !win.__rv_storage_wired) {
        win.addEventListener('storage', function (ev) {
          if (!ev || ev.key !== storageKey) return;
          try { handler({ type: 'storage', key: storageKey }); } catch (e) { /* swallow */ }
        });
        win.__rv_storage_wired = true;
      }
      return api;
    }

    function clearAll() {
      if (lv && typeof lv.clearAll === 'function') {
        lv.clearAll();
      } else if (storage && typeof storage.setItem === 'function') {
        try { storage.setItem(storageKey, '{}'); } catch (e) { /* swallow */ }
      }
      // Best-effort: re-render an empty popover so the user sees the
      // empty state if the popover is currently open.
      if (_containerEl && _containerEl.getAttribute('data-state') === 'open') {
        _openPopover();
      }
    }

    function refresh() {
      const n = _getCountFromLv();
      if (doc && typeof doc.getElementById === 'function') {
        const badge = doc.getElementById('recent_viewed_count');
        if (badge) badge.textContent = String(n);
        // Disable the pill when there are zero entries (forces user to
        // mark at least one listing before the popover does anything).
        if (_triggerEl) _triggerEl.disabled = (n === 0);
      }
      if (_containerEl && _containerEl.getAttribute('data-state') === 'open') {
        _openPopover();
      }
    }

    const api = {
      init: function () { return api; },
      getCount: getCount,
      getRecent: getRecent,
      setDeals: setDeals,
      renderEntry: renderEntry,
      attachPopover: attachPopover,
      closePopover: closePopover,
      togglePopover: togglePopover,
      listenStorage: listenStorage,
      clearAll: clearAll,
      refresh: refresh,
      // Exposed for tests
      _escHtml: _escHtml,
      _fmtPrice: _fmtPrice,
      _fmtBedsBaths: _fmtBedsBaths,
      _fmtViewedAgo: _fmtViewedAgo,
      _safeParseStorage: _safeParseStorage,
      _storageKey: storageKey,
    };
    return api;
  }

  return {
    DEFAULT_STORAGE_KEY: DEFAULT_STORAGE_KEY,
    DEFAULT_MAX_ENTRIES: DEFAULT_MAX_ENTRIES,
    createView: createView,
    _escHtml: _escHtml,
    _fmtPrice: _fmtPrice,
    _fmtBedsBaths: _fmtBedsBaths,
    _fmtViewedAgo: _fmtViewedAgo,
    _safeParseStorage: _safeParseStorage,
  };
}));
