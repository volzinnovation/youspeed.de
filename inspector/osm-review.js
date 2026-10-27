/* Transient OSM review workspace. No localStorage, IndexedDB, service worker or uploads to OSM. */
(() => {
  'use strict';
  const API='/inspector/api/osm', $=id=>document.getElementById('osm-'+id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let csrf='',trips=[],project=null,selected=null,filtered=[],photo=0,map=null,layers=null,busy=false,closing=false,sessionEpoch=0;
  let requests=new AbortController();
  const choices=new Map(), labels={pending:'Offen',accepted:'Bestätigt',needs_work:'Klärung',skipped:'Übersprungen',reference:'Bereits korrekt',all:'Alle'};
  const stages={queued:'Wartet …',starting:'Verarbeitung startet …',bundle:'App-Bundle wird gelesen …',panoramax:'Aufnahmen beider Richtungen werden gesucht …',proposals:'Vorschläge werden berechnet …',osm_refresh:'Aktuelle OSM-Objekte werden geprüft …',josm_validation:'JOSM prüft Tags, Geometrie und Relationen …',final_refresh:'Abschließender OSM-Abgleich …',complete:'Prüfung abgeschlossen.'};
  function cancelled(){return new DOMException('','AbortError');}
  function reportFailure(e){if(e.name!=='AbortError')error(e.message);}
  async function api(path,options={}){
    const epoch=sessionEpoch,headers={...(options.headers||{})};if(options.method&&options.method!=='GET')headers['X-OSM-CSRF']=csrf;
    const response=await fetch(API+path,{credentials:'same-origin',cache:'no-store',signal:requests.signal,...options,headers});
    const body=response.status===204?null:await response.json().catch(()=>({}));
    if(epoch!==sessionEpoch)throw cancelled();
    if(!response.ok){const failure=new Error(body?.message||'Anfrage fehlgeschlagen.');failure.code=body?.code;throw failure;}
    return body;
  }
  function error(message){$('error').textContent=message||'';$('error').hidden=!message;}
  function setBusy(value){busy=value;for(const id of ['open','files','analyze','trip','bundle','filter','way','prev','next','accept','skip','hold'])$(id).disabled=value||closing; $('analyze').disabled=value||closing||!$('trip').value||!$('bundle').value;}
  function stamp(value){if(value==null)return 'Aufnahmezeit unbekannt';const d=new Date(typeof value==='number'?value*1000:value);return Number.isFinite(d.getTime())?new Intl.DateTimeFormat('de-DE',{dateStyle:'short',timeStyle:'short',timeZone:'Europe/Berlin'}).format(d):'Aufnahmezeit unbekannt';}
  async function init(){
    try{
      const fragment=new URLSearchParams(location.hash.slice(1)),token=fragment.get('session');
      if(token){history.replaceState(null,'',location.pathname+location.search);const response=await fetch(API+'/session/resume',{method:'POST',headers:{Authorization:'Bearer '+token},credentials:'same-origin'});if(!response.ok)throw Error('Der App-Link ist abgelaufen. Bitte die Fahrt erneut teilen.');csrf=(await response.json()).csrf;}
      else{try{csrf=(await api('/session')).csrf;}catch{csrf=(await api('/session',{method:'POST'})).csrf;}}
      const data=await api('/bundles');$('bundle').replaceChildren(...data.bundles.map(b=>new Option(b.name+' · '+b.bundle_version,b.id)));
      if(data.bundles.some(b=>b.id==='baden-wuerttemberg'))$('bundle').value='baden-wuerttemberg';
      trips=(await api('/trips')).trips;renderTrips();$('close').hidden=false;
    }catch(e){reportFailure(e);}
  }
  function renderTrips(){const old=$('trip').value;$('trip').replaceChildren(new Option(trips.length?'Fahrt auswählen':'Fahrt-ZIP öffnen',''),...trips.map(t=>new Option(stamp(t.started_at)+' · '+(t.start_place||'Start unbekannt').replace(/\n/g,' ')+ ' → '+(t.end_place||'Ziel unbekannt').replace(/\n/g,' ')+' · '+(t.distance_m/1000).toLocaleString('de-DE',{maximumFractionDigits:1})+' km',t.id)));if(trips.some(t=>t.id===old))$('trip').value=old;else if(trips.length)$('trip').value=trips.at(-1).id;$('analyze').disabled=!$('trip').value||!$('bundle').value;}
  $('open').onclick=()=>$('files').click();
  $('files').onchange=async e=>{
    const epoch=sessionEpoch;error('');setBusy(true);
    try{
      // A tab left open overnight may have outlived its RAM session.
      try{csrf=(await api('/session')).csrf;}catch(expired){
        if(!['session_expired','session_required'].includes(expired.code))throw expired;
        csrf=(await api('/session',{method:'POST'})).csrf;trips=[];project=null;selected=null;choices.clear();
      }
      $('close').hidden=false;
      for(const file of e.target.files){if(file.size>64*1024**2)throw Error('Der Fahrt-Export ist größer als 64 MB. Bitte nur die Fahrt und benötigte Bilder teilen.');$('stage').textContent='Fahrt wird eingelesen …';const result=await api('/trips',{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});trips=result.trips;}renderTrips();project=null;$('review').hidden=true;$('welcome').hidden=false;$('actions').hidden=true;$('stage').textContent='Fahrt geladen. App-Bundle wählen und Vorschläge berechnen.';}catch(e){reportFailure(e);}finally{if(epoch===sessionEpoch){setBusy(false);e.target.value='';}}
  };
  $('trip').onchange=async()=>{error('');project=null;selected=null;choices.clear();$('review').hidden=true;$('welcome').hidden=false;$('actions').hidden=true;$('analyze').disabled=!$('trip').value;try{if($('trip').value)await loadProject();}catch(e){if(e.code!=='project_not_ready')reportFailure(e);}};
  $('bundle').onchange=()=>$('analyze').disabled=!$('trip').value||!$('bundle').value;
  function json(body){return {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};}
  async function waitJob(id){
    const epoch=sessionEpoch;
    for(;;){if(epoch!==sessionEpoch)throw cancelled();const job=await api('/jobs/'+id);$('stage').textContent=stages[job.stage]||'Verarbeitung läuft …';if(job.state==='complete')return job.result;if(job.state==='failed')throw Object.assign(Error(job.result?.message||'Prüfung fehlgeschlagen.'),{code:job.result?.code});await new Promise(resolve=>setTimeout(resolve,1200));}
  }
  $('analyze').onclick=async()=>{const epoch=sessionEpoch;error('');setBusy(true);try{const result=await api('/trips/'+$('trip').value+'/analyze',json({request_id:crypto.randomUUID(),bundle_id:$('bundle').value}));await waitJob(result.job_id);await loadProject();$('stage').textContent='Vorschläge bereit.';}catch(e){reportFailure(e);}finally{if(epoch===sessionEpoch)setBusy(false);}};
  async function loadProject(){project=await api('/trips/'+$('trip').value+'/proposals');$('review').hidden=false;$('welcome').hidden=true;photo=0;renderNav();render();}
  function renderNav(){if(!project)return;const status=$('filter').value;filtered=project.proposals.filter(p=>status==='all'||p.status===status);for(const option of $('filter').options)option.textContent=labels[option.value]+' ('+(option.value==='all'?project.proposals.length:project.proposals.filter(p=>p.status===option.value).length)+')';if(!filtered.some(p=>p.id===selected))selected=filtered[0]?.id||null;$('way').replaceChildren(...filtered.map((p,i)=>new Option((i+1)+' / '+filtered.length+' · '+p.title,p.id)));$('way').value=selected||'';$('prev').disabled=$('next').disabled=filtered.length<2;}
  function choose(id){selected=id;photo=0;renderNav();render();window.scrollTo({top:$('review').offsetTop-84,behavior:'smooth'});}
  $('filter').onchange=()=>{selected=null;photo=0;renderNav();render();};$('way').onchange=()=>choose($('way').value);
  function next(delta){const i=filtered.findIndex(p=>p.id===selected);if(filtered.length)choose(filtered[(i+delta+filtered.length)%filtered.length].id);}
  $('prev').onclick=()=>next(-1);$('next').onclick=()=>next(1);
  function hasSpeed(c,p){return Object.entries(c.updates||{}).some(([k,v])=>k.startsWith('maxspeed')&&p.current_tags?.[k]!==v);}
  function mode(p){if(!choices.has(p.id)){const first=p.variants.find(v=>v.mode==='split')||p.variants[0];choices.set(p.id,first||{});}return choices.get(p.id);}
  function selectedProposal(){return project?.proposals.find(p=>p.id===selected);}
  function table(p,c,label){return '<p class="osm-segment-title">'+esc(label)+'</p><table class="osm-tag-table"><thead><tr><th>OSM-Tag</th><th>Aktuell</th><th>Vorschlag</th></tr></thead><tbody>'+Object.entries(c.updates).map(([k,v])=>'<tr><td>'+esc(k)+'</td><td>'+esc(p.current_tags?.[k]??'Nicht gesetzt')+'</td><td>'+(k==='source'?String(v).split('; ').map((s,i)=>/^https:\/\/panoramax\.youspeed\.de\/#pic=[0-9a-f-]{36}$/.test(s)?'<a href="'+esc(s)+'" target="_blank" rel="noopener">Bildquelle '+(i+1)+'</a>':esc(s)).join(' · '):esc(v))+'</td></tr>').join('')+'</tbody></table>';}
  function photos(p){return [...p.evidence.filter(e=>e.kind==='own_crop'),...p.evidence.filter(e=>e.kind!=='own_crop')];}
  function renderPhoto(p){const list=photos(p);const own=list.filter(e=>e.kind==='own_crop').length;photo=Math.min(photo,Math.max(0,list.length-1));const item=list[photo];let caption='';if(item){caption=(item.kind==='own_crop'?'Eigener Crop':'Panoramax')+' · '+stamp(item.captured_at);if(item.association==='candidate')caption+=' · Zuordnung zum selben Schild prüfen';if(item.license)caption+=' · '+item.license;if(item.producer)caption+=' · '+item.producer;if(item.url)caption+=' · <a href="'+esc(item.url)+'" target="_blank" rel="noopener">Aufnahme öffnen</a>';if(item.main_ocr?.length)caption+='<br>Hauptzeichen-OCR: '+esc(item.main_ocr.join(' · '));if(item.ocr?.length)caption+='<br>OCR: '+esc(Array.isArray(item.ocr)?item.ocr.join(' · '):item.ocr);}
    return '<h3>Bildevidenz</h3><div class="osm-photo">'+(item?'<img src="'+esc(item.kind==='own_crop'?API+'/trips/'+(item.trip_id||$('trip').value)+'/images/'+item.object:item.image_url)+'" alt="'+esc(item.kind==='own_crop'?'Eigener Zeichen-Ausschnitt':'Panoramax-Aufnahme des Schildes')+'" referrerpolicy="origin">':'<p class="osm-photo-empty">Keine passende Aufnahme verknüpft. Im Export enthaltene eigene Crops bleiben verfügbar; fehlende Bilder werden nicht ersetzt.</p>')+'</div><div class="osm-photo-tabs">'+list.map((e,i)=>'<button data-photo="'+i+'" aria-pressed="'+(i===photo)+'">'+(e.kind==='own_crop'?'Unser Crop '+(i+1):'Aufnahme '+(i-own+1))+'</button>').join('')+'</div><p class="osm-photo-caption">'+caption+'</p>';
  }
  function render(){
    if(map){map.remove();map=null;}const p=selectedProposal();$('actions').hidden=!p;
    if(!p){$('detail').innerHTML='<div class="osm-empty"><h2>Keine weiteren Vorschläge in dieser Ansicht</h2><p>Über den Statusfilter kannst du bestätigte Vorschläge oder Fälle zur Klärung ansehen.</p></div>';return;}
    const choice=mode(p),can=p.initialStatus==='pending'&&p.variants.length;
    let left='<div class="osm-scope">'+p.variants.map((v,i)=>'<label><input type="radio" name="osm-scope" value="'+i+'" '+(v.mode===choice.mode&&v.childId===choice.childId?'checked':'')+'>'+esc(v.label)+'</label>').join('')+'</div><div id="osm-map" class="osm-map" aria-label="Nur der ausgewählte OSM-Way"></div><p class="osm-direction">'+esc(p.direction==='both'?'Gleiche Regel in beiden Richtungen im markierten Abschnitt.':['forward','backward'].includes(p.direction)?'Einbahnstraße · Limit in der zulässigen Fahrtrichtung.':'Geltungsrichtung noch zu klären.')+'</p>';
    if(p.children){if(choice.mode==='whole'){const child=p.children.find(c=>c.id===choice.childId);if(child)left+=table(p,child,'Gesamter Way · Tags ändern');}else for(const c of p.children.filter(c=>hasSpeed(c,p)))left+=table(p,c,c.lengthMetres.toLocaleString('de-DE',{maximumFractionDigits:1})+' m · '+(c.id>0?'Way-ID bleibt erhalten':'Neues Teilstück'));}
    const reason=p.decision?.reason||p.reason;
    $('detail').innerHTML='<div class="osm-heading osm-new"><div class="osm-eyebrow">WAY '+p.way_id+'</div><h2>'+esc(p.title)+'</h2><p class="osm-summary">'+esc(p.summary||p.speed+' km/h · Zuordnung prüfen')+'</p><p><a href="https://www.openstreetmap.org/way/'+p.way_id+'" target="_blank" rel="noopener">Way in OpenStreetMap öffnen</a></p></div>'+(reason?'<div class="osm-note">'+esc(reason)+'</div>':'')+'<div class="osm-columns"><section class="osm-change">'+left+'</section><section id="osm-evidence" class="osm-evidence">'+renderPhoto(p)+'</section></div><details class="osm-details"><summary>Quellen und Einzelheiten</summary><p>Bundle-Basis: '+esc(p.bundle_basis)+'</p><p>Standort und Aufstellung sind Bestandsangaben. Die Kameraposition ist kein Schildstandort. OCR gilt nur mit geklärter Zuordnung zum Haupt- und Zusatzzeichen.</p><pre>'+esc(JSON.stringify({inventory:p.inventory,source_context:p.source_context,discovery:project.discovery},null,2))+'</pre></details>';
    document.querySelectorAll('[name="osm-scope"]').forEach(el=>el.onchange=()=>{choices.set(p.id,p.variants[Number(el.value)]);render();});
    $('detail').onclick=event=>{const button=event.target.closest('[data-photo]');if(button){photo=Number(button.dataset.photo);document.getElementById('osm-evidence').innerHTML=renderPhoto(p);}};
    $('accept').hidden=!can;$('accept').textContent=p.status==='accepted'?'JOSM-Datei erneut laden':'Bestätigen & JOSM-Datei laden';$('validation').textContent=p.status==='accepted'?'JOSM: 0 Fehler · 0 Warnungen':'Nur dieser Way · Prüfung vor dem Download';
    map=L.map('osm-map',{scrollWheelZoom:false}).setView([p.point[1],p.point[0]],17);YouSpeedInspectorTiles.create(L).addTo(map);layers=L.featureGroup().addTo(map);
    if(p.children&&p.geometry){for(const c of p.children){const coordinates=c.nodes.map(n=>p.geometry[String(n)]).filter(Boolean).map(([lon,lat])=>[lat,lon]);if(coordinates.length>1)L.polyline(coordinates,{color:choice.mode==='whole'||hasSpeed(c,p)?'#16946f':'#657b90',weight:choice.mode==='whole'||hasSpeed(c,p)?7:4}).addTo(layers);}if(layers.getLayers().length)map.fitBounds(layers.getBounds(),{padding:[25,25],maxZoom:18});}
    L.circleMarker([p.point[1],p.point[0]],{radius:5,color:'#152738',weight:2,fillColor:'#f7c267',fillOpacity:1}).addTo(map).bindTooltip('Geschätzter Schildstandort aus dem Bundle');
    if(!project.discovery.complete)$('stage').textContent='Bildsuche teilweise begrenzt; fehlende Evidenz bleibt sichtbar.';
  }
  async function decide(status){const p=selectedProposal();if(!p)return;const epoch=sessionEpoch;setBusy(true);error('');try{await api('/trips/'+$('trip').value+'/proposals/'+p.id+'/decision',json({request_id:crypto.randomUUID(),revision:p.revision,status}));await loadProject();}catch(e){reportFailure(e);}finally{if(epoch===sessionEpoch)setBusy(false);}}
  $('skip').onclick=()=>decide('skipped');$('hold').onclick=()=>decide('needs_work');
  async function download(job){const epoch=sessionEpoch;const response=await fetch(API+'/artifacts/'+job+'/osm',{credentials:'same-origin',cache:'no-store',signal:requests.signal});if(!response.ok){const data=await response.json();throw Error(data.message||'Download fehlgeschlagen.');}const blob=await response.blob();if(epoch!==sessionEpoch)throw cancelled();const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=(response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)||[])[1]||'youspeed-way.osm';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}
  $('accept').onclick=async()=>{const p=selectedProposal();if(!p)return;const epoch=sessionEpoch;error('');setBusy(true);try{let job=p.decision?.job_id;if(!job){const choice=mode(p);const response=await api('/trips/'+$('trip').value+'/proposals/'+p.id+'/export',json({request_id:crypto.randomUUID(),revision:p.revision,mode:choice.mode,...(choice.mode==='whole'?{childId:choice.childId}:{})}));job=response.job_id;await waitJob(job);}await download(job);await loadProject();$('stage').textContent='Geprüfte JOSM-Datei geladen. In JOSM ansehen und selbst hochladen.';}catch(e){if(e.name!=='AbortError'){error(e.message);try{await loadProject();}catch{}}}finally{if(epoch===sessionEpoch)setBusy(false);}};
  $('close').onclick=async()=>{
    if(closing)return;closing=true;$('close').disabled=true;setBusy(true);error('');
    try{
      try{if(csrf)await api('/session',{method:'DELETE'});}catch(e){if(!['session_expired','session_required'].includes(e.code))throw e;}
      sessionEpoch++;requests.abort();requests=new AbortController();
      csrf='';trips=[];project=null;selected=null;filtered=[];photo=0;choices.clear();
      if(map){map.remove();map=null;}layers=null;
      $('files').value='';$('review').hidden=true;$('welcome').hidden=false;$('actions').hidden=true;$('close').hidden=true;
      $('detail').replaceChildren();renderTrips();
      $('stage').textContent='Sitzung beendet. Die Sitzung wurde auf dem Server verworfen. Für eine neue Prüfung eine Fahrt öffnen.';
    }catch(e){error('Die Sitzung konnte auf dem Server nicht beendet werden. Bitte erneut versuchen. '+e.message);}
    finally{closing=false;$('close').disabled=false;setBusy(false);}
  };
  window.addEventListener('pagehide',()=>{if(csrf)fetch(API+'/session',{method:'DELETE',headers:{'X-OSM-CSRF':csrf},credentials:'same-origin',keepalive:true}).catch(()=>{});});
  init();
})();
