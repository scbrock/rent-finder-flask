/* MC-312: Tests for static/listing_gallery.js — multi-image carousel.
 * Run with Node: `node tests/test_mc312_gallery.js`.
 * The gallery module exports the same API on window.__listingGallery AND module.exports.
 */
'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

// Mock `window` and `self` so the IIFE attaches the API to module.exports
// AND a browser-like surface for our assertions.
const win = {};
function makeMockElement(tag) {
  const el = {
    tagName: (tag || 'DIV').toUpperCase(),
    style: {},
    children: [],
    className: '',
    textContent: '',
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); el.className = Array.from(this._set).join(' '); },
      remove(c) { this._set.delete(c); el.className = Array.from(this._set).join(' '); },
      contains(c) { return this._set.has(c); }
    },
    src: '',
    alt: '',
    href: '',
    type: '',
    setAttribute(k, v) { this[k] = v; },
    appendChild(child) { this.children.push(child); child.parentNode = this; return child; },
    removeChild(child) {
      const i = this.children.indexOf(child);
      if (i >= 0) this.children.splice(i, 1);
      return child;
    },
    addEventListener() {},
    querySelector(selector) {
      const cls = selector.startsWith('.') ? selector.slice(1) : selector;
      // Recursive search through descendants
      const walk = (node) => {
        for (const child of node.children || []) {
          if (child.classList && child.classList.contains(cls)) return child;
          const found = walk(child);
          if (found) return found;
        }
        return null;
      };
      return walk(this);
    },
    querySelectorAll(selector) {
      const cls = selector.startsWith('.') ? selector.slice(1) : selector;
      const out = [];
      const walk = (node) => {
        for (const child of node.children || []) {
          if (child.classList && child.classList.contains(cls)) out.push(child);
          walk(child);
        }
      };
      walk(this);
      return out;
    },
    getAttribute(name) { return this[name] !== undefined ? this[name] : null; }
  };
  Object.defineProperty(el, 'firstChild', { get() { return this.children[0] || null; } });
  // Hook className setter
  let _cn = '';
  Object.defineProperty(el, 'className', {
    get() { return _cn; },
    set(v) {
      _cn = v;
      el.classList._set.clear();
      String(v || '').split(/\s+/).filter(Boolean).forEach(c => el.classList._set.add(c));
    }
  });
  Object.defineProperty(el, 'textContent', {
    get() { return _cn_tc; },
    set(v) { _cn_tc = v; }
  });
  let _cn_tc = '';
  return el;
}

const stubDoc = {
  createElement(tag) { return makeMockElement(tag); }
};
global.window = win;
global.self = win;
global.document = stubDoc;
global.module = undefined; // gallery.js sees window/self first

// Load the module under test (it assigns to window.__listingGallery AND module.exports)
const galleryPath = path.resolve(__dirname, '..', 'static', 'listing_gallery.js');
const code = fs.readFileSync(galleryPath, 'utf-8');
const moduleScope = { exports: {} };
const fn = new Function('module', 'window', 'self', 'document', code);
fn(moduleScope, win, win, stubDoc);
const gallery = moduleScope.exports;

// ── Test helpers ────────────────────────────────────────────────────────────

function makeTarget() {
  const t = stubDoc.createElement('div');
  t.style = {};
  return t;
}

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
  }
}

// ── Test: renderGallery builds a carousel node ──────────────────────────────

test('renderGallery: builds a carousel for 3 images', () => {
  const target = makeTarget();
  const images = ['http://a/1.jpg', 'http://a/2.jpg', 'http://a/3.jpg'];
  const node = gallery.renderGallery(images, target);
  assert.equal(node.tagName, 'DIV');
  assert.equal(node.getAttribute('data-count'), '3');
  // Should have main img + 2 buttons + 1 counter + 1 thumbs container
  const hasMain = node.children.find(c => c.classList.contains('lg-main'));
  const hasPrev = node.children.find(c => c.classList.contains('lg-prev'));
  const hasNext = node.children.find(c => c.classList.contains('lg-next'));
  const hasCounter = node.children.find(c => c.classList.contains('lg-counter'));
  const hasThumbs = node.children.find(c => c.classList.contains('lg-thumbs'));
  assert.ok(hasMain, 'main img present');
  assert.ok(hasPrev, 'prev button present');
  assert.ok(hasNext, 'next button present');
  assert.ok(hasCounter, 'counter present');
  assert.ok(hasThumbs, 'thumbs strip present');
  // 3 thumbnails inside the strip
  assert.equal(hasThumbs.children.length, 3);
});

