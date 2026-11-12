'use strict';

function startReview(data) {
  const byId = Object.fromEntries(data.groups.map(group => [group.id, group]));
  const isGroup = group => Boolean(group?.inspectorId || group?.routeGroup);
  const hasMapPosition = group => Boolean(isGroup(group) && group.p && group.mapInScope !== false);
  const confirmedDiscrepancy = value => value === 'Misclassified' || value === 'No saved read';
  const possibleDiscrepancy = value => value === 'No matched read' || value === 'Possible wrong class';
  const $ = id => document.getElementById(id);
  const text = (tag, value, cls) => {
    const item = document.createElement(tag);
    item.textContent = value;
    if (cls) item.className = cls;
    return item;
  };
  const fmt = n => new Intl.NumberFormat('en').format(n);
  const date = value => value ? value.slice(0, 10) : 'Date unavailable';
  const counted = (n, singular, plural = singular+'s') => fmt(n)+' '+(n===1?singular:plural);
  $('snapshot-label').textContent = data.label || '';
  if (data.overlap) {
    const scope = data.overlap;
    $('overlap-summary').hidden = false;
    $('overlap-summary').textContent = 'Shared driving only · '+scope.distanceKm+' km across '+counted(scope.segments,'stretch','stretches');
    $('historical-scope').textContent =
      'The phones must be moving in the same direction with GPS fixes within '+scope.maxFixTimeS
      +' seconds and '+scope.maxFixDistanceM+' m. Historical camera positions must be within '
      +scope.evidenceDistanceM+' m of both shared tracks with a compatible direction. Counts include repeated views. '
      +'A manual Panoramax class edit requires matching sign geometry and label in the mirrored edit history.';
  }
  const totalCrops = group => group.history.reduce((n, id) => n + data.history[id].crops.length, 0);
  const colors = {Android:'#258260',iPhone:'#526ec4'};
  const summary = [[data.groups.filter(isGroup).length,'Sign groups'],[data.totals.phone,'Phone observations'],[data.totals.mobile,'Historical mobile sightings'],[data.totals.crops,'Stored mobile crops'],[data.totals.panoramax,'Panoramax annotations and crops']];
  for (const [n,label] of summary) {
    const cell=document.createElement('div');
    cell.append(text('b',fmt(n)),text('span',label));
    $('summary').append(cell);
  }

  const canvas=$('map'), ctx=canvas.getContext('2d');
  const routes=data.tracks.flatMap(track=>track.lines.flat());
  const bounds=[Math.min(...routes.map(p=>p[0])),Math.min(...routes.map(p=>p[1])),Math.max(...routes.map(p=>p[0])),Math.max(...routes.map(p=>p[1]))];
  let filtered=[], selected=null, center, zoom, rendered=[], pointer=null;
  const project=p=>[p[0]*.659,p[1]];
  function fit() {
    const a=project(bounds.slice(0,2)), b=project(bounds.slice(2));
    center=[(a[0]+b[0])/2,(a[1]+b[1])/2]; zoom=1;
  }
  fit();
  function draw() {
    const w=canvas.clientWidth,h=canvas.clientHeight,dpr=window.devicePixelRatio||1;
    if (!w||!h) return;
    if (canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)) {
      canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
    }
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
    const scale=Math.min((w-35)/((bounds[2]-bounds[0])*.659),(h-35)/(bounds[3]-bounds[1]))*zoom;
    const screen=p=>{const a=project(p);return [w/2+(a[0]-center[0])*scale,h/2-(a[1]-center[1])*scale];};
    ctx.lineWidth=1;ctx.strokeStyle='#dce6dc';
    for(let x=20;x<w;x+=48){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}
    for(let y=20;y<h;y+=48){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
    ctx.globalAlpha=.74;
    for(const track of data.tracks){
      ctx.strokeStyle=colors[track.phone];ctx.lineWidth=2;
      for(const line of track.lines){ctx.beginPath();line.forEach((p,i)=>i?ctx.lineTo(...screen(p)):ctx.moveTo(...screen(p)));ctx.stroke();}
    }
    ctx.globalAlpha=1;
    rendered=[];
    for(const group of filtered){
      if(!hasMapPosition(group))continue;
      const [x,y]=screen(group.p);
      if(x<0||x>w||y<0||y>h)continue;
      rendered.push({id:group.id,x,y});
      const alert=Object.values(group.verdicts).some(v=>v==='Misclassified'||v==='No saved read');
      ctx.fillStyle=alert?'#af412e':group.reviewCases?.length?'#136243':'#678476';
      ctx.beginPath();ctx.arc(x,y,group.reviewCases?.length?4.8:3.4,0,Math.PI*2);ctx.fill();
    }
    const current=byId[selected];
    if(hasMapPosition(current)){
      const [x,y]=screen(current.p);ctx.fillStyle='#212e28';ctx.strokeStyle='white';ctx.lineWidth=2;
      ctx.beginPath();ctx.moveTo(x,y-8);ctx.lineTo(x+8,y);ctx.lineTo(x,y+8);ctx.lineTo(x-8,y);ctx.closePath();ctx.fill();ctx.stroke();
    } else if (current?.cameraPoint || (!isGroup(current) && current?.p)) {
      const [x,y]=screen(current.cameraPoint || current.p);
      ctx.beginPath();ctx.arc(x,y,7,0,Math.PI*2);
      ctx.fillStyle='white';ctx.fill();ctx.strokeStyle='#52655c';ctx.lineWidth=2;ctx.stroke();
    }
    canvas.dataset.scale=scale;
  }
  function status(value){
    const cls=confirmedDiscrepancy(value)?'bad':possibleDiscrepancy(value)?'possible':value==='Match'||value==='Candidate match'?'good':'quiet';
    return text('span',value,'status '+cls);
  }
  function link(label, href){
    const a=text('a',label);a.href=href;a.target='_blank';a.rel='noopener noreferrer';return a;
  }
  function photoLink(r){
    const u=new URL('https://panoramax.youspeed.de/');
    u.searchParams.set('pic',r.pic);
    if(r.seq)u.searchParams.set('seq',r.seq);
    return link('Open Panoramax photo',u.href);
  }
  function referenceCaption(reference) {
    const label=reference.visualLabel || (reference.code==='yes'?'Unclassified sign':reference.code);
    const provenance=reference.manual?'Manual edit':reference.machine?'Model classification':'Detection only';
    return [label,provenance,date(reference.t)].join(' · ');
  }
  function cropCard(image,caption,alt){
    const figure=document.createElement('figure');figure.className='card';
    if(image){const img=document.createElement('img');img.src='./api/route-review/'+image;img.alt=alt;img.loading='lazy';figure.append(img);}
    figure.append(text('figcaption',caption));return figure;
  }
  if (data.additionalPhotos?.length) {
    const count = data.additionalPhotos.length;
    $('extra-photos').hidden = false;
    $('extra-photos-link').hidden = false;
    $('extra-photos-link').textContent = 'Additional photos ('+count+')';
    $('extra-photos-title').textContent = count+' photos outside the recognition journals';
    $('extra-photos-note').textContent = data.photoNote;
    for (const photo of data.additionalPhotos) {
      $('extra-photos-grid').append(cropCard(photo.image, photo.number+' · '+photo.caption, 'Android photo preview '+photo.number));
    }
    $('extra-photos-link').addEventListener('click', () => { $('extra-photos').open = true; });
  }
  function disclosure(summary){
    const element=document.createElement('details');
    element.append(text('summary',summary));return element;
  }
  function evidenceColumn(heading, id) {
    const column=document.createElement('section');
    const title=text('h3',heading);
    title.id=id;
    column.setAttribute('aria-labelledby',id);
    column.append(title);
    return column;
  }
  function compareEvidence(group, references) {
    const comparison=document.createElement('div');
    comparison.className='evidence-comparison';
    comparison.setAttribute('role','region');
    comparison.setAttribute('aria-label','Phone crops and Panoramax evidence side by side');
    for (const phone of ['Android','iPhone']) {
      const column=evidenceColumn(phone,'selected-'+phone.toLowerCase());
      column.append(status(group.verdicts[phone]));
      const passage=group.passages[phone];
      if (passage) column.append(text('p',passage.time+' · '+passage.m+' m from reference camera position','muted'));
      const observations=group[phone].map(id=>data.current[id]);
      if (!observations.length) column.append(text('p','No saved crop for this sign group.','evidence-empty'));
      for (const observation of observations) {
        column.append(cropCard(observation.image,
          observation.time+' · '+observation.label+' · '+observation.score.toFixed(3)+' · '+observation.id,
          phone+' crop labeled '+observation.label));
      }
      comparison.append(column);
    }
    const panoramax=evidenceColumn('Panoramax','selected-panoramax');
    if (!references.length) panoramax.append(text('p','No linked Panoramax annotation.','evidence-empty'));
    if (references.length) {
      const reference=references.find(item=>item.image)||references[0];
      panoramax.append(text('p',counted(references.length,'annotation'),'muted'));
      if (!reference.image) panoramax.append(text('p','Crop preview unavailable.','evidence-empty'));
      const card=cropCard(reference.image,referenceCaption(reference),
        'Panoramax reference '+(reference.visualLabel||reference.code));
      if (reference.public) card.append(photoLink(reference));
      panoramax.append(card);
      const details=disclosure('Photo and annotation records');
      const list=document.createElement('ul');list.className='evidence-list';
      for (const item of references) {
        const row=text('li',referenceCaption(item)+' · ');
        if (item.public) row.append(photoLink(item),' · ');
        row.append(item.id);list.append(row);
      }
      details.append(list);panoramax.append(details);
    }
    comparison.append(panoramax);
    return comparison;
  }
  function show(group){
    const pane=$('detail');
    if(!group){pane.replaceChildren(text('p','No signs in this view.','muted'));return;}
    pane.replaceChildren(text('h2',group.title),text('p',group.code+' · '+group.mode+' · '+group.id,'muted'));
    if(group.inspectorId){
      const positionDetails=[group.place];
      if (!group.p) positionDetails.push('Sign position unresolved');
      else if (group.mapInScope === false) positionDetails.push('Sign position outside the shared track corridor');
      if (Number.isFinite(group.positionRadius)) positionDetails.push('Position radius '+Math.round(group.positionRadius)+' m');
      if (Number.isFinite(group.azimuth)) positionDetails.push('Azimuth '+Math.round(group.azimuth)+'°');
      const location=text('p',positionDetails.join(' · '),'muted');
      const place='./#place-signs?'+new URLSearchParams({group:group.inspectorId});
      const links=document.createElement('p');
      links.append(link('Open in Zeichen vor Ort',place));
      pane.append(location,links);
    } else if(group.routeGroup){
      pane.append(text('p','Sign position unresolved. The map can show the camera position.','muted'));
    }
    if(group.reviewCases?.length){
      for(const item of group.reviewCases)pane.append(text('p',item.note));
    } else if(group.note)pane.append(text('p',group.note));
    if(group.possible?.length){
      const candidates=document.createElement('p');candidates.className='muted';candidates.append('Nearby reference candidates ');
      for(const id of group.possible.filter(id=>byId[id])){
        const target=byId[id];
        const button=text('button',target.code+' · '+(target.place||'Sign group'));
        button.addEventListener('click',()=>{
          $('scope').value=isGroup(target)?'groups':'unassigned';
          $('phone').value='';$('query').value='';refresh(id);
        });
        candidates.append(button,' ');
      }
      pane.append(candidates);
    }
    const refs=[...group.refs,...(group.contextRefs||[])].map(id=>data.refs[id])
      .sort((a,b)=>Number(b.manual)-Number(a.manual)||Number(Boolean(b.image))-Number(Boolean(a.image)));
    pane.append(compareEvidence(group,refs));
    if(group.history.length){
      const n=totalCrops(group);
      pane.append(text('h3','Mobile history · '+group.history.length+' sightings · '+n+' crops'));
      const details=disclosure('Sightings and linked crop records');
      const list=document.createElement('ul');list.className='evidence-list';
      for(const id of group.history){
        const r=data.history[id], item=text('li',date(r.t)+' · '+r.phone+' '+(r.build||'')+' · '+r.label+' · '+id);
        for(const c of r.crops){
          const line=text('p','Crop '+c.id+' · '+date(c.when),'muted');item.append(line);
          if(c.image)item.append(cropCard(c.image,'Historical mobile crop','Stored historical crop'));
        }
        list.append(item);
      }
      details.append(list);pane.append(details);
    }
    if(!refs.length&&!group.history.length)pane.append(text('p','This row has device-journal evidence only.','muted'));
    pane.scrollTop=0;
  }
  const locationURL = () => new URL(window.location.href);
  function select(id, recenter=false){
    selected=id;
    const group=byId[id];
    const position=hasMapPosition(group)?group.p:group?.cameraPoint||(!isGroup(group)?group?.p:null);
    if(recenter&&position){center=project(position);zoom=Math.max(zoom,2);}
    $('group-select').value=id||'';
    const url=locationURL();
    if(id)url.searchParams.set('group',id);
    else url.searchParams.delete('group');
    url.searchParams.set('view',$('scope').value);
    window.history.replaceState(null,'',url);
    for(const row of $('rows').children) row.classList.toggle('selected',row.dataset.id===id);
    show(group);draw();
  }
  function refresh(preferred=selected){
    const scope=$('scope').value, phone=$('phone').value, query=$('query').value.trim().toLowerCase();
    filtered=data.groups.filter(group=>{
      const verdicts=phone?[group.verdicts[phone]]:Object.values(group.verdicts);
      if((scope==='unassigned')===isGroup(group))return false;
      if(scope==='review'&&!group.reviewCases?.length)return false;
      if(scope==='reviewed-exceptions'&&(!group.reviewCases?.length||!verdicts.some(confirmedDiscrepancy)))return false;
      if(scope==='possible-exceptions'&&!verdicts.some(possibleDiscrepancy))return false;
      if(phone&&['Unverified','No comparable pass'].includes(group.verdicts[phone])&&!group[phone].length)return false;
      if(query){
        const current=[...group.Android,...group.iPhone].map(id=>data.current[id]);
        const labels=current.map(r=>r.label+' '+r.time+' '+r.id+' '+r.key).join(' ');
        const keys=[group.title,group.code,group.id,group.place,group.note||'',labels].join(' ').toLowerCase();
        if(!keys.includes(query))return false;
      }
      return true;
    });
    filtered.sort((a,b)=>Number(Boolean(b.reviewCases?.length))-Number(Boolean(a.reviewCases?.length))
      || Number(b.Android.length+b.iPhone.length>0)-Number(a.Android.length+a.iPhone.length>0)
      || a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
    $('count').textContent=scope==='unassigned'?counted(filtered.length,'evidence row'):counted(filtered.length,'sign group');
    $('group-select').replaceChildren(...filtered.map(group=>{
      const description=group.title===group.code?group.code:group.code+' · '+group.title;
      const option=text('option',[description,group.place,group.id.slice(-6)].filter(Boolean).join(' · '));
      option.value=group.id;
      return option;
    }));
    $('group-select').disabled=!filtered.length;
    $('export').disabled=!filtered.some(hasMapPosition);
    const fragment=document.createDocumentFragment();
    for(const group of filtered){
      const row=document.createElement('tr');row.dataset.id=group.id;
      const name=document.createElement('td'), button=text('button',group.title,'row-select');
      button.type='button';
      button.addEventListener('click',()=>select(group.id,true));
      const groupLabel=[group.code,group.place || (group.routeGroup?'Route group':null)].filter(Boolean).join(' · ');
      name.append(button,text('span',groupLabel,'code'));row.append(name);
      for(const p of ['Android','iPhone']){
        const cell=document.createElement('td');cell.append(status(group.verdicts[p]));
        if(group[p].length)cell.append(text('span',group[p].length+' saved','code'));
        row.append(cell);
      }
      row.append(text('td',[
        counted(group.history.length,'sighting'),
        counted(totalCrops(group),'crop'),
      ].join(' · ')));
      const panoramax=document.createElement('td');
      const manual=group.refs.filter(id=>data.refs[id].manual).length;
      if(group.refs.length||group.contextRefs?.length){
        const evidence=text('button',group.refs.length?counted(group.refs.length,'annotation'):counted(group.contextRefs.length,'related photo'),'evidence-button');
        evidence.type='button';
        evidence.addEventListener('click',()=>{
          select(group.id,true);
          $('selected-panoramax')?.scrollIntoView({block:'nearest'});
        });
        panoramax.append(evidence);
        if(manual)panoramax.append(text('span',counted(manual,'manual edit'),'code'));
      } else {
        panoramax.append(text('span','No linked annotation','muted'));
      }
      row.append(panoramax);
      fragment.append(row);
    }
    $('rows').replaceChildren(fragment);
    select(filtered.some(g=>g.id===preferred)?preferred:filtered[0]?.id);
  }
  for(const name of ['scope','phone','query'])$(name).addEventListener('input',()=>refresh());
  $('group-select').addEventListener('change',event=>select(event.target.value,true));
  $('zoomIn').addEventListener('click',()=>{zoom=Math.min(50,zoom*1.5);draw();});
  $('zoomOut').addEventListener('click',()=>{zoom=Math.max(.5,zoom/1.5);draw();});
  $('reset').addEventListener('click',()=>{fit();draw();});
  canvas.addEventListener('pointerdown',e=>{pointer={x:e.offsetX,y:e.offsetY,dx:0,dy:0};canvas.setPointerCapture(e.pointerId);});
  canvas.addEventListener('pointermove',e=>{
    if(!pointer)return;
    const dx=e.offsetX-pointer.x,dy=e.offsetY-pointer.y,scale=Number(canvas.dataset.scale);
    pointer.x=e.offsetX;pointer.y=e.offsetY;pointer.dx+=Math.abs(dx);pointer.dy+=Math.abs(dy);
    if(scale){center[0]-=dx/scale;center[1]+=dy/scale;draw();}
  });
  canvas.addEventListener('pointerup',e=>{
    if(pointer&&pointer.dx+pointer.dy<6){
      let nearest=null;
      for(const mark of rendered){
        const d=Math.hypot(mark.x-e.offsetX,mark.y-e.offsetY);
        if(d<13&&(!nearest||d<nearest.d))nearest={...mark,d};
      }
      if(nearest)select(nearest.id);
    }
    pointer=null;
  });
  canvas.addEventListener('pointercancel',()=>{pointer=null;});
  new ResizeObserver(draw).observe(canvas);
  $('export').addEventListener('click',()=>{
    const features=filtered.filter(hasMapPosition).map(g=>({type:'Feature',id:g.id,geometry:{type:'Point',coordinates:g.p},properties:{
      code:g.code,title:g.title,position_basis:g.positionBasis,position_radius_m:g.positionRadius,azimuth:g.azimuth,
      android:g.verdicts.Android,iphone:g.verdicts.iPhone,panoramax_annotations:g.refs.length,
      mobile_sightings:g.history.length,mobile_crops:totalCrops(g),note:g.note||null}}));
    const blob=new Blob([JSON.stringify({type:'FeatureCollection',features})],{type:'application/geo+json'});
    const u=URL.createObjectURL(blob), a=document.createElement('a');a.href=u;a.download='route-sign-review.geojson';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
  });
  const parameters=locationURL().searchParams;
  const requested=parameters.get('group');
  const requestedView=parameters.get('view');
  if ([...$('scope').options].some(option=>option.value===requestedView)) $('scope').value=requestedView;
  else if (requested && byId[requested]) $('scope').value=isGroup(byId[requested])?'groups':'unassigned';
  if (requested && !byId[requested]) $('group-message').textContent='That Inspector group is outside this route snapshot.';
  refresh(byId[requested]?requested:data.defaultGroup);
}
fetch('./api/route-review/data.json', {cache:'no-store'}).then(response=>{
  if (!response.ok) throw new Error('Route comparison is unavailable');
  return response.json();
}).then(data=>{
  document.getElementById('comparison').hidden=false;
  startReview(data);
  document.getElementById('load-status').hidden=true;
}).catch(()=>{
  document.getElementById('comparison').hidden=true;
  document.getElementById('load-status').textContent='Open this page on a local Inspector server configured with a route evidence directory.';
});
