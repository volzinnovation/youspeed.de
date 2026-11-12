const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const core = require('../../inspector/sign-annotations-core.js');
const catalog = require('../../shared/tsr/prolix-de-class-catalog-v1.json');
const source = fs.readFileSync(require.resolve('../../inspector/sign-annotations.js'), 'utf8');
const response = (body, status = 200) => ({ok: status < 400, status, json: async () => body});
const picture = (id = 'p1') => ({id, width: 4000, height: 2000, photo_url: '/inspector/api/sign-annotations/pictures/' + id + '/image',
  revision: 'revision-1', captured_at: '2026-01-01T12:00:00Z', latitude: 48, longitude: 8, heading_deg: 90,
  previous: null, next: {id: 'unannotated'}, nearby: [],
  annotations: id === 'unannotated' ? [] : [{id: 'a1', sign_code: 'DE:205', class_id: 'give_way', box_xyxy: [10, 20, 100, 200], geometry_editable: false}]});
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };
function harness(fetcher) {
  const elements = new Map(), events = {}, requests = [];
  class Element {
    constructor(tag = 'div') { this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {}; this.dataset = {}; this.value = ''; this.textContent = ''; this.hidden = false; this.disabled = false; this.attributes = {}; this.checked = true;
      this.classList = {add() {}, remove() {}}; }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    append(...items) { this.children.push(...items); items.forEach(item => { if (typeof item === 'object') item.parentNode = this; }); }
    replaceChildren(...items) { this.children = []; this.append(...items); }
    setAttribute(key, value) { this.attributes[key] = value; }
    closest() { return evidence; }
    querySelector(tag) { return this.children.find(child => child.tagName === tag.toUpperCase()); }
    click() { if (!this.disabled) this.listeners.click?.({target: this}); }
    focus() {}
    setPointerCapture() {}
    getBoundingClientRect() { return {left: 0, top: 0, width: 800, height: 400}; }
  }
  const evidence = new Element();
  const el = name => { if (!elements.has(name)) elements.set(name, new Element()); return elements.get(name); };
  el('sign-annotation-editor').hidden = true; el('sign-annotation-mode').value = 'group';
  const document = {getElementById: el, createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag)};
  const window = {location: {origin: 'http://127.0.0.1:8771'}, YouSpeedSignAnnotationsCore: core,
    addEventListener: (name, fn) => {events[name] = fn;}, dispatchEvent: event => {events[event.type]?.(event);} };
  let uuids = 0;
  vm.runInNewContext(source, {document, window, URL, AbortController, Option: class extends Element {constructor(text, value) {super('option'); this.textContent = text; this.value = value;}},
    CustomEvent: class {constructor(type, options) {this.type = type; this.detail = options.detail;}},
    crypto: {randomUUID: () => 'request-' + (++uuids)}, fetch: async (url, options) => {
      requests.push({url, options});
      if (url.endsWith('/status')) return response({write_enabled: true, supports_shape_edit: false});
      if (url.endsWith('/history')) return response({corrections: []});
      if (url.startsWith('/shared/')) return response(catalog);
      return fetcher(url, options);
    }, console});
  const get = name => el('sign-annotation-' + name);
  const select = (id = 'p1') => window.YouSpeedSignAnnotations.select({observation: {image_id: id, annotation_id: 'a1'},
    observations: [{image_id: 'p1', sequence_id: 's', sequence_rank: 1}, {image_id: 'p2', sequence_id: 's', sequence_rank: 2}]});
  return {el: get, events, requests, select, editor: window.YouSpeedSignAnnotations,
    async open() {select(); get('open').click(); await settle();},
    input(name, value) {get(name).value = value; get(name).listeners.input?.({target: get(name)});},
    change(name, value) {get(name).value = value; get(name).listeners.change?.({target: get(name)});},
    save: () => get('form').listeners.submit({preventDefault() {}})};
}

test('group navigation and sequence navigation are distinct, including frames without annotations', async () => {
  const app = harness(async url => response(picture(url.split('/').at(-1)))); await app.open();
  assert.equal(app.el('classes').children.length, 142);
  assert.equal(app.el('left').disabled, true); assert.equal(app.el('redraw').disabled, true);
  assert.equal(app.el('class').disabled, false);
  app.el('next').click(); await settle();
  assert.ok(app.requests.some(r => r.url.endsWith('/pictures/p2')));
  app.change('mode', 'sequence'); app.el('next').click(); await settle();
  assert.ok(app.requests.some(r => r.url.endsWith('/pictures/unannotated')));
  assert.equal(app.el('new').disabled, false);
  assert.equal(app.el('selection').children.length, 1);
});

