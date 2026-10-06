const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../../inspector/backend-crops.js'), 'utf8');
const iphone = 'd3e3c09c-2fc6-4f05-9698-67b8c3c30212';
const android = '78b247a4-9f14-430d-a3c0-af218a95d101';

function inspector() {
  const elements = new Map();
  function element() {
    return {value: '', children: [], listeners: {}, style: {}, attrs: {}, textContent: '',
      addEventListener(name, fn) {this.listeners[name] = fn;},
      append(...children) {this.children.push(...children);},
      replaceChildren(...children) {this.children = children;},
      setAttribute(name, value) {this.attrs[name] = value;},
      removeAttribute(name) {delete this.attrs[name];},
      decode: async () => {}};
  }
  const el = id => {if (!elements.has(id)) elements.set(id, element()); return elements.get(id);};
  const devices = [{installation: iphone, platforms: ['ios'], crop_count: 228},
    {installation: android, platforms: ['android'], crop_count: 15}];
  const urls = [];
  const row = installation => ({installation, epoch: 0, crop_id: 'crop', digest: 'digest',
    expires: 2000000000, image_url: '/inspector/api/crops/image',
    manifest: {observation_id: 'event', source_frame_at: '2026-10-06T08:00:00Z', source_kind: 'detector',
      decoded_width: 10, decoded_height: 20, encoding: 'PNG', byte_length: 123, actual_extra_height: 10},
    observation: {classification: {canonical_code: 'DE:274-50'},
      app: {platform: installation === iphone ? 'ios' : 'android', version: '1.4', build: '10039'}}});
  vm.runInNewContext(source, {
    document: {getElementById: el, createElement: element, body: {dataset: {inspectorMode: 'crops'}}},
    window: {addEventListener() {}}, AbortController, URL, URLSearchParams,
    fetch: async url => {
      urls.push(url);
      let body;
      if (url.endsWith('/status')) body = {database: 'youspeed', user: 'youspeed_report', media_available: true};
      else if (url.endsWith('/devices')) body = {devices};
      else if (url.includes('?')) {
        const params = new URLSearchParams(url.split('?')[1]);
        body = {crops: [row(params.get('installation') || iphone)], has_more: false};
      } else return {ok: false, json: async () => ({error: 'Preview absent in unit test'})};
      return {ok: true, headers: {get: () => 'application/json'}, json: async () => body};
    }
  });
  return {el: name => el('crops-' + name), urls, devices};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test('device choices include Android even when the first crop page only contains iPhone', async () => {
  const app = inspector(); await settle();
  const options = app.el('installation').children;
  assert.equal(options.length, 3);
  assert.match(options[1].textContent, /iPhone/);
  assert.ok(options[1].textContent.includes(iphone));
  assert.match(options[2].textContent, /Android.*15 Crops/);
  assert.ok(options[2].textContent.includes(android));
  const card = app.el('gallery').children[0];
  assert.ok(card.children.some(child => child.textContent.includes(iphone)));
  await card.listeners.click(); await settle();
  assert.ok(app.el('metadata').children.some(child => child.textContent === iphone));
  assert.equal(JSON.parse(app.el('raw').textContent).installation_id, iphone);
});

test('individual device filtering survives refresh and combines with existing filters', async () => {
  const app = inspector(); await settle();
  app.el('installation').value = android;
  app.el('country').value = 'DE';
  app.el('filters').listeners.submit({preventDefault() {}}); await settle();
  const params = new URLSearchParams(app.urls.filter(url => url.includes('?')).at(-1).split('?')[1]);
  assert.equal(params.get('installation'), android);
  assert.equal(params.get('country'), 'DE');
  assert.equal(params.get('offset'), '0');
  assert.equal(app.el('installation').value, android);
  const card = app.el('gallery').children[0];
  assert.ok(card.children.some(child => child.textContent.includes(android)));
  app.devices.splice(1, 1);
  app.el('filters').listeners.submit({preventDefault() {}}); await settle();
  assert.equal(app.el('installation').value, android);
  assert.match(app.el('installation').children.at(-1).textContent, /keine aktiven Crops/);
});