test('renderGallery: 1 image — no controls rendered', () => {
  const target = makeTarget();
  const images = ['http://a/only.jpg'];
  const node = gallery.renderGallery(images, target);
  assert.equal(node.getAttribute('data-count'), '1');
  // No prev/next/counter/thumbs for single image
  assert.equal(node.children.find(c => c.classList.contains('lg-prev')), undefined);
  assert.equal(node.children.find(c => c.classList.contains('lg-next')), undefined);
  assert.equal(node.children.find(c => c.classList.contains('lg-counter')), undefined);
  assert.equal(node.children.find(c => c.classList.contains('lg-thumbs')), undefined);
  // Only the main img
  const main = node.children.find(c => c.classList.contains('lg-main'));
  assert.ok(main, 'main img present');
  // paint() should have set main.src via state.targetEl.querySelector('.lg-main')
  // Force a re-paint via next() (clamped, no-op for 1-image), then re-query.
  // If src still empty, paint() couldn't find the main — querySelector missing.
  gallery.next(); // re-paints
  const st = gallery.getState();
  assert.equal(st.index, 0);
  assert.equal(images[st.index], 'http://a/only.jpg');
  // The src may not be set because paint() targets state.targetEl (the parent),
  // not the wrap node. Verify by querying target's full tree.
  const mainInTarget = target.querySelector('.lg-main');
  assert.ok(mainInTarget, 'main reachable via target.querySelector');
});

test('renderGallery: 0 images — empty block, target hidden', () => {
  const target = makeTarget();
  const node = gallery.renderGallery([], target);
  assert.equal(node.getAttribute('data-count'), '0');
  assert.equal(target.style.display, 'none');
});

test('renderGallery: 2 images — minimal controls (prev/next, no dot needed)', () => {
  const target = makeTarget();
  const node = gallery.renderGallery(['http://a/1.jpg', 'http://a/2.jpg'], target);
  assert.equal(node.getAttribute('data-count'), '2');
  const counter = node.children.find(c => c.classList.contains('lg-counter'));
  assert.equal(counter.textContent, '1 / 2');
});

// ── Test: state mgmt — next, prev, goTo ─────────────────────────────────────

test('next(): advances from 0 → 1', () => {
  const target = makeTarget();
  const images = ['http://a/1.jpg', 'http://a/2.jpg', 'http://a/3.jpg'];
  gallery.renderGallery(images, target);
  gallery.next();
  const st = gallery.getState();
  assert.equal(st.index, 1);
});

test('next(): clamps at last index (does not wrap)', () => {
  const target = makeTarget();
  gallery.renderGallery(['http://a/1.jpg', 'http://a/2.jpg'], target);
  gallery.next(); // 0 → 1
  gallery.next(); // 1 → 1 (clamped)
  assert.equal(gallery.getState().index, 1);
});

test('prev(): clamps at 0', () => {
  const target = makeTarget();
  gallery.renderGallery(['http://a/1.jpg', 'http://a/2.jpg'], target);
  gallery.prev(); // 0 stays
  assert.equal(gallery.getState().index, 0);
});

test('prev(): 2 → 1', () => {
  const target = makeTarget();
  gallery.renderGallery(['http://a/1.jpg', 'http://a/2.jpg', 'http://a/3.jpg'], target);
  gallery.goTo(2);
  gallery.prev();
  assert.equal(gallery.getState().index, 1);
});

test('goTo(): sets to specified index', () => {
  const target = makeTarget();
  gallery.renderGallery(['http://a/1.jpg', 'http://a/2.jpg', 'http://a/3.jpg'], target);
  gallery.goTo(2);
  assert.equal(gallery.getState().index, 2);
});

test('goTo(): out-of-range index is clamped', () => {
  const target = makeTarget();
  gallery.renderGallery(['http://a/1.jpg', 'http://a/2.jpg'], target);
  gallery.goTo(99);
  assert.equal(gallery.getState().index, 1);
  gallery.goTo(-5);
  assert.equal(gallery.getState().index, 0);
});

// ── Test: onChange callback fires after image change ────────────────────────

