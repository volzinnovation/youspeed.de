const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const core = require('../../inspector/sign-positions-core.js');
const {payload} = require('./sign_positions_fixture.js');
const source = fs.readFileSync(require.resolve('../../inspector/sign-positions.js'), 'utf8');
function harness(fetcher) {
  const elements = new Map(), events = {}, docEvents = {}, requests = [], maps = [], tiles = [], timers = new Map(); let timerId = 0;
  function element() { return {value: '', hidden: false, disabled: false, checked: true, children: [], listeners: {}, textContent: '',
    append(...x) {this.children.push(...x);}, replaceChildren(...x) {this.children = x;},
    addEventListener(name, callback) {this.listeners[name] = callback;},
    set innerHTML(_) {throw new Error('Raw HTML is prohibited');}}; }
  const el = name => {if (!elements.has(name)) elements.set(name, element()); return elements.get(name);};
  el('sign-positions-extent').value = 'context';
  const document = {hidden: false, body: {dataset: {inspectorMode: 'matcher'}}, getElementById: el, createElement: element,
    addEventListener(name, callback) {docEvents[name] = callback;}};
  const layer = () => ({addTo() {return this;}, bindTooltip(node) {assert.equal(typeof node, 'object'); return this;}, clearLayers() {}});
  const L = {map(target) {const map = {target, removed: false, remove() {this.removed = true;}, invalidateSize() {}, fitBounds() {}}; maps.push(map); return map;},
    tileLayer(url, options) {tiles.push({url, options}); return layer();}, layerGroup: layer, polyline: layer, polygon: layer, circleMarker: layer,
    latLngBounds(points) {assert.ok(points.length >= 2); return {pad() {return this;}};}};
  vm.runInNewContext(source, {document, window: {YouSpeedSignPositionsCore: core, addEventListener(name, callback) {events[name] = callback;}}, L, AbortController,
    fetch: (...args) => {requests.push(args); return fetcher(...args);}, setTimeout(fn) {timers.set(++timerId, fn); return timerId;}, clearTimeout(id) {timers.delete(id);}, Intl, Date, console});
  return {el: id => el('sign-positions-' + id), requests, maps, tiles, timers, document,
    mode(value) {document.body.dataset.inspectorMode = value; events['youspeed:mode']({detail: value});},
    hidden(value) {document.hidden = value; docEvents.visibilitychange();}};
}
const response = (body = payload(), ok = true) => ({ok, headers: {get: () => 'application/json'}, text: async () => JSON.stringify(body)});
const settle = () => new Promise(resolve => setImmediate(resolve));
test('loads only on this tab, uses policy-conforming OSM tiles, clears map/data on leave and refreshes on return', async () => {
  const app = harness(async () => response()); assert.equal(app.requests.length, 0); assert.equal(app.maps.length, 0);
  app.mode('positions'); await settle();
  assert.equal(app.requests.length, 1); assert.equal(app.maps.length, 1);
  assert.equal(app.requests[0][0], './api/sign-positions'); assert.equal(app.requests[0][1].cache, 'no-store');
  assert.equal(app.tiles[0].url, 'https://tile.openstreetmap.org/{z}/{x}/{y}.png');
  assert.equal(app.tiles[0].options.referrerPolicy, 'origin'); assert.equal(app.tiles[0].options.keepBuffer, 0);
  assert.equal(app.tiles[0].options.updateWhenIdle, true); assert.match(app.tiles[0].options.attribution, /openstreetmap.org\/copyright/);
  assert.match(app.el('summary').textContent, /1 freigegebene/); assert.match(app.el('summary').textContent, /keine bei einer indexierten Ausfahrt/);
  app.mode('crops'); assert.equal(app.maps[0].removed, true); assert.equal(app.el('case').children.length, 0); assert.equal(app.el('detail').textContent, '');
  app.mode('positions'); await settle(); assert.equal(app.requests.length, 2); assert.equal(app.maps.length, 2);
});
test('late response after leaving cannot redraw or request tiles', async () => {
  let resolve; const app = harness(() => new Promise(r => {resolve = r;})); app.mode('positions'); app.mode('matcher');
  assert.equal(app.requests[0][1].signal.aborted, true); resolve(response()); await settle(); assert.equal(app.maps.length, 0); assert.equal(app.tiles.length, 0);
});
test('refresh discards old geometry immediately and failed gating never restores it', async () => {
  let ok = true; const app = harness(async () => response(payload(), ok)); app.mode('positions'); await settle();
  ok = false; app.el('refresh').listeners.click(); assert.equal(app.maps[0].removed, true); await settle();
  assert.equal(app.el('case').children.length, 0); assert.equal(app.el('map-wrap').hidden, true); assert.match(app.el('status').textContent, /nicht verfügbar/);
});
test('out-of-order refresh responses cannot override a newer eligible subset', async () => {
  const resolves = []; const app = harness(() => new Promise(r => resolves.push(r))); app.mode('positions'); app.el('refresh').listeners.click();
  const p = payload(); p.cases[0].label = '48'; resolves[1](response(p)); await settle();
  resolves[0](response()); await settle(); assert.equal(app.el('case').value, '48'); assert.equal(app.maps.length, 1);
});
test('empty result does not create a map or request tiles', async () => {
  const p = payload(); p.cases = []; p.roads = []; p.roadClasses = [];
  const app = harness(async () => response(p)); app.mode('positions'); await settle();
  assert.equal(app.maps.length, 0); assert.equal(app.tiles.length, 0); assert.match(app.el('status').textContent, /keine Tempolimit-Positionen/);
});
test('hidden page stops its map and requires new lifecycle qualification on visibility', async () => {
  const app = harness(async () => response()); app.mode('positions'); await settle(); app.hidden(true);
  assert.equal(app.maps[0].removed, true); assert.equal(app.el('case').children.length, 0);
  app.hidden(false); await settle(); assert.equal(app.requests.length, 2);
});
test('expiry clears private data and map without a background refetch', async () => {
  const app = harness(async () => response()); app.mode('positions'); await settle(); [...app.timers.values()][0]();
  assert.equal(app.maps[0].removed, true); assert.equal(app.el('case').children.length, 0); assert.equal(app.requests.length, 1);
  assert.match(app.el('status').textContent, /abgelaufen/);
});
test('data strings remain text, not HTML or executable marker content', async () => {
  const p = payload(); p.cases[0].prediction = '<img src=x onerror=alert(1)>';
  const app = harness(async () => response(p)); app.mode('positions'); await settle();
  assert.match(app.el('detail').textContent, /<img src=x/); assert.equal(app.maps.length, 1);
});