test('number/name autocomplete selects the same class, uses shared icons, and prevents draft loss', async () => {
  const app = harness(async () => response(picture())); await app.open();
  app.input('class', '274-30');
  assert.equal(app.el('save').disabled, false);
  assert.match(app.el('class-label').textContent, /Höchstgeschwindigkeit 30/);
  assert.equal(app.el('icon').src, '/shared/tsr/sign-pictograms/png/de-274-30.png');
  const requests = app.requests.length; app.el('next').click(); await settle();
  assert.equal(app.requests.length, requests);
  assert.match(app.el('status').textContent, /ungespeicherte/);
  app.el('discard').click();
  app.input('class', 'Vorfahrt gewähren');
  assert.equal(app.el('save').disabled, true); // Identical annotation, no needless write.
});

test('uncertain writes reuse their request identity and freeze the draft until reconciliation', async () => {
  let posts = 0; const payloads = [];
  const app = harness(async (url, options) => {
    if (options?.method === 'POST') {
      payloads.push(JSON.parse(options.body));
      if (++posts === 1) throw new TypeError('network lost after acceptance');
      const updated = picture(); updated.annotations[0].sign_code = 'DE:206'; updated.annotations[0].class_id = 'stop';
      return response({picture: updated, receipt: {status: 'synced', sign_code: 'DE:206'}});
    }
    return response(picture());
  }); await app.open(); app.input('class', '206'); await app.save();
  assert.equal(app.el('save').textContent, 'Speicherstatus prüfen');
  assert.equal(app.el('class').disabled, true); assert.equal(app.el('discard').disabled, true);
  await app.save(); assert.equal(posts, 2);
  assert.equal(payloads[0].request_id, payloads[1].request_id);
  assert.equal(payloads[0].class_id, 'stop'); assert.equal(payloads[0].sign_code, 'DE:206');
  assert.match(app.el('status').textContent, /In Panoramax gespeichert/);
});

test('late picture responses cannot replace a newer selection', async () => {
  const pending = [];
  const app = harness(url => new Promise(resolve => pending.push({url, resolve})));
  app.select(); app.el('open').click(); await settle();
  app.select('p2'); await settle();
  pending[1].resolve(response(picture('p2'))); await settle();
  pending[0].resolve(response(picture('p1'))); await settle();
  assert.match(app.el('stage').children[0].src, /p2\/image$/);
});

test('icons are centered on native boxes and the toggle hides them without changing annotations', async () => {
  const app = harness(async () => response(picture())); await app.open();
  const svg = app.el('stage').children[1];
  const icon = svg.children.find(item => item.tagName === 'IMAGE');
  assert.ok(icon);
  assert.equal(Number(icon.attributes.x) + Number(icon.attributes.width) / 2, 55);
  assert.equal(Number(icon.attributes.y) + Number(icon.attributes.height) / 2, 110);
  app.el('show-icons').checked = false; app.change('show-icons', '');
  assert.equal(svg.children.filter(item => item.tagName === 'IMAGE').length, 0);
  assert.equal(app.el('save').disabled, true);
});

test('all 142 class choices can express an unmapped family without fabricating a StVO code', async () => {
  let payload;
  const app = harness(async (url, options) => {
    if (options?.method === 'POST') {
      payload = JSON.parse(options.body);
      return response({error: 'fixture rejection'}, 403);
    }
    return response(picture());
  }); await app.open();
  app.el('class-picker').click();
  app.el('classes').children[catalog.class_labels.indexOf('bad:back')].click();
  assert.equal(app.el('icon').hidden, true);
  assert.equal(app.el('save').disabled, false);
  await app.save();
  assert.equal(payload.class_id, 'bad:back'); assert.equal(payload.sign_code, null);
});

test('a confirmed save with a failed post-save refresh reloads without resubmitting the edit', async () => {
  let posts = 0;
  const app = harness(async (url, options) => {
    if (options?.method === 'POST') { posts++; return response({id: 'p1', picture_sync: 'refresh_required', correction: {status: 'confirmed'}}); }
    return response(picture());
  }); await app.open(); app.input('class', '206'); await app.save();
  assert.equal(posts, 1);
  assert.match(app.el('status').textContent, /gespeichert und Ansicht aktualisiert/);
  assert.equal(app.el('save').disabled, true);
});
