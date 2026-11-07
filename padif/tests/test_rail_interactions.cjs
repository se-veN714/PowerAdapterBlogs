// Run with: node padif/tests/test_rail_interactions.cjs
// Exercise the shipped script's event and geometry contracts without a browser.
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { runInNewContext } = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');

const script = readFileSync(join(__dirname, '../static/padif/padif.js'), 'utf8');

function setup({ saved = null, graphEnabled = false, editorOpen = false } = {}) {
  const editorPanel = { open: editorOpen };
  const clicks = [];
  const frames = [];
  const scrolls = [];
  const store = new Map();
  if (saved) store.set('padif.rail.navigation', JSON.stringify(saved));
  const body = { hidden: false };
  const head = { hidden: true };
  const paths = [];
  const card = {
    dataset: { expanded: 'true' },
    classList: { contains: (name) => name === 'is-selected' },
    querySelector: (selector) => selector === 'strong' ? { textContent: 'opening' } : head,
    getBoundingClientRect: () => ({ left: 140, top: 80 }),
  };
  const attributes = new Map([['aria-controls', 'branch-body'], ['aria-expanded', 'true']]);
  const toggle = {
    dataset: { railFocus: 'branch-2-toggle' },
    textContent: '−',
    focusCalls: [],
    getAttribute: (key) => attributes.get(key),
    setAttribute: (key, value) => attributes.set(key, value),
    closest: (selector) => selector === '[data-rail-toggle]' ? toggle : selector === '[data-rail-branch]' ? card : null,
    focus(options) { this.focusCalls.push(options); },
    getBoundingClientRect: () => ({ top: 180 }),
  };
  const link = {
    href: 'http://localhost/padif/documents/1/?branch=opening',
    dataset: { railFocus: 'branch-2-toggle' },
    closest: (selector) => selector === 'a[data-rail-navigation]' ? link : null,
    getBoundingClientRect: () => ({ top: 220 }),
  };
  const svg = {
    setAttribute() {},
    replaceChildren(...children) { paths.splice(0, paths.length, ...children); },
  };
  const graph = {
    querySelector: () => svg,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 300, height: 400 }),
    querySelectorAll: () => [{
      querySelector: () => ({ getBoundingClientRect: () => ({ left: 100, top: 20, width: 8, height: 8 }) }),
      querySelectorAll: () => [card],
    }],
    classList: { add() {} },
    addEventListener() {},
  };
  const rail = {
    querySelector: (selector) => selector === '[data-rail-graph]' ? (graphEnabled ? graph : null) : toggle,
    querySelectorAll: () => [toggle],
    addEventListener: (type, fn) => { if (type === 'click') clicks.push(fn); },
  };
  const window = {
    location: { origin: 'http://localhost', pathname: '/padif/documents/1/', search: '?branch=main', href: 'http://localhost/padif/documents/1/?branch=main' },
    sessionStorage: { getItem: (key) => store.get(key), setItem: (key, value) => store.set(key, value), removeItem: (key) => store.delete(key) },
    requestAnimationFrame: (fn) => { frames.push(fn); return frames.length; },
    scrollY: 50,
    scrollTo: (...args) => scrolls.push(args),
    addEventListener() {},
    setTimeout() {},
  };
  if (saved) window.location.search = saved.search;
  const document = {
    querySelector: (selector) => selector === '.version-rail' ? rail : selector === '.editor-panel' ? editorPanel : null,
    querySelectorAll: () => [],
    getElementById: () => body,
    createElementNS: () => ({ attributes: {}, setAttribute(key, value) { this.attributes[key] = value; } }),
    body: { addEventListener() {} },
    addEventListener: (type, fn) => { if (type === 'DOMContentLoaded') fn(); },
  };
  runInNewContext(script, { window, document, URL });
  function flush() { while (frames.length) frames.shift()(); }
  function click(target, extra = {}) {
    const event = { target, button: 0, preventDefault() { this.defaultPrevented = true; }, ...extra };
    clicks.forEach((fn) => fn(event));
    flush();
    return event;
  }
  flush();
  return { body, head, card, toggle, link, click, store, scrolls, window, paths, editorPanel };
}

test('collapse and expand are local and retain the same focused toggle', () => {
  const state = setup();
  state.click(state.toggle);
  assert.equal(state.body.hidden, true);
  assert.equal(state.head.hidden, false);
  assert.equal(state.card.dataset.expanded, 'false');
  assert.equal(state.toggle.textContent, '＋');
  state.click(state.toggle);
  assert.equal(state.body.hidden, false);
  assert.equal(state.head.hidden, true);
  assert.equal(state.card.dataset.expanded, 'true');
  assert.equal(state.toggle.focusCalls.length, 2);
  assert.equal(state.scrolls.length, 0);
  assert.equal(state.store.size, 0);
});

