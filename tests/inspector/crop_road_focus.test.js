const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../../inspector/app.js'), 'utf8');
const start = source.indexOf('function focusCropRoad(');
const end = source.indexOf('\nfunction ', start + 1);
assert.ok(start >= 0 && end > start);

function harness(database = true, found = true) {
  const calls = [];
  const state = {position: null, way: null};
  const sandbox = {
    setStatus: (...args) => calls.push(['status', ...args]),
    requireDatabase: () => database,
    ensureMapTiles: () => calls.push(['tiles']),
    map: {invalidateSize: () => calls.push(['resize'])},
    clearTSRContextLayers: () => { state.position = null; },
    clearWayLayers: () => { state.way = null; },
    updatePortalInspection: () => {},
    loadAndCenterWay: way => { calls.push(['lookup', way]); state.way = found ? way : null; return found; },
    focusTSRContext: context => {state.position = context; calls.push(['position', JSON.parse(JSON.stringify(context))]);}
  };
  vm.createContext(sandbox);
  vm.runInContext(source.slice(start, end), sandbox);
  return {calls, state, focus: sandbox.focusCropRoad};
}

test('recorded road opens indexed bundle lookup with per-crop travel bearing', () => {
  const app = harness();
  assert.equal(app.focus('123456789', {latitude: 48, longitude: 8, course_degrees: 0}), true);
  assert.deepEqual(app.calls.filter(c => ['lookup', 'position'].includes(c[0])), [
    ['lookup', '123456789'], ['position', {way_id: '123456789', latitude: 48, longitude: 8, heading_degrees: 0}]
  ]);
});

test('absent direction remains absent and no GPS is required for way lookup', () => {
  for (const course of [null, undefined, NaN, 360, -1]) {
    const app = harness();
    app.focus('123', {latitude: 48, longitude: 8, course_degrees: course});
    assert.equal('heading_degrees' in app.calls.find(c => c[0] === 'position')[1], false);
  }
  const app = harness();
  assert.equal(app.focus('123', null), true);
  assert.ok(app.calls.some(c => c[0] === 'lookup'));
  assert.ok(!app.calls.some(c => c[0] === 'position'));
});

test('unsupported int64 values never become a different rounded map way', () => {
  for (const way of ['9007199254740993', '9223372036854775807', '01', '0', '1e3', '-1']) {
    const app = harness();
    assert.equal(app.focus(way, null), false);
    assert.ok(!app.calls.some(c => c[0] === 'lookup'));
  }
  const app = harness(false);
  assert.equal(app.focus('123', null), false);
  assert.equal(app.calls.length, 0);
});

test('switching to absent GPS or a missing road clears the previous crop context', () => {
  const app = harness();
  app.focus('123', {latitude: 48, longitude: 8, course_degrees: 90});
  assert.ok(app.state.position);
  app.focus('456', null);
  assert.equal(app.state.position, null);
  assert.equal(app.state.way, '456');
  const missing = harness(true, false);
  missing.state.way = '123'; missing.state.position = {latitude: 48};
  assert.equal(missing.focus('789', null), false);
  assert.equal(missing.state.way, null);
  assert.equal(missing.state.position, null);
});
