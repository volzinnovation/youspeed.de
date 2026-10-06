const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../../inspector/backend-crops.js'), 'utf8');
const iphone = 'd3e3c09c-2fc6-4f05-9698-67b8c3c30212';
const android = '78b247a4-9f14-430d-a3c0-af218a95d101';

function inspector({manifest = {}, observation = {}} = {}) {
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
      decoded_width: 10, decoded_height: 20, encoding: 'PNG', byte_length: 123, actual_extra_height: 10, ...manifest},
    observation: {classification: {canonical_code: 'DE:274-50'},
      app: {platform: installation === iphone ? 'ios' : 'android', version: '1.4', build: '10039'}, ...observation}});
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

async function metadata(options) {
  const app = inspector(options); await settle();
  await app.el('gallery').children[0].listeners.click(); await settle();
  const children = app.el('metadata').children;
  return Object.fromEntries(children.flatMap((child, i) => i % 2 ? [] : [[child.textContent, children[i + 1]]]));
}

test('crop frame position and course take precedence over the parent sighting', async () => {
  const fields = await metadata({manifest: {vehicle_position: {
    latitude: 47, longitude: 8, course_degrees: 0, course_accuracy_degrees: 2,
    horizontal_accuracy_m: 3, fix_at: '2026-10-06T08:00:00Z', frame_fix_delta_ms: -50, alignment: 'nearest_fix'
  }}, observation: {vehicle_position: {latitude: 48, longitude: 9, course_degrees: 90}}});
  assert.equal(fields['Positionsbezug'].textContent, 'Crop-Aufnahme');
  assert.equal(fields['Fahrzeugposition'].children[0].textContent, '47, 8');
  assert.equal(fields['Fahrtrichtung (GPS-Kurs)'].textContent, '0 °');
  assert.equal(fields['Kursgenauigkeit'].textContent, '2 °');
  assert.equal(fields['Positionsgenauigkeit'].textContent, '3 m');
  assert.equal(fields['Frame − GPS-Fix'].textContent, '-50 ms');
});

test('legacy crops explicitly label sighting-level course and position', async () => {
  const fields = await metadata({observation: {vehicle_position: {latitude: 47, longitude: 8, course_degrees: 90}}});
  assert.equal(fields['Positionsbezug'].textContent, 'Beobachtung · ältere Crop-Metadaten');
  assert.equal(fields['Fahrtrichtung (GPS-Kurs)'].textContent, '90 °');
  assert.equal(fields['Kursgenauigkeit'].textContent, '—');
});

test('missing crop GPS or course never borrows an older sighting value', async () => {
  const parent = {vehicle_position: {latitude: 48, longitude: 9, course_degrees: 90}};
  for (const position of [null, {latitude: 47, longitude: 8, course_degrees: null}]) {
    const fields = await metadata({manifest: {vehicle_position: position}, observation: parent});
    assert.equal(fields['Positionsbezug'].textContent, 'Crop-Aufnahme');
    assert.equal(fields['Fahrtrichtung (GPS-Kurs)'].textContent, '—');
    if (position === null) assert.equal(fields['Fahrzeugposition'].textContent, '—');
  }
});

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
