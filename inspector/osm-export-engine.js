/* Portable local sign-off export. No fetch, network, storage, upload or external dependencies. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.YouSpeedSignoffExport = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const own = (o,k) => Object.prototype.hasOwnProperty.call(o,k);
  const present = (o,k) => own(o,k) && o[k] !== undefined;
  const fail = m => { throw new Error('Sign-off export: ' + m); };
  const clone = x => JSON.parse(JSON.stringify(x));
  function stable(x) { return Array.isArray(x) ? '['+x.map(stable).join(',')+']' : x && typeof x==='object' ? '{'+Object.keys(x).sort().map(k=>JSON.stringify(k)+':'+stable(x[k])).join(',')+'}' : JSON.stringify(x); }
  const eq = (a,b) => stable(a) === stable(b);
  function isSpeedTag(key) {
    const parts=key.split(':');
    return parts[0]==='maxspeed' && !parts.slice(1).some(p=>['reason','type','source','note','check_date','signed','advisory','advised','practical'].includes(p));
  }
  function hasSpeedTagDelta(originalTags,targetTags) {
    if(!originalTags || !targetTags || typeof originalTags!=='object' || typeof targetTags!=='object' || Array.isArray(originalTags) || Array.isArray(targetTags)) fail('speed comparison requires tag objects');
    return [...new Set([...Object.keys(originalTags),...Object.keys(targetTags)])].some(k=>isSpeedTag(k) && !eq(originalTags[k],targetTags[k]));
  }
  function validateSourceTag(originalTags,value) {
    if(typeof value!=='string' || !value || [...value].length>255) fail('source must be a nonempty string of at most255 characters');
    xml(value);
    const existing=originalTags.source===undefined?'':originalTags.source;
    if(typeof existing!=='string') fail('original source must be preserved as text');
    if(value===existing) return;
    let appended=value;
    if(existing) {
      const prefix=existing+'; ';
      if(!value.startsWith(prefix)) fail('source must preserve the existing value and append Panoramax links');
      appended=value.slice(prefix.length);
    }
    const links=appended.split('; '),viewer=/^https:\/\/panoramax\.youspeed\.de\/#pic=[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if(!links.length || links.some(link=>!viewer.test(link))) fail('source additions must be trusted Panoramax picture viewer links');
  }
  function id(x, positive) { if(!['number','string'].includes(typeof x) || typeof x==='string' && !/^-?\d+$/.test(x)) fail('invalid OSM ID'); const n=Number(x); if(!Number.isSafeInteger(n) || n===0 || positive && n<0) fail('invalid OSM ID'); return n; }
  function num(x, label) { if(typeof x!=='number' && (typeof x!=='string' || !x.trim())) fail(label+' must be a finite number'); const n=Number(x); if(!Number.isFinite(n)) fail(label+' must be a finite number'); return n; }
  function coord(x, lat) { const n=num(x,lat?'latitude':'longitude'); if(n<(lat?-90:-180) || n>(lat?90:180)) fail('coordinate outside valid range'); return n; }
  function version(o) { if(!Number.isInteger(o.version) || o.version<1) fail('missing positive object version for '+o.id); }
  function xml(s) {
    s=String(s);
    for(const c of s) { const n=c.codePointAt(0); if(!(n===9 || n===10 || n===13 || n>=32 && n<=0xD7FF || n>=0xE000 && n<=0xFFFD || n>=0x10000 && n<=0x10FFFF)) fail('invalid XML character'); }
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&apos;').replace(/\t/g,'&#9;').replace(/\r/g,'&#13;').replace(/\n/g,'&#10;');
  }
  function emit(type,o,action,osm) {
    const a={...(o.attributes||{})}; delete a.action; delete a.changeset;
    a.id=String(o.id); a.visible='true';
    if(o.id>0) { version(o); a.version=String(o.version); } else { delete a.version; delete a.timestamp; delete a.user; delete a.uid; }
    if(type==='node') { a.lat=o.id>0 && a.lat!==undefined ? a.lat : String(o.lat); a.lon=o.id>0 && a.lon!==undefined ? a.lon : String(o.lon); }
    if(osm && action) a.action='modify';
    const attrs=Object.keys(a).sort((x,y)=>x==='id'?-1:y==='id'?1:x.localeCompare(y)).map(k=>' '+k+'="'+xml(a[k])+'"').join('');
    let out='  <'+type+attrs+'>\n';
    if(type==='way') for(const n of o.nodes) out+='    <nd ref="'+id(n)+'"/>\n';
    if(type==='relation') for(const m of o.members) out+='    <member type="'+xml(m.type)+'" ref="'+id(m.ref)+'" role="'+xml(m.role)+'"/>\n';
    for(const k of Object.keys(o.tags||{}).sort()) out+='    <tag k="'+xml(k)+'" v="'+xml(o.tags[k])+'"/>\n';
    return out+'  </'+type+'>\n';
  }
  function metric(a,b) { const f=Math.PI/180*6371008.8, c=Math.cos(48.84*Math.PI/180); return Math.hypot((a.lon-b.lon)*f*c,(a.lat-b.lat)*f); }
  function segment(a,b,p) { const f=Math.PI/180*6371008.8,c=Math.cos(48.84*Math.PI/180),dx=(b.lon-a.lon)*f*c,dy=(b.lat-a.lat)*f,px=(p.lon-a.lon)*f*c,py=(p.lat-a.lat)*f,ll=dx*dx+dy*dy,t=ll?(px*dx+py*dy)/ll:0; return {t,d:Math.hypot(px-t*dx,py-t*dy)}; }
  function direction(value, attached) {
    if(value===null || value===undefined || String(value).trim()==='') return null;
    const s=String(value).trim();
    if(/^(N|NNE|NE|ENE|E|ESE|SE|SSE|S|SSW|SW|WSW|W|WNW|NW|NNW)$/.test(s)) return s;
    if(s==='forward' || s==='backward') { if(!attached) fail('forward/backward direction requires a loaded parent way; use a bearing for a standalone sign'); return s; }
    const n=num(s,'direction'); if(n<0 || n>=360) fail('direction bearing must be between 0 inclusive and 360 exclusive'); return String(n);
  }
  function assembleSignoffExport(model, decisions) {
    if(!model || model.schema!=='youspeed.human-signoff-export-model.v1') fail('unsupported model schema');
    const d=decisions||{}, wayInput=d.wayIds||[], wayEdits=d.wayEdits||[], edits=d.nodeEdits||{};
    if(!Array.isArray(wayInput) || !Array.isArray(wayEdits) || !edits || typeof edits!=='object' || Array.isArray(edits)) fail('wayIds/wayEdits must be arrays and nodeEdits an ID-keyed object');
    const selections=new Map();
    function select(wid,mode,childId) {
      const choice={wayId:id(wid,true),mode};if(mode==='whole') choice.childId=id(childId);
      const previous=selections.get(choice.wayId);
      if(previous && !eq(previous,choice)) fail('one original way cannot have conflicting whole/split or child choices');
      selections.set(choice.wayId,choice);
    }
    for(const wid of wayInput) select(wid,'split');
    for(const edit of wayEdits) {
      if(!edit || typeof edit!=='object' || Array.isArray(edit) || !['whole','split'].includes(edit.mode)) fail('way edit requires whole or split mode');
      if(edit.mode==='whole' && !present(edit,'childId')) fail('whole-way change requires an explicit source childId; choose the speed/constraint tag set');
      if(edit.mode==='split' && present(edit,'childId')) fail('split mode approves every child, not one childId');
      if(['tags','updates','nodes'].some(k=>present(edit,k))) fail('way edit must use the fixed source tag set and geometry, not free-form overrides');
      select(edit.wayId,edit.mode,edit.childId);
    }
    const selected=[...selections.keys()].sort((a,b)=>a-b), selectedModes=selected.map(wid=>selections.get(wid)), candidateIds=Object.keys(edits).sort();
    if((selected.length || candidateIds.length) && d.modelRevision!==model.revision) fail('missing or stale modelRevision; review the current revision again');
    if(d.modelRevision!==undefined && d.modelRevision!==model.revision) fail('stale modelRevision');
    const base=model.baseline, plans=model.wayPlans, relations=model.relationRecipes||{}, newGeometry=model.newRoadNodes||{};
    if(!base || !base.nodes || !base.ways || !base.relations) fail('missing baseline');
    // A baseline is existing OSM context, never a second channel for unsigned draft objects.
    for(const [key,n] of Object.entries(base.nodes)) {
      if(id(key,true)!==n.id) fail('baseline node key/ID mismatch');version(n);coord(n.lat,true);coord(n.lon,false);
      if(n.attributes && (own(n.attributes,'lat') && Number(n.attributes.lat)!==n.lat || own(n.attributes,'lon') && Number(n.attributes.lon)!==n.lon)) fail('baseline node coordinate representations differ');
    }
    for(const [key,w] of Object.entries(base.ways)) {
      if(id(key,true)!==w.id) fail('baseline way key/ID mismatch');version(w);
      if(!Array.isArray(w.nodes) || w.nodes.length<2 || w.nodes.some(n=>id(n,true)!==n || !own(base.nodes,String(n)))) fail('baseline way has missing or non-existing node references');
    }
    for(const [key,r] of Object.entries(base.relations)) {
      if(id(key,true)!==r.id) fail('baseline relation key/ID mismatch');version(r);
      if(!Array.isArray(r.members) || r.members.some(m=>!['node','way','relation'].includes(m.type) || id(m.ref,true)!==m.ref || typeof m.role!=='string')) fail('baseline relation contains invalid or unsigned members');
    }
    const selectedSet=new Set(selected.filter(wid=>selections.get(wid).mode==='split')), changes={create:{nodes:{},ways:{}},modify:{nodes:{},ways:{},relations:{}}}, contextNodes={}, contextWays={}, contextRelations={}, relationProofs=[], atomic=[], wholeWayTagEdits=[], noops=[];
    const allChildOwners={}, allNewNodeOwners={};
    for(const [wid,p] of Object.entries(plans)) for(const child of p.children) {
      if(child.id<0) { if(own(allChildOwners,String(child.id))) fail('new way ID has multiple owners'); allChildOwners[String(child.id)]=id(wid,true); }
      for(const n of child.nodes) if(n<0) { const k=String(n); (allNewNodeOwners[k]||(allNewNodeOwners[k]=new Set())).add(id(wid,true)); }
    }
    function baseNode(n) { const k=String(id(n,true)); if(!own(base.nodes,k)) fail('missing baseline node '+n); const o=base.nodes[k]; version(o); coord(o.lat,true); coord(o.lon,false); return o; }
    function geometryNode(n) { if(n>0) return baseNode(n); const k=String(id(n)); if(!own(newGeometry,k)) fail('missing new geometry node '+n); const o=newGeometry[k]; if(o.id!==n) fail('new node ID mismatch'); coord(o.lat,true);coord(o.lon,false);return o; }
    function validatePlan(p,wid,split) {
      const review=p.directionReview;
      if(review!==undefined) {
        if(!review || typeof review!=='object' || Array.isArray(review) || typeof review.exportAllowed!=='boolean' || typeof review.allowWholeWay!=='boolean') fail('invalid direction-review metadata for '+wid);
        if(!review.exportAllowed) fail('way '+wid+' is held by direction/scope review: '+(review.reason||review.status||'unresolved'));
        if(!split && !review.allowWholeWay) fail('whole-way scope is not approved for '+wid+'; use the reviewed split interval');
      }
      const original=base.ways[String(wid)]; if(!original || p.originalWayId!==wid) fail('unknown original way '+wid);version(original);
      if(p.version!==original.version || !eq(p.originalNodes,original.nodes) || !eq(p.originalTags,original.tags)) fail('way plan version or baseline mismatch '+wid);
      if(!Array.isArray(p.children) || p.children.length<(split?2:1)) fail('way bundle must contain every split child');
      const retained=p.children.filter(c=>c.id===wid); if(retained.length!==1) fail('original way ID must survive exactly once');
      let joined=[], positive=[], previous=null;
      for(const child of p.children) {
        id(child.id); if(child.id>0 && child.id!==wid) fail('child changes an unrelated positive way');
        if(child.id<0 && allChildOwners[String(child.id)]!==wid) fail('child ownership mismatch');
        if(!eq(child.tags,{...original.tags,...child.updates})) fail('child tags differ from the complete approved bundle');
        if(Object.keys(child.updates).some(k=>!k.startsWith('maxspeed') && k!=='source:maxspeed' && k!=='source')) fail('unexpected non-speed tag update in fixed way bundle');
        if(own(child.updates,'source')) validateSourceTag(original.tags,child.updates.source);
        if(!Array.isArray(child.nodes) || child.nodes.length<2 || previous!==null && previous!==child.nodes[0]) fail('split child connectivity broken');
        let length=0; for(let i=0;i<child.nodes.length;i++) { const n=id(child.nodes[i]); const o=geometryNode(n); if(i) length+=metric(geometryNode(child.nodes[i-1]),o); }
        if(length<2-1e-5) fail('split creates a child shorter than 2m');
        joined.push(...(joined.length?child.nodes.slice(1):child.nodes)); previous=child.nodes[child.nodes.length-1];
      }
      if(split && !p.children.some(child=>hasSpeedTagDelta(original.tags,child.tags))) fail('source-only/metadata-only changes do not justify splitting a way');
      positive=joined.filter(n=>n>0); if(!eq(joined,p.augmentedNodes) || !eq(positive,original.nodes)) fail('original node order/geometry not preserved');
      let lastOriginal=null, pending=[];
      for(const n of joined) {
        if(n<0) { pending.push(n);continue; }
        if(pending.length) {
          if(lastOriginal===null) fail('new geometry outside original endpoints');let lastT=0;
          for(const pn of pending) { const v=segment(baseNode(lastOriginal),baseNode(n),geometryNode(pn));if(v.t<=0 || v.t>=1 || v.t<lastT || v.d>0.02) fail('new road node is not ordered on its original segment');lastT=v.t; }
          pending=[];
        }
        lastOriginal=n;
      }
      if(pending.length) fail('new geometry after original endpoint');
      const declared=[...new Set(joined.filter(n=>n<0))].sort((a,b)=>a-b);if(!eq(declared,[...p.newNodeIds].sort((a,b)=>a-b))) fail('new node closure mismatch');
      if(split) for(const n of declared) for(const owner of allNewNodeOwners[String(n)]) if(!selectedSet.has(owner)) fail('shared new road node requires approval of every owning original-way split bundle');
      return original;
    }
    for(const wid of selected) {
      if(!own(plans,String(wid))) fail('unknown or deferred way bundle '+wid);const p=plans[String(wid)],choice=selections.get(wid),original=validatePlan(p,wid,choice.mode==='split');
      if(choice.mode==='whole') {
        const source=p.children.find(child=>child.id===choice.childId);if(!source) fail('whole-way source child does not belong to selected original way');
        const changed=!eq(source.tags,original.tags);
        if(changed && !hasSpeedTagDelta(original.tags,source.tags)) fail('source-only/metadata-only child is not a whole-way speed change');
        wholeWayTagEdits.push({originalWayId:wid,planHash:p.planHash,sourceChildId:source.id,updates:clone(source.updates),targetTags:clone(source.tags),requiredCandidateIds:[...(source.candidateIds||p.requiredCandidateIds)],geometryUnchanged:true,relationsUnchanged:true,changed,...(p.directionReview?{directionReview:clone(p.directionReview)}:{})});
        if(!changed) { noops.push({wayId:wid,mode:'whole',sourceChildId:source.id,reason:'chosen speed/constraint tag set already matches the original whole way'});continue; }
        changes.modify.ways[String(wid)]={...clone(original),tags:clone(source.tags)};
        for(const n of original.nodes) contextNodes[String(n)]=clone(baseNode(n));
        continue;
      }
      for(const child of p.children) {
        const o={id:child.id,version:child.id>0?original.version:null,attributes:child.id>0?clone(original.attributes||{}):{},nodes:[...child.nodes],tags:clone(child.tags)};
        changes[child.id<0?'create':'modify'].ways[String(child.id)]=o;
        for(const n of child.nodes) if(n<0) changes.create.nodes[String(n)]=clone(geometryNode(n));else contextNodes[String(n)]=clone(baseNode(n));
      }
      atomic.push({originalWayId:wid,planHash:p.planHash,requiredCandidateIds:[...p.requiredCandidateIds],childWayIds:p.children.map(c=>c.id),newNodeIds:[...p.newNodeIds],...(p.directionReview?{directionReview:clone(p.directionReview)}:{})});
    }
    // Always start with original member order. Unselected original ways stay exactly as they were.
    for(const [rid,original] of Object.entries(base.relations)) {
      let touched=false,sawSelected=false;const members=[],proof=[];
      for(let ix=0;ix<original.members.length;ix++) {
        const m=original.members[ix];
        if(m.type!=='way' || !selectedSet.has(m.ref)) { members.push(clone(m));continue; }
        sawSelected=true;const recipe=relations[rid] && relations[rid][String(ix)],p=plans[String(m.ref)];
        if(!recipe || recipe.sourceWayId!==m.ref || !eq(recipe.expectedMember,m)) fail('missing/mismatched original relation-member recipe '+rid+':'+ix);
        let expected;
        if(original.tags.type==='restriction') {
          const via=original.members.filter(x=>x.role==='via');if(recipe.kind!=='restriction' || via.length!==1 || via[0].type!=='node' || !['from','to'].includes(m.role) || recipe.viaNodeId!==via[0].ref) fail('unsafe restriction recipe');
          const touching=p.children.filter(c=>[c.nodes[0],c.nodes[c.nodes.length-1]].includes(via[0].ref));if(touching.length!==1) fail('restriction has ambiguous via-node child');expected=[touching[0].id];
        } else {
          if(recipe.kind!=='ordered_expansion' || !['forward','backward'].includes(recipe.order)) fail('unresolved relation order');expected=p.children.map(c=>c.id);if(recipe.order==='backward') expected.reverse();
        }
        if(!eq(recipe.replacementRefs,expected)) fail('recipe contains a foreign/unapproved child or wrong order');
        const replacement=expected.map(ref=>({...m,ref}));members.push(...replacement);if(!eq(replacement,[m])) touched=true;proof.push({originalMemberIndex:ix,sourceWayId:m.ref,role:m.role,replacementRefs:expected,kind:recipe.kind});
      }
      if(touched) { version(original);changes.modify.relations[rid]={...clone(original),members};relationProofs.push({relationId:original.id,version:original.version,replacements:proof}); } else if(sawSelected) contextRelations[rid]=clone(original);
    }
    const existingTargets=new Set(),signManifest=[];
    for(const cid of candidateIds) {
      if(!own(model.nodeCandidates,cid)) fail('unknown sign candidate '+cid);const c=model.nodeCandidates[cid],edit=edits[cid];if(!edit || typeof edit!=='object' || Array.isArray(edit) || edit.approved===false) fail('invalid/unapproved node edit');
      const op=edit.operation||'create';if(!['create','modify'].includes(op)) fail('only create or modify node operations are supported');
      let o;
      if(op==='create') { const nid=id(c.newNodeId);if(nid>0 || own(newGeometry,String(nid)) || own(changes.create.nodes,String(nid))) fail('new sign node ID collides with reserved road geometry');o={id:nid,version:null,attributes:{},lat:coord(present(edit,'lat')?edit.lat:c.lat,true),lon:coord(present(edit,'lon')?edit.lon:c.lon,false),tags:{}}; }
      else {
        const nid=id(edit.targetId,true);if(!model.existingSignNodeIds.includes(nid)) fail('existing target is not a loaded sign node; use JOSM for other targets');if(existingTargets.has(nid)) fail('two approved candidates target the same existing node; conflate manually first');existingTargets.add(nid);o=clone(baseNode(nid));
        if(present(edit,'lat') && coord(edit.lat,true)!==o.lat || present(edit,'lon') && coord(edit.lon,false)!==o.lon) fail('existing node coordinates cannot be moved by this export; edit in JOSM with all parents loaded');
      }
      const value=present(edit,'trafficSign')?edit.trafficSign:present(edit,'traffic_sign')?edit.traffic_sign:c.tags.traffic_sign;
      if(typeof value!=='string' || !value.trim() || value.length>255) fail('traffic_sign must be a nonempty string of at most255 characters');xml(value);o.tags.traffic_sign=value.trim();
      const hasDirection=present(edit,'direction'),attached=o.id>0 && Object.values(base.ways).some(w=>w.nodes.includes(o.id));
      // Candidate bearings are estimates. A newly created node receives direction only if
      // the human explicitly supplies it; omitted direction on a modify preserves baseline.
      if(hasDirection) { const dr=direction(edit.direction,attached);if(dr===null) delete o.tags.direction;else o.tags.direction=dr; }
      if(op==='modify' && eq(o.tags,base.nodes[String(o.id)].tags)) { noops.push({candidateId:cid,targetId:o.id,reason:'approved values already match baseline; no object modified'});continue; }
      changes[op==='create'?'create':'modify'].nodes[String(o.id)]=o;delete contextNodes[String(o.id)];signManifest.push({candidateId:cid,operation:op,nodeId:o.id,lat:o.lat,lon:o.lon,tags:clone(o.tags)});
    }
    // Resolve every new reference and every modified way node. Other positive relation members remain external OSM references.
    for(const bucket of ['create','modify']) for(const w of Object.values(changes[bucket].ways)) for(const n of w.nodes) {
      if(n<0 && !own(changes.create.nodes,String(n))) fail('unresolved/unapproved negative node reference');
      if(n>0 && !own(contextNodes,String(n)) && !own(changes.modify.nodes,String(n))) fail('missing positive way-node context');
    }
    const hasChanges=Object.values(changes.create.nodes).length+Object.values(changes.create.ways).length+Object.values(changes.modify.nodes).length+Object.values(changes.modify.ways).length+Object.values(changes.modify.relations).length>0;
    const includeContext=d.includeContext!==false && hasChanges;
    if(includeContext) {
      for(const [nid,n] of Object.entries(base.nodes)) if(!own(changes.modify.nodes,nid)) contextNodes[nid]=clone(n);
      for(const [wid,w] of Object.entries(base.ways)) if(!own(changes.modify.ways,wid)) contextWays[wid]=clone(w);
    } else for(const key of Object.keys(contextRelations)) delete contextRelations[key];
    const external=new Map();
    for(const r of Object.values({...contextRelations,...changes.modify.relations})) for(const m of r.members) {
      if(m.ref<0) { const group=m.type==='node'?changes.create.nodes:m.type==='way'?changes.create.ways:null;if(!group || !own(group,String(m.ref))) fail('relation refers to an unapproved negative object'); }
      else {
        const included=m.type==='node'?(own(contextNodes,String(m.ref))||own(changes.modify.nodes,String(m.ref))):m.type==='way'?(own(contextWays,String(m.ref))||own(changes.modify.ways,String(m.ref))):(own(contextRelations,String(m.ref))||own(changes.modify.relations,String(m.ref)));
        if(!included) external.set(m.type+':'+m.ref,{type:m.type,id:m.ref,knownInBaseline:own(base[m.type+'s']||{},String(m.ref))});
      }
    }
    const sorted=o=>Object.values(o).sort((a,b)=>a.id-b.id),osmNodes={...contextNodes,...changes.create.nodes,...changes.modify.nodes};
    let osm='<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="YouSpeed human sign-off local download" upload="true">\n';
    for(const o of sorted(osmNodes)) osm+=emit('node',o,own(changes.create.nodes,String(o.id))||own(changes.modify.nodes,String(o.id)),true);
    for(const o of sorted({...contextWays,...changes.create.ways,...changes.modify.ways})) osm+=emit('way',o,own(changes.create.ways,String(o.id))||own(changes.modify.ways,String(o.id)),true);
    for(const o of sorted({...contextRelations,...changes.modify.relations})) osm+=emit('relation',o,own(changes.modify.relations,String(o.id)),true);osm+='</osm>\n';
    let osc='<?xml version="1.0" encoding="UTF-8"?>\n<osmChange version="0.6" generator="YouSpeed human sign-off local diff; no upload authorized">\n';
    if(Object.keys(changes.create.nodes).length||Object.keys(changes.create.ways).length) { osc+=' <create>\n';for(const o of sorted(changes.create.nodes)) osc+=emit('node',o,false,false);for(const o of sorted(changes.create.ways)) osc+=emit('way',o,false,false);osc+=' </create>\n'; }
    if(Object.keys(changes.modify.nodes).length||Object.keys(changes.modify.ways).length||Object.keys(changes.modify.relations).length) { osc+=' <modify>\n';for(const o of sorted(changes.modify.nodes)) osc+=emit('node',o,false,false);for(const o of sorted(changes.modify.ways)) osc+=emit('way',o,false,false);for(const o of sorted(changes.modify.relations)) osc+=emit('relation',o,false,false);osc+=' </modify>\n'; }osc+='</osmChange>\n';
    const objectIds={createNodes:sorted(changes.create.nodes).map(o=>o.id),createWays:sorted(changes.create.ways).map(o=>o.id),modifyNodes:sorted(changes.modify.nodes).map(o=>o.id),modifyWays:sorted(changes.modify.ways).map(o=>o.id),modifyRelations:sorted(changes.modify.relations).map(o=>o.id),unchangedContextNodes:sorted(contextNodes).map(o=>o.id),unchangedContextWays:sorted(contextWays).map(o=>o.id),unchangedContextRelations:sorted(contextRelations).map(o=>o.id)};
    const counts=Object.fromEntries(Object.entries(objectIds).map(([k,v])=>[k,v.length]));
    return {osm,osc,manifest:{schema:'youspeed.human-signoff-local-export.v1',modelRevision:model.revision,sourceHashes:clone(model.sourceHashes),selectedWayIds:selected,selectedWayModes:selectedModes,selectedNodeCandidateIds:candidateIds,atomicWayBundles:atomic,wholeWayTagEdits,nodeEdits:signManifest,noops,counts,objectIds,empty:!hasChanges,includeContext,relationRebuilds:relationProofs,externalPositiveRelationMembers:[...external.values()].sort((a,b)=>a.type.localeCompare(b.type)||a.id-b.id),localNewReferenceClosureValid:true,originalWayNodeOrderAndChildConnectivityPreserved:true,osmUploadPolicy:'true',oscIsStandardLocalDiffNotUploadAuthorization:true,osmNetworkOrUploadPerformed:false,requiresFreshCurrentVersionsInJosm:true,requiresFullJosmValidation:true,requiresDownloadIncompleteRelationMembers:external.size>0,limitations:['A split sign-off selects every child/cut of the original way; a whole-way sign-off selects one explicit source-child speed/constraint tag set and preserves all geometry/relations.','Only selected original ways, their approved split closure, recomputed split parent relations and explicitly selected sign-node edits are changed.','Use includeContext:false for a selected-way draft; unloaded positive relation members remain external references.','Snapshots are stale until refreshed; resolve versions/conflicts, download required incomplete members and run JOSM validation before any separately authorized upload.']}};
  }
  return Object.freeze({assembleSignoffExport,hasSpeedTagDelta});
});
