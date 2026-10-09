const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const core = require('../../inspector/crop-review-core.js');
const controller = fs.readFileSync(require.resolve('../../inspector/crop-review.js'), 'utf8');
const classification = {country:'DE',canonical_code:'DE:274-50',family:'maximum_speed',value:50,unit:'km/h',role:'primary',
  mapping_revision:'registry-v1',mapping_sha256:'a'.repeat(64),model_label:null,alternatives:[]};
function crop(id='crop') {return {installation:'device',epoch:1,crop_id:id,digest:'b'.repeat(64),analysis_eligible:true,
  manifest:{observation_id:'observation-'+id,source_kind:'detector'},observation:{classification:structuredClone(classification)},
  current_revision:0,current_review:null};}
const history = (revision=0,review=null) => ({eligible:true,current_revision:revision,current_review:review,history:review?[review]:[]});
const form = {verdict:'wrong_class',corrected:classification,reviewer:'Reviewer',reason:'Readable class'};
const settle = () => new Promise(resolve => setImmediate(resolve));

test('live eligibility requires backend approval and rejects replay evidence and legacy browsing', () => {
  assert.equal(core.eligible(crop()),true);
  assert.equal(core.eligible({...crop(),analysis_eligible:undefined}),false);
  assert.equal(core.eligible(crop(),'legacy'),false);
  for (const patch of [{local_frame_token:'archive:recording:time'},{source_frame_token:'hf-replay:sha:time'},
    {local_frame_token:'dashcam_replay:frame'},{local_frame_token:'simulated:frame'}]) {
    assert.equal(core.eligible({...crop(),manifest:{...crop().manifest,...patch}}),false);
  }
  assert.equal(core.eligible({...crop(),manifest:{...crop().manifest,vehicle_position:null}}),true);
  assert.equal(core.eligible({...crop(),observation:{evidence:{quality_flags:['hf_archive_replay']}}}),false);
  assert.equal(core.eligible({...crop(),observation:{classification:{model_label:'archive building sign'}}}),true);
});

test('decisions preserve raw source and freeze identity, revision and exact canonical classification', () => {
  const row=crop(), before=JSON.stringify(row);
  const d=core.decision(row,history(4),form,'id');
  assert.equal(d.previous_revision,4);assert.equal(d.encoded_sha256,row.digest);
  assert.equal(d.observation_id,row.manifest.observation_id);
  assert.deepEqual(d.corrected_classification,classification);
  d.corrected_classification.value=80;
  assert.equal(classification.value,50);assert.equal(JSON.stringify(row),before);
  assert.equal(core.decision(row,history(4),{...form,verdict:'unreviewed'},'undo').corrected_classification,null);
  assert.throws(()=>core.decision(row,{...history(),eligible:false},form,'x'),/Live-Analyse/);
});

test('unknown replacement remains unresolved and invalid numeric/hash values cannot be saved', () => {
  assert.equal(core.decision(crop(),history(),{...form,corrected:null},'id').corrected_classification,null);
  for (const change of [{value:NaN},{value:Infinity},{country:'FR'},{mapping_sha256:'bad'}]) {
    assert.throws(()=>core.validateClassification({...classification,...change}));
  }
  assert.equal(core.validateClassification({...classification,family:'maxspeed:end',value:null,unit:null}).value,null);
  assert.equal(core.validateClassification({...classification,country:'FR',canonical_code:'B14[50]'}).canonical_code,'B14[50]');
});

test('export uses explicit latest reviewed revisions and excludes unresolved, replay and unknown provenance', () => {
  const reviewed=(id,verdict,corrected=null)=>({...crop(id),current_revision:2,current_review:{verdict,corrected_classification:corrected}});
  const rows=[reviewed('correct','confirmed'),reviewed('corrected','wrong_class',classification),reviewed('not','not_a_sign'),
    reviewed('unknown','wrong_class'),reviewed('unsure','uncertain'),reviewed('undo','unreviewed'),
    {...reviewed('old','confirmed'),analysis_eligible:false}];
  assert.deepEqual(core.exportMembers(rows).map(r=>r.crop_id),['correct','corrected','not']);
  assert.ok(core.exportMembers(rows).every(r=>r.revision===2));
  assert.deepEqual(core.exportMembers(rows,'legacy'),[]);
});

test('artwork accepts only shared local PNG assets', () => {
  assert.equal(core.safeArtwork('/shared/tsr/sign-pictograms/png/de-274.png'),'/shared/tsr/sign-pictograms/png/de-274.png');
  for (const bad of ['https://example.test/sign.png','/shared/tsr/sign-pictograms/../../secret.png','//remote/shared/tsr/sign-pictograms/x.png','data:image/png,x']) {
    assert.equal(core.safeArtwork(bad),null);
  }
});

