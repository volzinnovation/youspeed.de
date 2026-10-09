const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const core = require('../../inspector/tsr-qa-core.js');
const source = fs.readFileSync(require.resolve('../../inspector/tsr-qa.js'), 'utf8');

// Execute the complete production mode controller with empty local QA data.
function harness(hash) {
  const elements = new Map(), listeners = {}, dispatched = [], historyWrites = [];
  function element() {
    const classes = new Set();
    return {hidden: false, value: 'all', dataset: {}, style: {}, attributes: {}, listeners: {}, children: [],
      classList: {toggle(name, active) {if (active) classes.add(name); else classes.delete(name);}, contains: name => classes.has(name)},
      setAttribute(name, value) {this.attributes[name] = value;}, append(...items) {this.children.push(...items);},
      prepend(...items) {this.children.unshift(...items);}, replaceChildren(...items) {this.children = items;},
      addEventListener(name, callback) {this.listeners[name] = callback;}};
  }
  const el = id => {if (!elements.has(id)) elements.set(id, element()); return elements.get(id);};
  const document = {body: {dataset: {}}, getElementById: el, createElement: element, addEventListener() {}};
  const window = {YouSpeedTSRQACore: core, location: {hash, href: 'https://inspector.example/inspector/' + hash},
    addEventListener(name, callback) {listeners[name] = callback;}, dispatchEvent(event) {dispatched.push(event);}, setTimeout() {}};
  vm.runInNewContext(source, {window, document, URL, console,
    history: {replaceState(_state, _title, value) {historyWrites.push(value); window.location.hash = value;}},
    CustomEvent: class {constructor(type, options) {this.type = type; this.detail = options.detail;}},
    fetch: async () => ({ok: false, status: 503})});
  return {el, document, dispatched, historyWrites, hashchange(value) {window.location.hash = value; listeners.hashchange();}};
}

for (const hash of ['#sign-positions', '#positions']) {
  test(`${hash} initializes the positions tab and keeps other workspaces hidden`, () => {
    const app = harness(hash);
    assert.equal(app.document.body.dataset.inspectorMode, 'positions');
    assert.equal(app.el('positions-workspace').hidden, false);
    assert.equal(app.el('positions-mode-btn').attributes['aria-selected'], 'true');
    for (const id of ['matcher-workspace', 'tsr-workspace', 'crops-workspace']) assert.equal(app.el(id).hidden, true);
    assert.equal(app.dispatched.at(-1).detail, 'positions');
    assert.equal(app.historyWrites.length, 0);
  });
}

test('hash changes support canonical route and alias; tab navigation writes the canonical route', () => {
  const app = harness('#matcher');
  for (const hash of ['#sign-positions', '#positions']) {
    app.hashchange('#crops');
    assert.equal(app.document.body.dataset.inspectorMode, 'crops');
    app.hashchange(hash);
    assert.equal(app.document.body.dataset.inspectorMode, 'positions');
    assert.equal(app.el('positions-workspace').hidden, false);
    assert.equal(app.el('crops-workspace').hidden, true);
  }
  app.el('positions-mode-btn').listeners.click();
  assert.equal(app.historyWrites.at(-1), '#sign-positions');
  app.el('tsr-mode-btn').listeners.click();
  assert.equal(app.historyWrites.at(-1), '#tsr');
  assert.equal(app.el('positions-workspace').hidden, true);
  app.hashchange('#not-a-tab');
  assert.equal(app.document.body.dataset.inspectorMode, 'matcher');
});
