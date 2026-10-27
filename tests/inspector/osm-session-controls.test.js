const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const script=fs.readFileSync(require.resolve('../../inspector/osm-review.js'),'utf8');
async function workspace(deleteFails=false,overrides={}){
 const elements=new Map(),calls=[];let picker=0,reloads=0,sessionActive=true;
 function element(id){if(!elements.has(id))elements.set(id,{value:'',hidden:true,disabled:false,options:[],textContent:'',replaceChildren(...children){this.options=children;this.value=children[0]?.value||'';},click(){if(id==='osm-files')picker++;}});return elements.get(id);}
 const fetch=async(url,options={})=>{calls.push([url,options.method||'GET']);let data={};let status=200;
  const intercepted=overrides.fetch?.(url,options);if(intercepted)return intercepted;
  if(url.endsWith('/session')){if(options.method==='DELETE'){if(deleteFails){status=503;data={code:'source_unavailable',message:'offline'};}else{sessionActive=false;data={closed:true};}}else if(options.method==='POST'){sessionActive=true;data={csrf:'synthetic-csrf'};}else if(!sessionActive){status=401;data={code:'session_required'};}else data={csrf:'synthetic-csrf'};}
  if(url.endsWith('/bundles'))data={bundles:[{id:'qa',name:'QA',bundle_version:'v1'}]};
  if(url.endsWith('/trips'))data={trips:[{id:'synthetic-trip',started_at:1000,start_place:'QA',end_place:'QA',distance_m:100}]};
  return {ok:status<400,status,json:async()=>data};
 };
 const context={document:{getElementById:element},fetch,Option:class{constructor(text,value){this.textContent=text;this.value=value;}},URLSearchParams,AbortController,DOMException,Intl,setTimeout:overrides.setTimeout||setTimeout,clearTimeout,crypto:{randomUUID:()=> 'synthetic-request'},location:{hash:'',pathname:'/',search:'',reload(){reloads++;}},window:{addEventListener(){}},history:{replaceState(){}}};
 vm.runInNewContext(script,context);
 for(let i=0;i<20&&element('osm-close').hidden;i++)await new Promise(setImmediate);
 assert.equal(element('osm-close').hidden,false);
 return {elements,element,calls,picker:()=>picker,reloads:()=>reloads};
}
test('closing deletes the server session without opening the picker, reloading or creating another session',async()=>{
 const w=await workspace();await w.element('osm-close').onclick();
 assert.deepEqual(w.calls.filter(([,method])=>method!=='GET'),[['/inspector/api/osm/session','DELETE']]);
 assert.equal(w.picker(),0);assert.equal(w.reloads(),0);assert.equal(w.element('osm-close').hidden,true);assert.equal(w.element('osm-trip').value,'');assert.match(w.element('osm-stage').textContent,/Sitzung beendet/);assert.equal(w.element('osm-analyze').disabled,true);
 w.element('osm-open').onclick();assert.equal(w.picker(),1);
});
test('a failed server delete stays visible and keeps the session available for retry',async()=>{
 const w=await workspace(true);await w.element('osm-close').onclick();
 assert.equal(w.picker(),0);assert.equal(w.reloads(),0);assert.equal(w.element('osm-close').hidden,false);assert.equal(w.element('osm-error').hidden,false);assert.match(w.element('osm-error').textContent,/nicht beendet/);
});
test('opening a Fahrt after closing creates a new session with its close control restored',async()=>{
 const w=await workspace();await w.element('osm-close').onclick();
 const input=w.element('osm-files');input.files=[{size:10}];await input.onchange({target:input});
 assert.equal(w.element('osm-close').hidden,false);assert.equal(w.element('osm-trip').value,'synthetic-trip');
 await w.element('osm-close').onclick();
 assert.deepEqual(w.calls.filter(([,method])=>method!=='GET'),[['/inspector/api/osm/session','DELETE'],['/inspector/api/osm/session','POST'],['/inspector/api/osm/trips','POST'],['/inspector/api/osm/session','DELETE']]);
});
test('a cancelled job finishing its poll wait cannot unlock a new session import',async()=>{
 const timers=[];let completeImport;
 const response=data=>({ok:true,status:200,json:async()=>data});
 const w=await workspace(false,{
  setTimeout(callback,delay){assert.equal(delay,1200);timers.push(callback);},
  fetch(url,options){
   if(url.endsWith('/analyze'))return response({job_id:'old-job'});
   if(url.endsWith('/jobs/old-job'))return response({state:'queued',stage:'queued'});
   if(url.endsWith('/trips')&&options.method==='POST')return new Promise(resolve=>{completeImport=()=>resolve(response({trips:[{id:'new-trip',started_at:2000,start_place:'QA',end_place:'QA',distance_m:100}]}));});
  }
 });
 const oldAnalysis=w.element('osm-analyze').onclick();
 for(let i=0;i<20&&!timers.length;i++)await new Promise(setImmediate);
 assert.equal(timers.length,1,'the old job is waiting between polls');
 await w.element('osm-close').onclick();
 const input=w.element('osm-files');input.files=[{size:10}];const newImport=input.onchange({target:input});
 for(let i=0;i<20&&!completeImport;i++)await new Promise(setImmediate);
 assert.equal(typeof completeImport,'function','the next session has an import in flight');
 assert.equal(w.element('osm-open').disabled,true);
 timers.shift()();await oldAnalysis;
 assert.equal(w.element('osm-open').disabled,true,'stale job cleanup must not unlock the new import');
 assert.equal(w.element('osm-analyze').disabled,true);
 assert.equal(w.calls.filter(([url])=>url.endsWith('/jobs/old-job')).length,1,'the closed job must not be polled again');
 completeImport();await newImport;
 assert.equal(w.element('osm-trip').value,'new-trip');assert.equal(w.element('osm-open').disabled,false);assert.equal(w.element('osm-close').hidden,false);assert.equal(w.element('osm-error').hidden,true);
});
test('the upload input is genuinely hidden and has no label hitbox around the close button',()=>{
 const html=fs.readFileSync(require.resolve('../../inspector/osm.html'),'utf8');
 assert.match(html,/<button id="osm-open"[^>]*type="button"/);assert.match(html,/<input id="osm-files"[^>]*\bhidden\b/);assert.doesNotMatch(html,/<label[^>]*for="osm-files"/);assert.match(html,/<button id="osm-close"[^>]*type="button"/);
});
