/* Local, dependency-free snapshot viewer. The analysis lives in the research CLI. */
(() => {
  'use strict';
  const report = window.HOTSPOT_REPORT;
  const $ = id => document.getElementById(id);
  const text = (id, value) => { $(id).textContent = value ?? '—'; };
  const features = value => Array.isArray(value) ? value : value?.features || [];
  const number = (value, digits = 0) => Number.isFinite(Number(value)) && value !== null && value !== '' ? Number(value).toFixed(digits) : '—';
  const signed = value => Number.isFinite(Number(value)) && value !== null ? `${Number(value) >= 0 ? '+' : '−'}${number(Math.abs(Number(value)))}` : '—';
  const substantial = c => typeof c.substantial === 'boolean' ? c.substantial : c.excess_kmh != null && c.osm_limit_kmh != null && Number(c.excess_kmh) >= Math.max(10,.2*Number(c.osm_limit_kmh));
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date = value => {
    if (!value) return 'Timestamp unavailable';
    const d = new Date(value);
    return Number.isFinite(d.getTime()) ? new Intl.DateTimeFormat('en-GB', {dateStyle:'medium',timeStyle:'short',timeZone:'Europe/Berlin'}).format(d) + ' Berlin' : String(value);
  };
  if (!report) {
    $('candidate-list').innerHTML = '<div class="empty-state">No saved analysis was found.<br>Run the research CLI to create <code>data.js</code>.</div>';
    text('snapshot-time', 'No snapshot loaded');
    return;
  }
  const speedBasis = report.speed_basis || {};
  const isAverage = speedBasis.field === 'average_speed';
  const speedLabel = isAverage ? 'Durchschnitt' : 'Traffic speed';
  const candidates = ((isAverage ? report.top5_eligible : null) || report.top10 || report.candidates || []).slice(0,isAverage ? 5 : 10).map((c, i) => ({...c, rank:c.rank ?? i+1, id:String(c.id ?? c.segment_id ?? i)}));
  const status = c => Number(c.excess_kmh) < 0 ? 'Below mapped limit' : Number(c.excess_kmh) === 0 ? 'At mapped limit' : substantial(c) ? 'Threshold met' : 'Small excess';
  document.body.classList.toggle('is-average',isAverage);
  if(isAverage){
    document.title='YouSpeed · Durchschnitt comparisons';
    $('page-title').innerHTML='Speed comparisons<span class="title-dot">.</span>';
    text('study-eyebrow','HISTORICAL SPEED × OPENSTREETMAP');
    text('snapshot-label','Saved Durchschnitt profile');
    text('time-label','PROFILE EXPORT');
    $('ranking-title').innerHTML=`Top ${candidates.length} comparisons <span id="rank-count"></span>`;
    text('speed-column-label','DURCHSCHNITT');
    text('selected-speed-label','Durchschnitt');
    text('selected-speed-description','km/h · typical day / time');
    text('difference-column-label','DIFF.');
    text('selected-difference-label','Difference');
    text('table-difference-label','Difference');
    text('confidence-label','Average confidence');
    text('selected-time-label','Profile export');
    $('source-score-row').hidden=true;
    text('confidence-note',speedBasis.confidence_note || 'Confidence for average_speed is not supplied. Current-speed c-values do not describe this historical average.');
    text('table-speed-label','Durchschnitt');
    text('table-confidence-label','Average confidence');
    text('table-caption','Top eligible Durchschnitt comparisons, including sections at or below the mapped limit. Durchschnitt is the typical historical speed for the day and time. All speeds are in km/h; confidence for the historical average is not supplied.');
    text('positive-map-key','Positive excess');
    $('nonpositive-key').hidden=false;
    text('map-title','Durchschnitt comparisons and OpenStreetMap roads');
    document.querySelector('.map-panel').setAttribute('aria-label','Map of Durchschnitt comparisons');
    $('speed-basis-description').hidden=false;
    text('speed-basis-description',speedBasis.description || 'Durchschnitt: typical historical speed for the given day and time, rather than a current measured speed.');
  }
  const roads = features(report.roads);
  const traffic = features(report.traffic);
  const summary = report.summary || {};
  const scope = report.scope || {};
  const routeSource = scope.route || report.route;
  const route = !routeSource ? [] : routeSource.type === 'Feature' ? [routeSource] : routeSource.type === 'LineString' || routeSource.type === 'MultiLineString' ? [{type:'Feature',geometry:routeSource,properties:{}}] : features(routeSource);
  const isRoute = route.length > 0 || scope.kind === 'route' || scope.route_name;
  const routeName = scope.route_name || scope.label || 'GPX route';
  const bbox = scope.bbox || report.bbox || [8.49,48.78,8.58,48.84];
  const center = scope.center || [(bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2];
  const observation = report.observation_time || report.observed_at || report.metadata?.observation_time || candidates[0]?.observed_at || candidates[0]?.observed_at_raw || traffic.find(f=>f.properties?.observed_at)?.properties.observed_at;
  const rawTime = !observation || /(?:Z|[+-]\d\d:\d\d)$/.test(String(observation)) ? date(observation) : `${String(observation).replace('T',' ').replace(/\.\d+$/,'')} · source time`;
  text('scope', isRoute ? `${routeName} · GPX route corridor · direction of travel` : `${number(center[1],5)}° N, ${number(center[0],5)}° E · zoom ${number(scope.zoom,2)} · linked map window`);
  text('snapshot-time', rawTime);
  const routeDistance = scope.route_distance_m ?? scope.route_length_m ?? summary.route_length_m;
  text('scope-size', isRoute ? `${routeDistance == null ? 'Route corridor' : number(routeDistance/1000,1) + ' km route'} · one snapshot` : `${scope.viewport?.width || 1280} × ${scope.viewport?.height || 800} window · one snapshot`);
  text('map-scope-name', isRoute ? routeName : 'Linked map window');
  $('route-key').hidden = !isRoute;
  text('map-position', `${number(center[1],3)} N  /  ${number(center[0],3)} E`);
  text('metric-traffic', isRoute ? summary.on_route_segments ?? summary.traffic_segments ?? traffic.length : summary.traffic_segments ?? traffic.length);
  text('traffic-count-label', isRoute ? 'traffic sections on route' : 'traffic sections');
  text('metric-eligible', summary.eligible_segments ?? '—');
  const candidateCount = summary.distinct_candidate_sections ?? summary.candidate_clusters ?? summary.candidate_segments ?? (report.candidates || candidates).length;
  text('metric-candidates', candidateCount);
  const substantialCount = summary.substantial_candidates ?? (report.candidates || candidates).filter(substantial).length;
  text('substantial-count', `${substantialCount} of ${candidateCount} candidate sections`);
  text('metric-excluded', isRoute ? summary.route_excluded_segments ?? summary.excluded_segments ?? '—' : summary.excluded_segments ?? '—');
  $('route-coverage-summary').hidden = !isRoute;
  if(isRoute){
    const measuredCoverage=isAverage ? summary.route_average_source_coverage_pct ?? summary.route_selected_coverage_pct ?? report.route_coverage?.average_source_coverage_pct ?? report.route_coverage?.selected_traffic_coverage_pct : summary.route_measured_coverage_pct ?? report.route_coverage?.measured_traffic_coverage_pct;
    const eligibleCoverage=summary.route_eligible_coverage_pct ?? report.route_coverage?.eligible_traffic_coverage_pct;
    text('measured-route-coverage',measuredCoverage == null ? '—' : `${number(measuredCoverage,1)}%`);
    text('eligible-route-coverage',eligibleCoverage == null ? '—' : `${number(eligibleCoverage,1)}%`);
    $('measured-route-bar').style.width=`${Math.min(100,Math.max(0,Number(measuredCoverage)||0))}%`;
    $('eligible-route-bar').style.width=`${Math.min(100,Math.max(0,Number(eligibleCoverage)||0))}%`;
    const availableCount=isAverage ? summary.on_route_average_source_segments : summary.on_route_measured_segments;
    text('source-coverage-label',isAverage ? 'Durchschnitt profile availability' : 'Measured traffic coverage');
    text('route-measured-count',availableCount == null ? '' : `${availableCount} of ${summary.on_route_segments ?? '—'} on-route sections have ${isAverage ? 'a Durchschnitt profile' : 'measured-source data'}. `);
  }
  text('rank-count', isAverage ? '· Durchschnitt' : candidates.length);
  text('footer-time', `Retrieved ${date(report.fetched_at)} · no automatic refresh`);
  text('ranking-note', isAverage ? `Top ${candidates.length} eligible comparisons by Durchschnitt minus OSM limit. Sections at or below the limit are included; only positive excesses count as candidates.` : report.ranking_note || (candidates.length < 10 ? `${candidates.length} qualifying candidate${candidates.length === 1 ? '' : 's'} ${isRoute ? 'along this route' : 'in this window'}. Excluded sections do not establish compliance.` : 'Ranked by excess over the mapped limit. Select a section to inspect its evidence.'));
  let selectedId = null;
  const rowById = new Map();
  const pathById = new Map();
  const markerById = new Map();
  $('candidate-list').innerHTML = '';
  if (!candidates.length) $('candidate-list').innerHTML = `<div class="empty-state">No ${isAverage ? 'eligible Durchschnitt comparisons' : 'qualifying candidates'} in this snapshot.<br>See exclusions and source coverage below.</div>`;
  for (const c of candidates) {
    const row = document.createElement('button');
    row.type = 'button'; row.className = 'candidate-row'; row.dataset.id = c.id;
    row.setAttribute('aria-pressed','false');
    row.setAttribute('aria-label', `${c.rank}. ${c.road_name || 'Unnamed road'}, ${c.direction || 'direction unavailable'}, ${speedLabel} ${number(c.speed_kmh)}, mapped limit ${number(c.osm_limit_kmh)}, difference ${signed(c.excess_kmh)} kilometres per hour`);
    row.innerHTML = `<span class="candidate-name"><span class="rank">${escape(c.rank)}</span><span class="candidate-description"><span class="road-name">${escape(c.road_name || 'Unnamed road')}</span><span class="road-direction">${escape(c.direction || 'Direction unavailable')} <span class="candidate-status${substantial(c) ? ' threshold-met' : ''}">· ${status(c)}</span></span></span></span><span class="candidate-value">${number(c.speed_kmh)}</span><span class="candidate-value candidate-limit">${number(c.osm_limit_kmh)}</span><span class="candidate-value candidate-excess${Number(c.excess_kmh)>0 ? '' : ' is-not-positive'}">${signed(c.excess_kmh)}</span>`;
    row.addEventListener('click', () => select(c.id));
    row.addEventListener('mouseenter', () => hover(c.id,true));
    row.addEventListener('mouseleave', () => hover(c.id,false));
    $('candidate-list').append(row); rowById.set(c.id,row);
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${escape(c.rank)}</td><td>${escape(c.road_name || 'Unnamed road')}</td><td>${escape(c.direction || '—')}</td><td>${number(c.speed_kmh)}</td><td>${number(c.osm_limit_kmh)}</td><td>${signed(c.excess_kmh)}</td><td>${status(c)}</td><td>${isAverage || c.c_value == null ? 'Not supplied' : `${number(c.c_value)} / 100`}</td><td>${number(c.match?.coverage_pct,1)}%</td>`;
    $('results-table').append(tr);
  }
  function hover(id,on) { [rowById.get(id),pathById.get(id),markerById.get(id)].filter(Boolean).forEach(el => el.classList.toggle('is-hover',on)); }
  function select(id) {
    const c = candidates.find(c => c.id === id); if (!c) return;
    selectedId = id;
    for (const [key,row] of rowById) { row.classList.toggle('is-selected',key === id); row.setAttribute('aria-pressed',String(key === id)); }
    for (const [key,path] of pathById) path.classList.toggle('is-selected',key === id);
    for (const [key,marker] of markerById) marker.classList.toggle('is-selected',key === id);
    const path = pathById.get(id); if(path) path.parentNode.append(path);
    const marker = markerById.get(id); if(marker) marker.parentNode.append(marker);
    text('selected-title', c.road_name || 'Unnamed road');
    text('selected-subtitle', `${c.direction || 'Direction unavailable'} · segment ${c.segment_id || c.id}`);
    text('selected-threshold', Number(c.excess_kmh)<0 ? `${isAverage ? 'Typical historical speed' : 'Traffic speed'} is below the mapped limit.` : Number(c.excess_kmh)===0 ? `${isAverage ? 'Typical historical speed' : 'Traffic speed'} equals the mapped limit.` : substantial(c) ? 'Meets research threshold: at least +10 km/h and +20%.' : 'Small excess · below the research threshold.');
    $('selected-threshold').classList.toggle('threshold-met',substantial(c));
    text('selected-speed', number(c.speed_kmh)); text('selected-limit', number(c.osm_limit_kmh)); text('selected-excess', signed(c.excess_kmh));
    $('selected-excess').classList.toggle('is-not-positive',Number(c.excess_kmh)<=0);
    text('selected-pct', c.excess_pct == null ? 'versus mapped limit' : `${signed(c.excess_pct)}% versus mapped limit`);
    text('selected-confidence', isAverage || c.c_value == null ? 'Not supplied' : `${number(c.c_value)} / 100`);
    text('selected-score', c.source_score == null ? 'Not supplied' : `${c.source_score}${Number(c.source_score) === 30 ? ' · measured' : ''}`);
    text('selected-coverage', c.match?.coverage_pct == null ? 'Not supplied' : `${number(c.match.coverage_pct,1)}% of section`);
    text('selected-distance', c.match?.distance_p95_m == null ? 'Not supplied' : `${number(c.match.distance_p95_m,1)} m`);
    const t = c.observed_at || c.observed_at_raw;
    text('selected-time', t && /(?:Z|[+-]\d\d:\d\d)$/.test(String(t)) ? date(t) : String(t || 'Not supplied').replace('T',' ').replace(/\.\d+$/,''));
    const way = c.match?.osm_way_ids?.[0] || c.osm_way_ids?.[0];
    $('selected-osm').href = way ? `https://www.openstreetmap.org/way/${encodeURIComponent(way)}` : `https://www.openstreetmap.org/#map=15/${center[1]}/${center[0]}`;
    $('selected-osm').textContent = way ? `View OSM way ${way} ↗` : 'View OSM source ↗';
    $('inspector').classList.remove('is-changing'); void $('inspector').offsetWidth; $('inspector').classList.add('is-changing');
  }
  const R = 6378137;
  const project = ([lon,lat]) => [R * Number(lon) * Math.PI/180, -R * Math.log(Math.tan(Math.PI/4 + Math.max(-85,Math.min(85,Number(lat))) * Math.PI/360))];
  const NW = project([bbox[0],bbox[3]]), SE = project([bbox[2],bbox[1]]);
  const world = {x:NW[0],y:NW[1],w:SE[0]-NW[0],h:SE[1]-NW[1]};
  let view = {...world};
  const map = $('map');
  const ns = 'http://www.w3.org/2000/svg';
  const make = (tag,attrs,parent) => {const el = document.createElementNS(ns,tag); for(const [k,v] of Object.entries(attrs)) el.setAttribute(k,String(v)); if(parent)parent.append(el); return el;};
  const lines = geometry => !geometry ? [] : geometry.type === 'LineString' ? [geometry.coordinates] : geometry.type === 'MultiLineString' ? geometry.coordinates : geometry.type === 'GeometryCollection' ? geometry.geometries.flatMap(lines) : [];
  const pathData = geometry => lines(geometry).map(line => line.map((coord,i) => {const p=project(coord);return `${i?'L':'M'}${p[0].toFixed(2)},${p[1].toFixed(2)}`;}).join(' ')).join(' ');
  function fit() {
    const rect = map.getBoundingClientRect(), ratio=rect.width/Math.max(1,rect.height), current=world.w/world.h;
    let w=world.w*1.04,h=world.h*1.04;
    if(current>ratio)h=w/ratio;else w=h*ratio;
    view={x:world.x+(world.w-w)/2,y:world.y+(world.h-h)/2,w,h}; updateView();
  }
  const labelRecords=[];
  const markerRecords=[];
  function updateView() {
    map.setAttribute('viewBox',`${view.x} ${view.y} ${view.w} ${view.h}`);
    const pixel = view.w / Math.max(1,map.getBoundingClientRect().width);
    for(const item of markerRecords){
      item.circle.setAttribute('r',12*pixel);item.circle.setAttribute('stroke-width',1.5*pixel);item.text.setAttribute('font-size',10*pixel);
      const offset = item.normal.map(v=>v*16*pixel);
      item.marker.setAttribute('transform',`translate(${item.anchor[0]+offset[0]} ${item.anchor[1]+offset[1]})`);
      item.leader.setAttribute('x1',-offset[0]);item.leader.setAttribute('y1',-offset[1]);
    }
    for(const item of labelRecords){item.text.setAttribute('font-size',9*pixel);item.text.setAttribute('stroke-width',3*pixel);}
  }
  const labelUsed = new Set();
  for (const f of roads) {
    const d=pathData(f.geometry); if(!d)continue;
    const p=f.properties || {}, highway=p.highway || '', major=/motorway|trunk|primary|secondary/.test(highway), minor=/service|track|path|footway/.test(highway);
    const width=major?6:minor?1.5:3.4;
    make('path',{d,class:'road-casing','stroke-width':width+1.3},$('map-roads'));
    make('path',{d,class:'road-fill','stroke-width':width},$('map-roads'));
    const name=p.ref || p.name;
    const line=lines(f.geometry).sort((a,b)=>b.length-a.length)[0];
    if(name && line?.length>2 && !labelUsed.has(name) && labelUsed.size<20 && !minor){
      const point=project(line[Math.floor(line.length/2)]);
      if(point[0]>world.x+world.w*.06 && point[0]<world.x+world.w*.94 && point[1]>world.y+world.h*.05 && point[1]<world.y+world.h*.95){
        const el=make('text',{x:point[0],y:point[1],class:'map-label'},$('map-labels'));el.textContent=name;labelRecords.push({text:el});labelUsed.add(name);
      }
    }
  }
  for(const f of traffic){const d=pathData(f.geometry);if(d)make('path',{d,class:'traffic-line'},$('map-traffic'));}
  for(const f of route){const d=pathData(f.geometry);if(d)make('path',{d,class:'route-line',stroke:'#485d56','stroke-width':2.2,'stroke-dasharray':'5 4',opacity:.8},$('map-route'));}
  for (const c of [...candidates].reverse()) {
    const geometry=c.geometry || traffic.find(f=>String(f.properties?.XDSegID ?? f.id)===c.id)?.geometry;
    const d=pathData(geometry); if(!d)continue;
    const path=make('path',{d,class:`candidate-line${Number(c.excess_kmh)>0 ? '' : ' is-not-positive'}`,'data-id':c.id},$('map-candidates')); pathById.set(c.id,path);
    path.addEventListener('click',()=>select(c.id));path.addEventListener('mouseenter',()=>hover(c.id,true));path.addEventListener('mouseleave',()=>hover(c.id,false));
    const line=lines(geometry).sort((a,b)=>b.length-a.length)[0]; if(!line?.length)continue;
    const lengths=[0]; let total=0;
    for(let i=1;i<line.length;i++){const a=project(line[i-1]),b=project(line[i]);total+=Math.hypot(b[0]-a[0],b[1]-a[1]);lengths.push(total);}
    let k=lengths.findIndex(v=>v>=total*.5);if(k<1)k=1;
    const a=project(line[Math.min(k-1,line.length-1)]),b=project(line[Math.min(k,line.length-1)]),part=(total*.5-(lengths[k-1]||0))/Math.max(.001,(lengths[k]||0)-(lengths[k-1]||0));
    const point=[a[0]+(b[0]-a[0])*part,a[1]+(b[1]-a[1])*part];
    const marker=make('g',{class:`map-marker${Number(c.excess_kmh)>0 ? '' : ' is-not-positive'}`,transform:`translate(${point[0]} ${point[1]})`,'data-id':c.id},$('map-markers'));
    const tangentLength=Math.max(.001,Math.hypot(b[0]-a[0],b[1]-a[1]));
    const normal=[-(b[1]-a[1])/tangentLength,(b[0]-a[0])/tangentLength];
    const leader=make('line',{x1:0,y1:0,x2:0,y2:0,stroke:Number(c.excess_kmh)>0 ? '#ad4428' : '#758b7e','stroke-width':1,'vector-effect':'non-scaling-stroke',opacity:.65},marker);
    const circle=make('circle',{cx:0,cy:0,r:1},marker),label=make('text',{x:0,y:0},marker);label.textContent=c.rank;
    const title=make('title',{},marker);title.textContent=`${c.rank}. ${c.road_name || 'Unnamed road'} · ${signed(c.excess_kmh)} km/h`;
    markerRecords.push({circle,text:label,marker,leader,anchor:point,normal});markerById.set(c.id,marker);
    marker.addEventListener('click',()=>select(c.id));marker.addEventListener('mouseenter',()=>hover(c.id,true));marker.addEventListener('mouseleave',()=>hover(c.id,false));
  }
  $('map-empty').hidden = roads.length+traffic.length>0;
  function zoom(factor,px=.5,py=.5){const oldW=view.w,oldH=view.h;view.w=Math.max(world.w*.035,Math.min(world.w*5,view.w*factor));view.h=view.w*(oldH/oldW);view.x+=(oldW-view.w)*px;view.y+=(oldH-view.h)*py;updateView();}
  $('zoom-in').addEventListener('click',()=>zoom(.7));$('zoom-out').addEventListener('click',()=>zoom(1/.7));$('reset-map').addEventListener('click',fit);
  $('show-traffic').addEventListener('change',event=>{$('map-traffic').style.display=event.target.checked?'':'none';});
  map.addEventListener('wheel',event=>{event.preventDefault();const r=map.getBoundingClientRect();zoom(Math.exp(Math.max(-.3,Math.min(.3,event.deltaY*.001))), (event.clientX-r.left)/r.width,(event.clientY-r.top)/r.height);},{passive:false});
  let drag=null;
  map.addEventListener('pointerdown',event=>{if(event.button!==0 || event.target.closest('.map-marker,.candidate-line'))return;drag={x:event.clientX,y:event.clientY,view:{...view}};map.setPointerCapture(event.pointerId);map.classList.add('is-dragging');});
  map.addEventListener('pointermove',event=>{if(!drag)return;const r=map.getBoundingClientRect();view.x=drag.view.x-(event.clientX-drag.x)*drag.view.w/r.width;view.y=drag.view.y-(event.clientY-drag.y)*drag.view.h/r.height;updateView();});
  const endDrag=()=>{drag=null;map.classList.remove('is-dragging');};map.addEventListener('pointerup',endDrag);map.addEventListener('pointercancel',endDrag);
  map.addEventListener('keydown',event=>{let handled=true;if(event.key==='+')zoom(.7);else if(event.key==='-')zoom(1/.7);else if(event.key==='0')fit();else if(event.key==='ArrowLeft')view.x-=view.w*.1;else if(event.key==='ArrowRight')view.x+=view.w*.1;else if(event.key==='ArrowUp')view.y-=view.h*.1;else if(event.key==='ArrowDown')view.y+=view.h*.1;else handled=false;if(handled){event.preventDefault();updateView();}});
  const method=report.methodology;
  if(Array.isArray(method)){$('methodology').innerHTML=`<ol>${method.map(v=>`<li>${escape(typeof v==='object'?JSON.stringify(v):v)}</li>`).join('')}</ol>`;}
  else if(method){$('methodology').innerHTML=`<p>${escape(typeof method==='object'?JSON.stringify(method):method)}</p>`;}
  else{$('methodology').innerHTML='<p>Traffic sections were matched to directed OSM roads. Sections with unresolved speed limits or ambiguous geometry were excluded. Candidates are ranked by aggregate speed excess over the mapped limit.</p>';}
  if(report.metadata?.provider_timestamp_note){$('timestamp-source-note').hidden=false;text('timestamp-source-note',report.metadata.provider_timestamp_note);}
  if(isRoute && report.route_coverage?.method){$('route-coverage-method').hidden=false;text('route-coverage-method',`Route coverage: ${report.route_coverage.method}`);}
  const exclusion=(isRoute ? report.route_exclusions : null) || report.exclusions || report.exclusion_counts || {};
  if(isRoute){
    text('exclusions-title','On-route exclusions');
    const offRoute=summary.off_route_segments;
    if(offRoute!=null){$('scope-exclusion-note').hidden=false;text('scope-exclusion-note',`${offRoute} nearby or opposite-direction sections fetched in the bounding boxes are outside the directed GPX scope. They are not counted as on-route ranking exclusions.`);}
  }
  const exclusionPairs=Array.isArray(exclusion)?exclusion.map(v=>[v.reason || v.label || 'Excluded',v.count??'—']):Object.entries(exclusion);
  if(!exclusionPairs.length)$('exclusion-list').innerHTML='<div><dt>See saved evidence for eligibility rules</dt><dd>—</dd></div>';
  for(const [key,value] of exclusionPairs){const row=document.createElement('div');row.innerHTML=`<dt>${escape(key.replace(/_/g,' '))}</dt><dd>${escape(typeof value==='object'?value.count??JSON.stringify(value):value)}</dd>`;$('exclusion-list').append(row);}
  const defaultSources=[{name:'Traffic snapshot · VerkehrsInfo BW',url:'https://verkehrsinfo-bw.de/?loc=48.80602,8.53271,13.41z'},{name:'OpenStreetMap · speed-limit tagging',url:'https://wiki.openstreetmap.org/wiki/Key:maxspeed'},{name:'INRIX · speed and confidence definitions',url:'https://docs.inrix.com/ra/datanetworkandxdtraffic/'}];
  const sourceList=Array.isArray(report.sources)?report.sources:defaultSources;
  for(const source of sourceList){const li=document.createElement('li');const url=source.url || source.href;const name=source.name || source.title || source.label || url || 'Source';if(url && /^https?:\/\//.test(url)){const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=name;li.append(a);}else li.textContent=name;if(source.description){li.append(document.createElement('br'),document.createTextNode(source.description));}$('source-list').append(li);}
  fit();
  new ResizeObserver(()=>fit()).observe($('map-wrap'));
  if(candidates.length)select(candidates[0].id);
})();
