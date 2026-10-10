/* Exercise the real editor controller with decoded synthetic PNGs and asynchronous API responses. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto').webcrypto;
const core = require('../../inspector/lane-annotations-core.js');
const zip = require('../../inspector/lane-dataset-zip.js');
const fixtureRoot = `${__dirname}/fixtures/lane-dataset-v1`;
const fixture = JSON.parse(fs.readFileSync(`${fixtureRoot}/manifest.json`));
const source = fixture.sources.find(s=>s.split==='train');
const script = fs.readFileSync(require.resolve('../../inspector/lane-annotations.js'),'utf8');

function editor() {
  const elements = new Map(), downloads = [], urls = new Map(), windowEvents = {}, docEvents = {};
  let file = {name:'train.mp4'}, frameGate = null, zipGate = null, requests = [];
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      id, value:'', dataset:{}, listeners:{}, options:[], hidden:false, disabled:false, open:true,
      classList:{toggle() {}}, currentTime:0,
      addEventListener(name,fn) { this.listeners[name]=fn; },
      replaceChildren() { this.options=[]; }, append(o) { this.options.push(o); },
      focus() {}, click() { if(this.download) downloads.push(urls.get(this.href)); else return this.listeners.click?.({target:this}); },
      getBoundingClientRect() { return {left:0,top:0,width:800,height:600}; },
      getContext() { return new Proxy({}, {get:()=>()=>{}}); },
      setPointerCapture() {}, releasePointerCapture() {}, contains(other) { return other===this; },
      closest() { return {hidden:false}; }
    });
    return elements.get(id);
  }
  element('track-video').parentElement = element('stage');
  element('lane-marking').value='solid';
  const window = {YouSpeedLaneCore:core,YouSpeedLaneZip:{...zip,pack:async files=>{if(zipGate)await zipGate;return zip.pack(files);}},devicePixelRatio:1,
    YouSpeedTrackVideoController:{getFile:()=>file,pause(){},showTime(time){element('track-video').currentTime=time;}},
    addEventListener(name,fn){windowEvents[name]=fn;},confirm:()=>true};
  const document = {getElementById:element, createElement:()=>element(`created-${elements.size}`),
    addEventListener(name,fn){docEvents[name]=fn;},querySelector:()=>element('toolbar')};
  vm.runInNewContext(script, {window,document,crypto,Blob,Map,console,
    ResizeObserver:class {observe(){}},setTimeout(){},AbortController,
    URL:{createObjectURL(blob){const name=`blob:${urls.size}`;urls.set(name,blob);return name;},revokeObjectURL(){}},
    createImageBitmap:async()=>({width:128,height:72,close(){}}),
    fetch:async (url,options={})=>{
      requests.push({url,method:options.method||'GET'});
      if(options.method==='DELETE') return new Response('{}');
      if(options.method==='POST') return new Response(JSON.stringify({session:'a'.repeat(32),source}));
      const index=Number(url.split('/').at(-1)); if(frameGate) await frameGate;
      const sample=fixture.samples.find(s=>s.sourceId===source.id&&s.frameIndex===index);
      return new Response(fs.readFileSync(`${fixtureRoot}/${sample.image.path}`),{headers:{'Content-Type':'image/png'}});
    }
  });
  async function change(id,value) {const e=element(`lane-${id}`);e.value=value;await e.listeners.change?.({target:e});}
  async function click(id) { await element(`lane-${id}`).listeners.click?.({target:element(`lane-${id}`)}); }
  async function exported() {
    await click('export');
    assert.ok(downloads.length,element('lane-status').textContent);
    return JSON.parse(await (await zip.unpack(downloads.at(-1))).get('manifest.json').text());
  }
  function add(points) {
    element('lane-add').listeners.click();
    const rect=core.fitRect(800,600,128,72);
    for(const [x,y] of points) element('lane-canvas').listeners.pointerdown({button:0,pointerId:1,
      clientX:rect.x+x*rect.width,clientY:rect.y+y*rect.height});
  }
  return {window,element,click,change,exported,add,requests,
    setFile(next){file=next;},gate(promise){frameGate=promise;},gateZip(promise){zipGate=promise;}};
}
const points=[[.15,.95],[.25,.75],[.35,.55],[.45,.35]];

test('frame navigation, draft reuse, independent editing and review gating survive export',async()=>{
  const app=editor();await app.click('open');app.add(points);app.add(points.map(([x,y])=>[1-x,y]));
  await app.change('marking','dashed');await app.click('confirm');
  await app.window.YouSpeedLaneAnnotations.step(1);await app.click('copy');
  assert.match(app.element('lane-status').textContent,/Entwurf \(2 Markierungen\)/);
  await app.change('curves',app.element('lane-curves').options[1].value);
  await app.click('unlink');
  await app.window.YouSpeedLaneAnnotations.step(-1);
  assert.match(app.element('lane-position').textContent,/Geprüft/);
  const data=await app.exported(), [first,second]=data.samples;
  assert.equal(first.curves.length,2);assert.equal(second.curves.length,2);assert.equal(second.status,'draft');
  assert.notEqual(first.curves[0].trackId,second.curves[0].trackId);
  assert.equal(first.curves[1].trackId,second.curves[1].trackId);
  assert.deepEqual(second.draftFrom,{sampleId:first.id,revision:first.revision});
  assert.deepEqual(core.splitManifests(data)[data.sources[0].split],[first.id]);
  assert.equal(app.requests.filter(r=>r.method==='GET').length,2,'revisit must reuse the exact cached image');
});

test('undo/redo marks restored labels as drafts and frame history is isolated',async()=>{
  const app=editor();await app.click('open');app.add(points);await app.click('confirm');
  await app.click('undo');assert.match(app.element('lane-position').textContent,/ENTWURF/);
  await app.click('redo');assert.match(app.element('lane-position').textContent,/ENTWURF/);
  await app.window.YouSpeedLaneAnnotations.step(1);
  assert.equal(app.element('lane-undo').disabled,true);
  await app.click('confirm');
  const data=await app.exported();assert.equal(data.samples[1].status,'reviewed');assert.deepEqual(data.samples[1].curves,[]);
});

test('late decoded frame is discarded after video replacement without polluting annotations',async()=>{
  const app=editor();await app.click('open');app.add(points);
  let release;app.gate(new Promise(resolve=>{release=resolve;}));
  const pending=app.window.YouSpeedLaneAnnotations.step(1);
  app.setFile({name:'different.mp4'});app.window.YouSpeedLaneAnnotations.closeVideo();release();await pending;
  assert.equal(app.window.YouSpeedLaneAnnotations.isActive(),false);
  const data=await app.exported();assert.equal(data.samples.length,1);assert.equal(data.samples[0].frameIndex,0);
  assert.ok(app.requests.some(r=>r.method==='DELETE'));
});


test('video replacement cannot reset a dataset while its export is still being packed',async()=>{
  const app=editor();await app.click('open');app.add(points);await app.click('confirm');
  let release;app.gateZip(new Promise(resolve=>{release=resolve;}));
  const pending=app.exported();
  await new Promise(resolve=>setImmediate(resolve));
  app.window.YouSpeedLaneAnnotations.closeVideo();
  assert.equal(app.element('lane-new').disabled,true);
  await app.click('new');release();
  const data=await pending;assert.equal(data.samples.length,1);assert.equal(data.samples[0].curves.length,1);
});