function app(responder) {
  const elements=new Map(),calls=[],updates=[];
  function element() {return {value:'',textContent:'',children:[],hidden:false,disabled:false,attrs:{},listeners:{},dataset:{},
    addEventListener(name,fn){this.listeners[name]=fn;},setAttribute(name,value){this.attrs[name]=value;},
    removeAttribute(name){delete this.attrs[name];},replaceChildren(...children){this.children=children;},
    append(...children){this.children.push(...children);},click(){this.listeners.click?.();}};}
  const el=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
  const buttons=['wrong_class','confirmed','not_a_sign','uncertain'].map(value=>{const b=element();b.dataset.cropVerdict=value;return b;});
  const window={YouSpeedCropReviewCore:core,addEventListener(){}};
  vm.runInNewContext(controller,{window,document:{getElementById:el,createElement:element,querySelectorAll:()=>buttons},
    crypto:{randomUUID:(()=>{let i=0;return()=>`request-${++i}`;})()},URL,Blob,setTimeout,console});
  const view=window.YouSpeedCropReview.create(async(url,options)=>{calls.push({url,options});return responder(url,options);},row=>updates.push(structuredClone(row)));
  return {view,el:name=>el('crops-'+name),buttons,calls,updates};
}
function standard(url,options) {
  if(url.endsWith('/taxonomy'))return {entries:[{label:'50',image_path:'tsr/sign-pictograms/png/de-274.png',classification}]};
  if(url.endsWith('/history'))return history();
  throw Error('Unexpected route '+url);
}

test('no review credential is sent or persisted until an operator supplies it', async () => {
  const a=app(standard);a.view.setPage([crop()],'live');await a.view.select(crop());assert.equal(a.calls.length,0);
  a.el('review-token').value='private-key';await a.view.select(crop());
  assert.equal(a.calls.length,2);assert.ok(a.calls.every(c=>c.options.headers.Authorization==='Bearer private-key'));
  assert.equal(a.el('review-fields').disabled,false);
});

test('old asynchronous review response cannot overwrite the next selected crop', async () => {
  let resolveFirst;
  const a=app((url,options)=>url.endsWith('/history') && JSON.parse(options.body).crop_id==='first'
    ? new Promise(resolve=>{resolveFirst=resolve;}) : standard(url,options));
  a.el('review-token').value='key';const first=a.view.select(crop('first'));await a.view.select(crop('second'));
  resolveFirst(history(99,{verdict:'wrong_class',revision:99}));await first;
  assert.match(a.el('review-current').textContent,/Revision 0/);assert.ok(a.updates.every(r=>r.crop_id==='second'));
});

test('unknown-result retry reuses request UUID and successful save reloads history without changing original', async () => {
  let attempts=0,revision=0;const saved=[];
  const a=app((url,options)=>{
    if(url.endsWith('/save')) {saved.push(JSON.parse(options.body).decision);attempts++;if(attempts===1)throw Error('Connection lost');revision=1;return {revision};}
    if(url.endsWith('/history'))return history(revision,revision?{verdict:'wrong_class',corrected_classification:classification,revision}:null);
    return standard(url,options);
  });
  const row=crop(),original=JSON.stringify(row.observation);a.view.setPage([row],'live');a.el('review-token').value='key';a.el('reviewer').value='Reviewer';
  await a.view.select(row);a.buttons[0].listeners.click();a.el('review-class').value='0';a.el('review-class').listeners.change();
  a.el('review-form').listeners.submit({preventDefault(){}});await settle();
  a.el('review-form').listeners.submit({preventDefault(){}});await settle();
  assert.equal(saved.length,2);assert.equal(saved[0].request_id,saved[1].request_id);assert.equal(saved[0].previous_revision,0);
  assert.equal(row.current_revision,1);assert.equal(JSON.stringify(row.observation),original);
  assert.match(a.el('review-status').textContent,/erneut geladen/);
});

test('revision conflict requires explicit reload and never silently overwrites', async () => {
  const a=app((url,options)=>{if(url.endsWith('/save'))throw Object.assign(Error('conflict'),{status:409});return standard(url,options);});
  a.el('review-token').value='key';a.el('reviewer').value='Reviewer';await a.view.select(crop());a.buttons[1].listeners.click();
  a.el('review-form').listeners.submit({preventDefault(){}});await settle();
  assert.equal(a.el('review-fields').disabled,true);assert.match(a.el('review-status').textContent,/neu laden/);
  a.el('review-form').listeners.submit({preventDefault(){}});await settle();
  assert.equal(a.calls.filter(c=>c.url.endsWith('/save')).length,1);
});

test('archive browsing cannot fetch writable review state or export reviewed imports', async () => {
  const a=app(standard);a.el('review-token').value='key';a.view.setPage([crop()],'legacy');await a.view.select(crop());
  assert.equal(a.calls.length,0);assert.equal(a.el('review-fields').disabled,true);assert.equal(a.el('export').disabled,true);
});
