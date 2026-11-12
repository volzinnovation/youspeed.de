const test = require('node:test');
const assert = require('node:assert/strict');
const core = require('../../inspector/sign-annotations-core.js');
const catalog = require('../../shared/tsr/prolix-de-class-catalog-v1.json');

test('drawing maps a letterboxed preview to native pixels and rejects the empty margins', () => {
  const wide = {left: 10, top: 20, width: 800, height: 600};
  assert.equal(core.imagePoint(200, 30, wide, 4000, 2000), null);
  assert.deepEqual(core.imagePoint(410, 320, wide, 4000, 2000), [2000, 1000]);
  assert.deepEqual(core.imagePoint(10, 120, wide, 4000, 2000), [0, 0]);
  const tall = {left: 0, top: 0, width: 1000, height: 500};
  assert.equal(core.imagePoint(5, 250, tall, 1000, 1000), null);
  assert.deepEqual(core.imagePoint(500, 250, tall, 1000, 1000), [500, 500]);
});
test('reverse drag normalizes boxes but points, fractions, and out-of-image boxes are rejected', () => {
  assert.deepEqual(core.dragBox([80, 70], [20, 10], 100, 100), [20, 10, 80, 70]);
  assert.equal(core.dragBox([2, 2], [2, 2], 100, 100), null);
  for (const box of [[0, 0, 101, 2], [-1, 0, 1, 2], [0, 0, NaN, 2], [0, 0, 1.5, 2]]) {
    assert.equal(core.validBox(box, 100, 100), false);
  }
});
test('class edits are detected independently of geometry without mutating the loaded annotation', () => {
  const original = {id: 'a', sign_code: 'DE:205', box_xyxy: [1, 2, 30, 40]};
  assert.equal(core.changed(original, {...original}), false);
  assert.equal(core.changed(original, {...original, sign_code: 'DE:206'}), true);
  assert.equal(core.changed(original, {...original, box_xyxy: [1, 2, 31, 40]}), true);
  assert.equal(core.classCode(' de:274-30 '), 'DE:274-30');
  assert.equal(core.classCode('DE:274.1'), 'DE:274.1');
  assert.equal(core.classCode('<script>'), null);
});
test('group navigation deduplicates pictures, preserves sequence rank, and excludes mobile crops', () => {
  const observations = [
    {image_id: 'p3', sequence_id: 'a', sequence_rank: 3},
    {image_id: 'm', mobile_kind: 'crop'},
    {image_id: 'p1', sequence_id: 'a', sequence_rank: 1},
    {image_id: 'p1', sequence_id: 'a', sequence_rank: 1},
    {image_id: 'p2', sequence_id: 'a', sequence_rank: 2}
  ];
  assert.deepEqual(core.groupPictures(observations).map(p => p.image_id), ['p1', 'p2', 'p3']);
  assert.equal(observations[0].image_id, 'p3');
});

test('the picker contains exactly the model 142 classes and searches German names or numbers', () => {
  const entries = core.catalogEntries(catalog);
  assert.equal(entries.classes.length, 142);
  assert.deepEqual(entries.classes.map(item => item.class_id), catalog.class_labels);
  assert.equal(core.searchClasses(entries.search, '205')[0].code, 'DE:205');
  assert.ok(core.searchClasses(entries.search, 'Vorfahrt gewahren').some(item => item.code === 'DE:205'));
  assert.ok(core.searchClasses(entries.search, 'Hochstgeschwindigkeit 30').some(item => item.code === 'DE:274-30'));
  assert.equal(entries.classes.find(item => item.class_id === 'arrow_turn_left').code, 'DE:209-10');
  assert.equal(entries.classes.find(item => item.class_id === 'arrow_turn_right').code, 'DE:209');
  assert.equal(entries.classes.find(item => item.class_id === 'bad:back').code, null);
  assert.equal(entries.classes.find(item => item.class_id === 'bad:back').icon, null);
});

test('every displayed pictogram is the existing shared asset, and native decimal/family codes survive', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  for (const item of core.catalogEntries(catalog).search) {
    if (item.icon) assert.ok(fs.existsSync(path.join(__dirname, '../..', item.icon)), item.icon);
  }
  assert.equal(core.classCode('DE:262-5,5'), 'DE:262-5,5');
  assert.equal(core.classCode('de:101-x0'), 'DE:101-x0');
});
