const test = require('node:test');
const assert = require('node:assert/strict');
const core = require('../../inspector/sign-positions-core.js');
const {payload} = require('./sign_positions_fixture.js');
test('packed coordinates decode longitude first without unsafe OSM ID conversion', () => {
  const original = payload(), copy = structuredClone(original), parsed = core.parsePayload(original);
  assert.deepEqual(original, copy);
  assert.deepEqual(parsed.roads[0].coordinates, [[8, 48], [8.0001, 48.0001]]);
  assert.equal(parsed.roads[0].id, 'bw:9007199254740993');
  assert.deepEqual(core.latLng(parsed.cases[0].point), [48, 8]);
});
test('uncertainty rings close without mutating data, and full extent includes other assumptions', () => {
  const c = core.parsePayload(payload()).cases[0];
  assert.deepEqual(core.closedRegion(c), [...c.region, c.region[0]]);
  assert.equal(c.region.length, 3);
  assert.ok(core.extentPoints(c, 'uncertainty').some(p => p[0] === 48.001));
});
test('maximum speed and zone starts are explicit; other signs and arbitrary digits fail closed', () => {
  for (const family of ['minimum_speed', 'advisory_speed', 'restriction_end', 'city_start', 'unknown']) {
    const p = payload(); p.cases[0].speedLimit.family = family; assert.throws(() => core.parsePayload(p));
  }
  for (const value of [0, -1, '70', NaN, Infinity]) { const p = payload(); p.cases[0].speedLimit.value = value; assert.throws(() => core.parsePayload(p)); }
  const missing = payload(); delete missing.cases[0].speedLimit; assert.throws(() => core.parsePayload(missing));
  const zone = payload(); zone.cases[0].speedLimit = {family: 'zone_start', value: 30, unit: 'km/h'};
  assert.equal(core.limitLabel(core.parsePayload(zone).cases[0]), 'Tempo-Zone 30 km/h');
});
test('unknown coverage stays unknown and empty gated population is supported', () => {
  const p = payload(); p.cases[0].category = 'unknown'; p.cases[0].source = 'ch';
  assert.deepEqual(core.counts(core.parsePayload(p).cases), {motorway: 0, 'other-exit': 0, covered: 0, unknown: 1});
  p.cases = []; p.roads = []; p.roadClasses = [];
  assert.deepEqual(core.parsePayload(p).cases, []);
});
test('exit-first ordering and dynamic counts retain original labels', () => {
  const c = core.parsePayload(payload()).cases[0];
  const cases = [c, {...c, label: '07', category: 'unknown'}, {...c, label: '48', category: 'motorway', portals: [{distance: 40}]},
    {...c, label: '13', category: 'other-exit', portals: [{distance: 20}]}];
  assert.deepEqual(core.orderedCases(cases).map(c => c.label), ['48', '13', '18', '07']);
  assert.deepEqual(core.counts(cases), {motorway: 1, 'other-exit': 1, covered: 1, unknown: 1});
});
for (const [name, mutate] of [
  ['expired', p => {p.meta.availableUntil = '2020-01-01T00:00:00Z';}],
  ['wrong scope', p => {p.meta.scope = 'all_signs';}],
  ['bad coordinate order/range', p => {p.cases[0].point = [8, 180];}],
  ['invalid delta', p => {p.roads[0][4][0] = 1.2;}],
  ['invalid road reference', p => {p.cases[0].roadIds = [1];}],
  ['missing road from case', p => {p.cases[0].roadIds = [];}],
  ['duplicate label', p => {p.cases.push(structuredClone(p.cases[0]));}],
  ['unexpected portal in unknown', p => {p.cases[0].portals = [{point: [8,48],distance: 3,ref:'A1',highway:'motorway',incoming:0,mainline:[0],link:0}];}],
  ['unsupported estimate', p => {p.cases[0].scenarios[1].point = [8,48];}],
  ['missing lifecycle deadline', p => {delete p.meta.availableUntil;}]
]) test('rejects ' + name, () => { const p = payload(); mutate(p); assert.throws(() => core.parsePayload(p)); });
