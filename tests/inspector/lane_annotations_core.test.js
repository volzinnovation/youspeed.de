const test = require('node:test');
const assert = require('node:assert/strict');
const core = require('../../inspector/lane-annotations-core.js');
const zip = require('../../inspector/lane-dataset-zip.js');
const fixture = () => {
  const dataset = core.create('fixture');
  const source = core.addSource(dataset, {id: 'a'.repeat(64), sha256: 'a'.repeat(64), name: 'vfr.mp4', byteLength: 100,
    width: 640, height: 360, timeBase: '1/1000', startPts: '100', sourceRotation: 0, transform: 'ffmpeg_autorotate_full_frame',
    frames: [100, 140, 260, 300].map((pts,i) => ({index: i, pts: String(pts), timeSeconds: (pts-100)/1000}))}, 'drive-one');
  function sample(index) {
    const s = core.createSample(source, index, {path: `images/${core.sampleId(source,index)}.png`, sha256: 'b'.repeat(64), byteLength: 10});
    dataset.samples.push(s); return s;
  }
  return {dataset, source, sample};
};
const curve = (id, marking = 'solid') => ({id, trackId: `track-${id}`, degree: 3, marking,
  controlPoints: [[0.1,0.9],[0.2,0.7],[0.35,0.5],[0.4,0.3]], copiedFrom: null});

test('VFR identity, two marking classes, reviewed empty and draft frames round-trip', () => {
  const f = fixture(), a = f.sample(0), empty = f.sample(1), draft = f.sample(2);
  a.curves.push(curve('left'), curve('right', 'dashed')); core.confirm(a); core.confirm(empty);
  assert.deepEqual(core.validate(core.clone(f.dataset)), f.dataset);
  assert.deepEqual(core.splitManifests(f.dataset)[f.source.split], [a.id,empty.id]);
  assert.equal(draft.status, 'draft');
  const broken = core.clone(f.dataset); broken.samples[0].pts = '140';
  assert.throws(() => core.validate(broken), /exakten/);
});

test('copy creates independent curves, shared tracks and draft provenance without overwriting', () => {
  const f = fixture(), a = f.sample(0), b = f.sample(1); a.curves.push(curve('a'),curve('b','dashed')); core.confirm(a);
  let n = 0; core.copyDraft(a,b,() => `copy-${++n}`);
  b.curves[0].controlPoints[0][0] = .9;
  assert.equal(a.curves[0].controlPoints[0][0], .1);
  assert.equal(b.curves[0].trackId, a.curves[0].trackId);
  assert.equal(b.curves[1].marking, 'dashed');
  assert.equal(b.status, 'draft'); assert.equal(b.draftFrom.revision, a.revision);
  assert.equal(b.curves[0].copiedFrom.annotationId, 'a');
  assert.throws(() => core.copyDraft(a,b,() => 'other'), /enthält/);
  assert.doesNotThrow(() => core.validate(f.dataset));
  assert.deepEqual(core.splitManifests(f.dataset)[f.source.split], [a.id]);
  core.confirm(b); core.edited(b); assert.equal(b.status,'draft'); assert.equal(b.reviewedAt,null);
});

test('track linking enforces one instance per frame, unlink starts a new track', () => {
  const f = fixture(), a = f.sample(0); a.curves.push(curve('a'),curve('b')); core.confirm(a);
  assert.throws(() => core.link(a,'a','track-b'), /nur eine/);
  core.link(a,'a','new-track'); assert.equal(a.status,'draft'); assert.equal(a.curves[0].trackId,'new-track');
});

test('drive group assignment prevents split leakage even for separate video clips', () => {
  const f = fixture(); const other = core.addSource(f.dataset, {...f.source,id:'c'.repeat(64),sha256:'c'.repeat(64)}, 'drive-one');
  assert.equal(other.split,f.source.split);
  core.setGroup(f.dataset,other.id,'drive-one','test'); assert.equal(f.source.split,'test');
  assert.doesNotThrow(() => core.validate(f.dataset));
  other.split = 'train'; assert.throws(() => core.validate(f.dataset), /mehrere Splits/);
});

test('resizing, letterboxing and cubic sampling preserve normalized geometry', () => {
  const rect = core.fitRect(800,600,640,360);
  assert.deepEqual(rect, {x:0,y:75,width:800,height:450});
  assert.equal(core.pointAt(400,25,rect),null);
  assert.deepEqual(core.pointAt(400,300,rect),[.5,.5]);
  const points = core.polyline(curve('a'),640,360,3);
  assert.deepEqual(points[0],[.1*639,.9*359]); assert.deepEqual(points[2],[.4*639,.3*359]);
  assert.throws(() => core.polyline(curve('a'),640,360,1));
});

test('schema rejects invalid curve geometry, duplicates and broken provenance', () => {
  const f = fixture(), a = f.sample(0), b = f.sample(1); a.curves.push(curve('a'));
  let broken = core.clone(f.dataset); broken.samples[0].curves[0].controlPoints[0][0] = NaN;
  assert.throws(() => core.validate(broken));
  broken = core.clone(f.dataset); broken.samples.push(core.clone(a)); assert.throws(() => core.validate(broken));
  b.draftFrom = {sampleId:b.id,revision:0}; assert.throws(() => core.validate(f.dataset), /Draft/);
});

test('portable ZIP preserves all bytes and rejects corrupt data', async () => {
  const files = [['manifest.json',new Blob(['{"test":true}'])],['splits/train.json',new Blob(['[]'])],
    [`images/${'a'.repeat(64)}-0.png`,new Blob([new Uint8Array([0,10,255])])]];
  const blob = await zip.pack(files), restored = await zip.unpack(blob);
  assert.equal(await restored.get('manifest.json').text(), '{"test":true}');
  assert.deepEqual(new Uint8Array(await restored.get(files[2][0]).arrayBuffer()),new Uint8Array([0,10,255]));
  const bytes = new Uint8Array(await blob.arrayBuffer()); bytes[30+'manifest.json'.length] ^= 1;
  await assert.rejects(zip.unpack(new Blob([bytes])), /Prüfsumme/);
  await assert.rejects(zip.pack([['../secret',new Blob(['x'])]]),/ZIP-Pfad/);
});
