/* MC-309: Lazy-load Craigslist listing photos in the deals table thumbnail column.
 *
 * Background:
 *   - Craigslist search pages don't expose photos (verified in MC-307 self-audit).
 *   - MC-308 added `/api/craigslist/photo?url=<listing_url>` for the detail modal.
 *   - The deals table thumbnail column falls back to a house emoji 🏠 for CL
 *     listings without `image_url` from the scraper.
 *
 * This module replaces the emoji with the actual photo once the row scrolls into
 * view. The server enforces 1 req/sec + 30 fetches per 2hr budget; the client
 * mirrors that with a 250ms throttle (well under the server limit) and a
 * 10 fetches-per-page-load cap (well under the server 30/2hr budget). Failures
 * keep the original placeholder — no flicker, no broken image.
 *
 * Public API:
 *   setupCLPhotoLazyLoad(rootEl?) - scan `rootEl` (default: document) for
 *     `.deal-thumb-fallback.cl-lazy[data-cl-url]` elements and start observing.
 *     Disconnects any prior observer so it can be called repeatedly across
 *     `renderDeals()` invocations.
 *
 * Tunables (exported via `window.__clLazyConfig` for tests):
 *   - throttleMs       (default 250)
 *   - maxFetchesPerRun (default 10)
 *   - rootMargin       (default "120px")
 */
(function () {
  'use strict';

  const DEFAULTS = {
    throttleMs: 250,
    maxFetchesPerRun: 10,
    rootMargin: '120px',
  };

  const cfg = Object.assign({}, DEFAULTS, (window.__clLazyConfig || {}));

  // Per-render mutable state. setupCLPhotoLazyLoad() resets these each call.
  const state = {
    lastFetchAt: 0,
    fetchesThisRun: 0,
    observer: null,
    inFlight: 0,             // count of pending fetchCLPhotoForPlaceholder calls
  };

  function isCraigslistUrl(url) {
    if (typeof url !== 'string') return false;
    return /craigslist\.org\//.test(url);
  }

  /**
   * Replace a placeholder element with an <img> showing the fetched photo.
   * On error: hide the broken img and revert the placeholder to its emoji
   * (no flicker — the emoji was already there before we started).
   */
  function clLazyReplace(placeholder, imageUrl) {
    const parent = placeholder.parentNode;
    if (!parent) return;
    const img = document.createElement('img');
    img.className = 'deal-thumb';
    img.loading = 'lazy';
    img.referrerPolicy = 'no-referrer';
    img.alt = '';
    img.src = imageUrl;
    img.onerror = function () {
      // Broken image: hide it; the original placeholder is still in the DOM
      // (we never removed it), so no flicker.
      this.remove();
      placeholder.classList.remove('cl-loading');
    };
    parent.insertBefore(img, placeholder);
    placeholder.style.display = 'none';
  }

  /**
   * Fetch the photo for one placeholder. Resolves with `true` on success
   * (img swapped in), `false` on any failure (placeholder kept).
   * Throttled via `cfg.throttleMs` between consecutive calls.
   */
  async function fetchCLPhotoForPlaceholder(placeholder) {
    if (!placeholder || !placeholder.getAttribute) return false;
    const url = placeholder.getAttribute('data-cl-url');
    if (!url || !isCraigslistUrl(url)) return false;
    if (typeof fetch !== 'function') return false;

    // Throttle: ensure cfg.throttleMs has passed since the last fetch start.
    const now = Date.now();
    const waitMs = Math.max(0, state.lastFetchAt + cfg.throttleMs - now);
    if (waitMs > 0) {
      await new Promise(function (r) { setTimeout(r, waitMs); });
    }
    state.lastFetchAt = Date.now();
    state.inFlight++;

    if (placeholder.classList) placeholder.classList.add('cl-loading');

    try {
      const resp = await fetch('/api/craigslist/photo?url=' + encodeURIComponent(url));
      if (!resp || !resp.ok) {
        // 400/404/429/502 — silently keep placeholder.
        return false;
      }
      let data;
      try {
        data = await resp.json();
      } catch (_) {
        return false;
      }
      if (!data || !data.image_url) return false;

      // Make sure the placeholder is still in the DOM (user may have re-rendered).
      if (!placeholder.isConnected) return false;

      clLazyReplace(placeholder, data.image_url);
      return true;
    } catch (_) {
      // Network error — keep placeholder.
      return false;
    } finally {
      state.inFlight--;
      if (placeholder.classList) placeholder.classList.remove('cl-loading');
    }
  }

  /**
   * Setup observer + handlers. Safe to call repeatedly — the previous observer
   * is disconnected first. Idempotent if no `[data-cl-url]` placeholders exist.
   */
  function setupCLPhotoLazyLoad(rootEl) {
    // Tear down previous observer (re-renders reset observations).
    if (state.observer && typeof state.observer.disconnect === 'function') {
      state.observer.disconnect();
    }
    state.observer = null;
    state.lastFetchAt = 0;
    state.fetchesThisRun = 0;

    const root = rootEl || (typeof document !== 'undefined' ? document : null);
    if (!root || typeof root.querySelectorAll !== 'function') return;
    // IntersectionObserver may be missing in some test envs (Node) — guard.
    if (typeof IntersectionObserver === 'undefined') return;

    const placeholders = root.querySelectorAll('.deal-thumb-fallback.cl-lazy[data-cl-url]');
    if (!placeholders || placeholders.length === 0) return;

    state.observer = new IntersectionObserver(function (entries) {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const placeholder = entry.target;
        // One-shot: stop observing once intersected.
        if (state.observer) state.observer.unobserve(placeholder);

        if (state.fetchesThisRun >= cfg.maxFetchesPerRun) {
          // Budget exhausted for this render — keep the emoji placeholder.
          continue;
        }
        state.fetchesThisRun++;
        fetchCLPhotoForPlaceholder(placeholder).catch(function () {
          // Swallow — keep placeholder.
        });
      }
    }, { root: null, rootMargin: cfg.rootMargin, threshold: 0.1 });

    for (const p of placeholders) state.observer.observe(p);
  }

  // Expose for browser + Node tests.
  const api = {
    setupCLPhotoLazyLoad: setupCLPhotoLazyLoad,
    fetchCLPhotoForPlaceholder: fetchCLPhotoForPlaceholder,
    isCraigslistUrl: isCraigslistUrl,
    config: cfg,
    // Test-only helpers (intentionally exposed for inspection).
    _state: state,
    _reset: function (overrides) {
      Object.assign(cfg, DEFAULTS, overrides || {});
      state.lastFetchAt = 0;
      state.fetchesThisRun = 0;
      state.inFlight = 0;
      if (state.observer && typeof state.observer.disconnect === 'function') {
        state.observer.disconnect();
      }
      state.observer = null;
    },
  };

  if (typeof window !== 'undefined') {
    window.__clPhotoLazy = api;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})();