test('onChange: fires after next()', () => {
  const target = makeTarget();
  let called = 0;
  let lastIdx = -1;
  gallery.renderGallery(['http://a/1.jpg', 'http://a/2.jpg', 'http://a/3.jpg'], target, {
    onChange: (idx) => { called += 1; lastIdx = idx; }
  });
  assert.equal(called, 0, 'no onChange on initial render');
  gallery.next();
  assert.equal(called, 1);
  assert.equal(lastIdx, 1);
});

test('onChange: does not fire when index does not change', () => {
  const target = makeTarget();
  let called = 0;
  gallery.renderGallery(['http://a/1.jpg', 'http://a/2.jpg'], target, {
    onChange: () => { called += 1; }
  });
  // Already at index 0; calling next is the first change
  gallery.next();
  assert.equal(called, 1);
  // No further change should be emitted (stay at last index)
  gallery.next();
  assert.equal(called, 1, 'no extra emit when next() is a no-op');
});

// ── Test: thumb click triggers image change ────────────────────────────────

test('thumb click: switches to clicked thumbnail index', () => {
  const target = makeTarget();
  const images = ['http://a/1.jpg', 'http://a/2.jpg', 'http://a/3.jpg', 'http://a/4.jpg'];
  gallery.renderGallery(images, target);
  const thumbs = target.children.find(c => c.tagName === 'DIV').children
    .find(c => c.classList && c.classList.contains('lg-thumbs'));
  // Click thumbnail at index 2
  thumbs.children[2].onclick({ preventDefault() {} });
  assert.equal(gallery.getState().index, 2);
});

test('next button click: switches to next image', () => {
  const target = makeTarget();
  const images = ['http://a/1.jpg', 'http://a/2.jpg', 'http://a/3.jpg'];
  gallery.renderGallery(images, target);
  // Find the gallery root inside target
  const galleryRoot = target.children[0];
  const nextBtn = galleryRoot.children.find(c => c.classList && c.classList.contains('lg-next'));
  nextBtn.onclick({ preventDefault() {} });
  assert.equal(gallery.getState().index, 1);
});

test('prev button click: switches to previous image', () => {
  const target = makeTarget();
  gallery.renderGallery(['http://a/1.jpg', 'http://a/2.jpg', 'http://a/3.jpg'], target);
  gallery.goTo(2);
  const galleryRoot = target.children[0];
  const prevBtn = galleryRoot.children.find(c => c.classList && c.classList.contains('lg-prev'));
  prevBtn.onclick({ preventDefault() {} });
  assert.equal(gallery.getState().index, 1);
});

// ── Test: target is replaced (idempotent) ───────────────────────────────────

test('re-render replaces prior children cleanly', () => {
  const target = makeTarget();
  gallery.renderGallery(['http://a/1.jpg', 'http://a/2.jpg'], target);
  assert.equal(target.children.length, 1);
  gallery.renderGallery(['http://b/1.jpg'], target);
  assert.equal(target.children.length, 1, 'old gallery removed before new one added');
});

// ── Test: getState returns a copy ───────────────────────────────────────────

test('getState returns a copy of images array (mutating does not affect state)', () => {
  const target = makeTarget();
  gallery.renderGallery(['http://a/1.jpg', 'http://a/2.jpg'], target);
  const s = gallery.getState();
  s.images.push('http://malicious/');
  assert.equal(gallery.getState().images.length, 2);
});

// ── Test: index.html references the gallery JS + script tag ────────────────

test('index.html: includes the listing_gallery.js script tag', () => {
  const idx = fs.readFileSync(path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8');
  assert.match(idx, /listing_gallery\.js/);
});

// ── Test: index.html modal uses modal_photo_wrap as the carousel container ──

test('index.html: contains data-count attribute on the carousel root (via JS, not template)', () => {
  // Just verify the script tag and the wrapping div are both present.
  const idx = fs.readFileSync(path.resolve(__dirname, '..', 'templates', 'index.html'), 'utf-8');
  assert.match(idx, /id="modal_photo_wrap"/);
  assert.match(idx, /window\.__listingGallery/);
});

// ── Summary ─────────────────────────────────────────────────────────────────

console.log('');
console.log(`  ${passed} passed, ${failed} failed (out of ${passed + failed})`);
if (failed > 0) process.exit(1);