test('switching branches records focus and restores its viewport position', () => {
  const first = setup({ editorOpen: true });
  first.click(first.link);
  const saved = JSON.parse(first.store.get('padif.rail.navigation'));
  assert.equal(saved.focus, 'branch-2-toggle');
  assert.equal(saved.top, 220);
  const next = setup({ saved });
  assert.equal(next.toggle.focusCalls.length, 1);
  assert.equal(next.scrolls[0][0].top, 50); // restore page position before positioning the focused control
  assert.equal(next.editorPanel.open, true);
  assert.equal(next.scrolls.at(-1)[0].top, 10); // 50 + new top 180 - original top 220
  assert.equal(next.store.size, 0);
});

test('modified navigation leaves the current tab focus state alone', () => {
  const state = setup();
  state.click(state.link, { ctrlKey: true });
  assert.equal(state.store.size, 0);
});

function setupDrawer(saved = null, storageDenied = false) {
  const store = new Map();
  const key = 'padif.worldline-drawer./padif/documents/1/';
  if (saved) store.set(key, saved);
  const classes = new Set();
  const resized = [];
  const editor = { manuscript: 'Unsaved manuscript' };
  const file = { name: 'unsaved-upload.md' };
  const makeControl = () => ({
    events: {}, attributes: {}, isConnected: true,
    addEventListener(type, fn) { this.events[type] = fn; },
    setAttribute(name, value) { this.attributes[name] = value; },
    focus() { document.activeElement = this; },
  });
  const close = makeControl();
  const handle = makeControl();
  const branchLink = makeControl();
  const drawer = { ...makeControl(), contains: (element) => element === close || element === branchLink };
  const layout = {
    querySelector: (selector) => ({ '[data-version-drawer]': drawer, '[data-drawer-handle]': handle, '[data-drawer-close]': close })[selector],
    classList: { toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); } },
  };
  const document = {
    activeElement: editor,
    querySelector: (selector) => selector === '[data-worldline-layout]' ? layout : null,
    querySelectorAll: () => [],
    addEventListener: (type, fn) => { if (type === 'DOMContentLoaded') fn(); },
    body: { addEventListener() {} },
  };
  const window = {
    location: { pathname: '/padif/documents/1/' },
    requestAnimationFrame: (fn) => fn(),
    dispatchEvent: (event) => resized.push(event.type),
    sessionStorage: {
      getItem(name) { if (storageDenied) throw new Error('Storage disabled'); return store.get(name); },
      setItem(name, value) { if (storageDenied) throw new Error('Storage disabled'); store.set(name, value); },
    },
  };
  runInNewContext(script, { window, document, Event: class { constructor(type) { this.type = type; } } });
  return { document, drawer, handle, close, branchLink, classes, store, key, editor, file, resized };
}

test('drawer collapse releases the column and keeps manuscript and upload objects intact', () => {
  const state = setupDrawer();
  state.document.activeElement = state.close;
  state.close.events.click();
  assert.equal(state.drawer.hidden, true);
  assert.equal(state.handle.hidden, false);
  assert.equal(state.classes.has('worldline-collapsed'), true);
  assert.equal(state.document.activeElement, state.handle);
  assert.equal(state.editor.manuscript, 'Unsaved manuscript');
  assert.equal(state.file.name, 'unsaved-upload.md');
  state.handle.events.click();
  assert.equal(state.drawer.hidden, false);
  assert.equal(state.classes.has('worldline-collapsed'), false);
  assert.equal(state.document.activeElement, state.close);
  assert.equal(state.resized.length, 3);
});

test('drawer remembers collapsed preference without stealing editor focus on load', () => {
  const state = setupDrawer('closed');
  assert.equal(state.drawer.hidden, true);
  assert.equal(state.document.activeElement, state.editor);
  assert.equal(state.handle.attributes['aria-expanded'], 'false');
  state.handle.events.click();
  assert.equal(state.store.get(state.key), 'open');
});

test('Escape closes the drawer and reopening restores its previous internal focus', () => {
  const state = setupDrawer();
  state.document.activeElement = state.branchLink;
  let prevented = false;
  state.drawer.events.keydown({ key: 'Escape', preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(state.document.activeElement, state.handle);
  state.handle.events.click();
  assert.equal(state.document.activeElement, state.branchLink);
});

test('drawer remains operable when browser storage is unavailable', () => {
  const state = setupDrawer(null, true);
  assert.equal(state.drawer.hidden, false);
  state.close.events.click();
  assert.equal(state.drawer.hidden, true);
  state.handle.events.click();
  assert.equal(state.drawer.hidden, false);
});
