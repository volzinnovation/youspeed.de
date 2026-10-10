const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const zip = require('../../inspector/lane-dataset-zip.js');
const root = path.resolve(__dirname,'fixtures/lane-dataset-v1');
const loader = import('../../scripts/inspector/lane_dataset_loader.mjs');

test('all three fixture splits load reviewed lanes and reviewed empty images, excluding drafts', async () => {
  const {loadDataset} = await loader;
  const groups = new Set();
  for (const split of ['train','validation','test']) {
    const records = await loadDataset(root,{split,points:5});
    assert.equal(records.length,2); assert.equal(records[0].curves.length,2); assert.equal(records[1].curves.length,0);
    assert.deepEqual(records[0].curves.map(c=>c.classId),[0,1]); assert.equal(records[0].curves[0].points.length,5);
    assert.equal(records[0].status,'reviewed'); assert.equal(records[0].imageBytes.readUInt32BE(16),128);
    assert.ok(!groups.has(records[0].groupId)); groups.add(records[0].groupId);
    const drafts = await loadDataset(root,{split,includeDrafts:true});
    assert.equal(drafts.length,3); assert.equal(drafts[1].status,'draft');
    assert.equal(drafts[1].curves[0].trackId,drafts[0].curves[0].trackId);
  }
});

test('portable ZIP and extracted directory produce the same labels and images', async t => {
  const {loadDataset} = await loader;
  const dir = await fs.mkdtemp(path.join(os.tmpdir(),'lane-loader-')); t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  const manifest = JSON.parse(await fs.readFile(path.join(root,'manifest.json'),'utf8'));
  const names = ['manifest.json',...['train','validation','test'].map(s=>`splits/${s}.json`),...manifest.samples.map(s=>s.image.path)];
  const files = await Promise.all(names.map(async name=>[name,new Blob([await fs.readFile(path.join(root,name))]) ]));
  const archive = await zip.pack(files), filename = path.join(dir,'dataset.zip');
  await fs.writeFile(filename,Buffer.from(await archive.arrayBuffer()));
  assert.deepEqual(await loadDataset(filename,{split:'test'}),await loadDataset(root,{split:'test'}));
});

test('loader rejects leaking split manifests and frame image corruption', async t => {
  const {loadDataset} = await loader;
  const dir = await fs.mkdtemp(path.join(os.tmpdir(),'lane-invalid-')); t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  await fs.cp(root,dir,{recursive:true});
  await fs.writeFile(path.join(dir,'splits/test.json'),'[]');
  await assert.rejects(loadDataset(dir,{split:'train'}),/Inconsistent test/);
  await fs.copyFile(path.join(root,'splits/test.json'),path.join(dir,'splits/test.json'));
  const manifest = JSON.parse(await fs.readFile(path.join(root,'manifest.json'),'utf8'));
  const sample = manifest.samples.find(s=>s.status==='reviewed' && manifest.sources.find(v=>v.id===s.sourceId).split==='train');
  await fs.writeFile(path.join(dir,sample.image.path),'bad png');
  await assert.rejects(loadDataset(dir),/Invalid frame image/);
});
