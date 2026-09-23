const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const core = require('../../inspector/track-tsr-core');
const root = path.resolve(__dirname, '../..');
const catalogs = {}, manifests = {};
for (const c of core.countries) {
  catalogs[c] = JSON.parse(fs.readFileSync(path.join(root, `shared/tsr/prolix-${c.toLowerCase()}-class-catalog-v1.json`)));
  manifests[c] = JSON.parse(fs.readFileSync(path.join(root, `iphone/SpeedConsumerApp/TSRModelPacks/${c}.panoramax-bootstrap.tsrmodelpack/manifest.json`)));
}
const scope = {sessionId: 's', generation: 1, contextGeneration: 1, traversalEpoch: 1, bundleId: 'b', cameraGeometryId: 'g'};
function frame(time = 1000, options = {}) {
  const candidate = {candidateId: `c-${time}`, semanticKey: 'maximum_speed:90:km/h', rawScore: 0.82, recognitionEligible: true};
  const batch = {frameId: `f-${time}`, capturedAtMs: time, candidates: [candidate], scope: {...scope, ...options}};
  return {batch, tracks: [{trackId: 'track-1', samples: [{frameId: batch.frameId, candidate}]}],
    decisions: [{trackId: 'track-1', frameId: batch.frameId, classification: 'UNKNOWN', reasons: ['camera_calibration_unavailable']}]};
}

test('mixed iPhone log tracks country switches and separates observations from applied/rejected actions', () => {
  const result = core.parseLog([
    'timestamp=1970-01-01T00:00:00Z lifecycle=loading country=DE',
    'timestamp=1970-01-01T00:00:00Z lifecycle=switch country=FR',
    `timestamp=1970-01-01T00:00:01Z tsr_applicability_v1=${JSON.stringify(frame())}`,
    'timestamp=1970-01-01T00:00:01Z event_id=legacy state=confirmed speed_kmh=90 confidence=0.82 track=uuid',
    'timestamp=1970-01-01T00:00:02Z passage_activation=applied reason=camera_posted_maximum effective_kmh=90 track=uuid',
    'timestamp=1970-01-01T00:00:03Z passage_activation=rejected reason=latest_road_scope_incompatible track=uuid2'
  ].join('\n'));
  assert.equal(result.events.length, 3);
  assert.deepEqual(result.events.map(e => e.kind), ['detection', 'applied', 'rejected']);
  assert.ok(result.events.every(e => e.country === 'FR'));
  assert.ok(result.events[0].diagnostics.includes('UNKNOWN'));
  assert.equal(result.events[1].semantic, 'maximum_speed:90:km/h');
  assert.equal(result.events[2].semantic, 'unknown::');
});

test('repeated sightings group only within the same immutable scope and short interval', () => {
  const result = core.parseLog(JSON.stringify([frame(), frame(2000), frame(3000, {traversalEpoch: 2}), frame(10000)]));
  assert.equal(result.events.length, 3);
  assert.equal(result.events[0].count, 2);
  assert.equal(result.events[0].time, 1000);
  assert.equal(result.events[0].endTime, 2000);
});

test('same-frame candidates stay distinct; duplicate frames deduplicate and conflicting duplicates warn', () => {
  const a = frame();
  a.batch.candidates.push({...a.batch.candidates[0], candidateId: 'other'});
  const conflict = frame(); conflict.batch.candidates[0].rawScore = 0.3;
  const result = core.parseLog(JSON.stringify([a, a, conflict]));
  assert.equal(result.events.length, 2);
  assert.equal(result.frames, 1);
  assert.equal(result.warnings.length, 1);
});

test('Android envelope, raw diagnostic arrays, bad lines, and legacy logs remain inspectable', () => {
  const result = core.parseLog(JSON.stringify({event: 'tsr_applicability_v1', details: {evidence: JSON.stringify(frame())}}));
  assert.equal(result.samples, 1);
  assert.equal(result.events[0].country, null);
  const legacy = core.parseLog('timestamp=1970-01-01T00:00:01Z state=provisional speed_kmh=50 confidence=0.8 track=x\n' +
    'timestamp=1970-01-01T00:00:02Z state=confirmed speed_kmh=50 confidence=0.9 track=x\n{broken');
  assert.equal(legacy.events[0].count, 2);
  assert.equal(legacy.events[0].score, 0.9);
  assert.equal(legacy.warnings.length, 1);
});

test('GPS joins are nearest, bounded, sorted, keep original fix indexes, and never invent coordinates', () => {
  const fixes = [
    {timestampUTC: '1970-01-01T00:00:10Z', lat: 44, lon: 4},
    {timestampUTC: '1970-01-01T00:00:01Z', lat: 43, lon: 4},
    {timestampUTC: '1970-01-01T00:00:20Z', lat: null, lon: 4},
    {timestampUTC: '1970-01-01T00:00:30Z', lat: 999, lon: 4}];
  const joined = core.joinTrack([0, 3100, 9500, 20000, 30000].map(time => ({time})), fixes);
  assert.equal(joined[0].fix.index, 1);
  assert.equal(joined[1].fix, null);
  assert.equal(joined[2].fix.index, 0);
  assert.equal(joined[3].fix, null);
  assert.equal(joined[4].fix, null);
  assert.equal(core.joinTrack([{time: 1}], [])[0].fix, null);
});

test('all five countries resolve national end symbols without crossing country boundaries', () => {
  for (const c of core.countries) {
    const art = core.artwork({country: c, semantic: 'restriction_end::'}, catalogs, manifests);
    assert.ok(art.url, c);
    assert.match(art.url, new RegExp(`/${c.toLowerCase()}-`));
    assert.ok(fs.existsSync(path.join(root, 'inspector', art.url)));
  }
  assert.match(core.artwork({country: 'FR', semantic: 'maximum_speed:90:km/h'}, catalogs, manifests).url, /fr-b14-90.png$/);
  assert.match(core.artwork({country: 'FR', semantic: 'city_exit::'}, catalogs, manifests).url, /fr-eb20.png$/);
  assert.equal(core.artwork({semantic: 'maximum_speed:90:km/h'}, catalogs, manifests).url, null);
  assert.equal(core.artwork({country: 'FR', semantic: 'zone_end:20:'}, catalogs, manifests).url, null);
  assert.match(core.artwork({semantic: 'city_exit::'}, catalogs, manifests, 'FR').url, /fr-eb20/);
});

test('exact class artwork uses eligibility; semantic placeholders never fabricate a class for unknowns', () => {
  const known = catalogs.FR.signs.find(s => s.display_eligible && s.class_id.startsWith('A'));
  assert.ok(core.artwork({country: 'FR', classId: known.class_id, semantic: 'unknown::'}, catalogs, manifests).url);
  assert.equal(core.artwork({country: 'FR', semantic: 'unknown::'}, catalogs, manifests).url, null);
  const unsafe = {FR: {signs: [{class_id: 'x', display_eligible: true, image_path: 'tsr/sign-pictograms/../../private.png'}]}};
  assert.equal(core.artwork({country: 'FR', classId: 'x', semantic: 'unknown::'}, unsafe, {}).url, null);
});

test('all display-eligible catalog images resolve to existing shared local bytes', () => {
  for (const c of core.countries) for (const sign of catalogs[c].signs.filter(s => s.display_eligible)) {
    const art = core.artwork({country: c, classId: sign.class_id, semantic: 'unknown::'}, catalogs, manifests);
    assert.ok(art.url, `${c} ${sign.class_id}`);
    assert.ok(fs.existsSync(path.join(root, 'inspector', art.url)), `${c} ${sign.class_id}`);
  }
});
