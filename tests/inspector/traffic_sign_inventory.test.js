const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const core = require('../../inspector/traffic-sign-inventory');
test('viewport and literal text filters bind values without changing sign-code semantics', () => {
  const q=core.querySpec({bounds:{west:8,south:48,east:9,north:49},code:'DE:331.2[]',text:"x%' OR 1=1 --"});
  assert.deepEqual(q.params.slice(0,5),[8,9,48,49,'DE:331.2[]']);
  assert.ok(!q.sql.includes('OR 1=1 --'));assert.ok(q.params[5].includes('\\%'));
  assert.equal(q.params.at(-1),401);
  assert.throws(()=>core.querySpec({bounds:{west:NaN,south:48,east:9,north:49}}));
});
test('R-tree and ordinary-index fallback return the same bounded spatial contract',()=>{
  const bounds={west:8,south:48,east:9,north:49};
  const q=core.querySpec({bounds,rtree:true,limit:5000});
  assert.match(q.sql,/JOIN traffic_sign_inventory_rtree/);assert.deepEqual(q.params,[9,8,49,48,401]);
  assert.doesNotMatch(core.querySpec({bounds}).sql,/rtree/);
});
test('only reviewed shared pictogram bytes are used, including reference-only town signs',()=>{
  const catalog=JSON.parse(fs.readFileSync('shared/tsr/prolix-de-class-catalog-v1.json'));
  const art=core.artworkIndex(catalog);
  assert.match(art.get('DE:310').url,/shared\/tsr\/sign-pictograms\/png\/de-310.png$/);
  assert.match(art.get('DE:311').url,/de-311.png$/);
  assert.equal(art.has('DE:331.2[]'),false);
  assert.equal(core.artworkIndex({signs:[{display_eligible:true,sign_code:'DE:310',image_path:'../../secret.png'}]}).size,0);
});
test('untrusted inventory metadata is escaped and source links cannot execute code',()=>{
  assert.equal(core.escapeHTML('<script>"&'), '&lt;script&gt;&quot;&amp;');
  assert.equal(core.safeLink('javascript:alert(1)'),null);
  assert.equal(core.safeLink('https://name:password@example.org'),null);
  assert.equal(core.safeLink('https://mobidata-bw.de/'),'https://mobidata-bw.de/');
});
