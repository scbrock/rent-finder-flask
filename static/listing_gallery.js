/* MC-312: Listing photo gallery carousel — multi-image viewer for the detail modal.
 * Self-contained IIFE. Renders arrows + thumbnail strip + counter when 2+ photos.
 * Falls back to a single photo (no controls) when only 1 photo is present.
 * Exported as window.__listingGallery for browser use and module.exports for Node tests.
 *
 * Public API:
 *   renderGallery(images, targetEl, opts) — populate targetEl with the carousel UI.
 *   goTo(index) — switch to a specific image index.
 *   next() / prev() — cycle through images.
 *
 * Markup produced:
 *   <div class="listing-gallery" data-count="N">
 *     <button class="lg-prev">‹</button>
 *     <img class="lg-main" />
 *     <button class="lg-next">›</button>
 *     <div class="lg-counter">1 / 5</div>
 *     <div class="lg-thumbs">[…thumbnails…]</div>
 *   </div>
 */
(function (root) {
  'use strict';

  var state = {
    images: [],
    index: 0,
    targetEl: null,
    onChange: null  // optional callback after each image change (for tests)
  };

  function clamp(i, n) {
    if (n <= 0) return 0;
    if (i < 0) return 0;
    if (i >= n) return n - 1;
    return i;
  }

  function setIndex(i) {
    if (!state.images.length) return;
    var n = state.images.length;
    var next = clamp(i, n);
    if (next === state.index) return;
    state.index = next;
    paint();
    if (typeof state.onChange === 'function') {
      try { state.onChange(next, state.images[next]); } catch (e) {}
    }
  }

  function paint() {
    if (!state.targetEl) return;
    var main = state.targetEl.querySelector('.lg-main');
    var counter = state.targetEl.querySelector('.lg-counter');
    var thumbs = state.targetEl.querySelectorAll('.lg-thumb');
    if (main) main.src = state.images[state.index] || '';
    if (counter && state.images.length > 1) {
      counter.textContent = (state.index + 1) + ' / ' + state.images.length;
    }
    thumbs.forEach(function (t, i) {
      if (i === state.index) t.classList.add('lg-thumb-active');
      else t.classList.remove('lg-thumb-active');
    });
  }

  function build(images, opts) {
    opts = opts || {};
    state.images = images.slice();
    state.index = clamp(opts.startIndex || 0, state.images.length);

    var wrap = document.createElement('div');
    wrap.className = 'listing-gallery';
    wrap.setAttribute('data-count', String(state.images.length));

    if (state.images.length === 0) {
      // No images — render an empty block so the surrounding modal doesn't shift
      wrap.style.minHeight = '0';
      return wrap;
    }

    var main = document.createElement('img');
    main.className = 'lg-main';
    main.alt = opts.alt || '';
    main.loading = 'lazy';
    main.referrerPolicy = 'no-referrer';
    main.style.cssText = 'width:100%;max-height:280px;object-fit:cover;border-radius:8px;background:#f1f5f3;display:block;';
    main.onerror = function () { wrap.style.display = 'none'; };
    wrap.appendChild(main);

    // Prev / Next arrows (only shown when 2+)
    if (state.images.length > 1) {
      var prev = document.createElement('button');
      prev.type = 'button';
      prev.className = 'lg-prev';
      prev.setAttribute('aria-label', 'Previous photo');
      prev.textContent = '\u2039';  // ‹
      prev.onclick = function (e) { e.preventDefault(); state.index = clamp(state.index - 1, state.images.length); paint(); emit(); };
      wrap.appendChild(prev);

      var next = document.createElement('button');
      next.type = 'button';
      next.className = 'lg-next';
      next.setAttribute('aria-label', 'Next photo');
      next.textContent = '\u203A';  // ›
      next.onclick = function (e) { e.preventDefault(); state.index = clamp(state.index + 1, state.images.length); paint(); emit(); };
      wrap.appendChild(next);

      var counter = document.createElement('div');
      counter.className = 'lg-counter';
      counter.textContent = (state.index + 1) + ' / ' + state.images.length;
      wrap.appendChild(counter);

      // Thumbnail strip
      var strip = document.createElement('div');
      strip.className = 'lg-thumbs';
      state.images.forEach(function (url, i) {
        var t = document.createElement('img');
        t.className = 'lg-thumb';
        t.src = url;
        t.alt = 'Photo ' + (i + 1);
        t.loading = 'lazy';
        t.referrerPolicy = 'no-referrer';
        t.onerror = function () { t.style.display = 'none'; };
        t.onclick = function (e) {
          e.preventDefault();
          state.index = i;
          paint();
          emit();
        };
        strip.appendChild(t);
      });
      wrap.appendChild(strip);
    }

    // Set main image src via paint
    paint();
    return wrap;
  }

  function emit() {
    if (typeof state.onChange === 'function') {
      try { state.onChange(state.index, state.images[state.index]); } catch (e) {}
    }
  }

  // Public API --------------------------------------------------------------

  function renderGallery(images, targetEl, opts) {
    state.targetEl = targetEl;
    state.onChange = (opts && opts.onChange) || null;
    var node = build(images, opts);
    // Replace contents of targetEl with the carousel
    while (targetEl.firstChild) targetEl.removeChild(targetEl.firstChild);
    targetEl.appendChild(node);
    targetEl.style.display = state.images.length > 0 ? 'block' : 'none';
    return node;
  }

  function next() { setIndex(state.index + 1); }
  function prev() { setIndex(state.index - 1); }
  function goTo(i) { setIndex(i); }

  function getState() {
    return {
      images: state.images.slice(),
      index: state.index,
      count: state.images.length
    };
  }

  // Expose ------------------------------------------------------------------

  var api = {
    renderGallery: renderGallery,
    next: next,
    prev: prev,
    goTo: goTo,
    getState: getState
  };

  if (typeof window !== 'undefined') {
    window.__listingGallery = api;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (root && typeof root === 'object') {
    root.__listingGallery = api;
  }
})(typeof self !== 'undefined' ? self : (typeof window !== 'undefined' ? window : null));
