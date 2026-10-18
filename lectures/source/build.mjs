import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { Presentation, PresentationFile } from '@oai/artifact-tool';
import {slides,meta} from './slides.mjs';

const root=path.resolve(import.meta.dirname,'..');
const skill='/Users/raphaelvolz/.codex/plugins/cache/openai-primary-runtime/presentations/26.1017.11052/skills/presentations';
const python='/Users/raphaelvolz/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3';
const build=path.join(root,'.build');
const out=path.join(root,'output');
await fs.mkdir(build,{recursive:true});await fs.mkdir(out,{recursive:true});
await fs.mkdir(path.join(build,'renders'),{recursive:true});
const C={bg:'#F4F2EB',ink:'#0B2F38',muted:'#50646A',accent:'#C38D1A',gold:'#F5D34C',line:'#C9D3D2',white:'#FFFFFF',dark:'#092C35'};
const p=Presentation.create({slideSize:{width:1280,height:720}});
const FONT='Arial';
let current=0;
function tx(s,t,x,y,w,h,size=26,color=C.ink,bold=false,align='left'){
 const a=s.shapes.add({geometry:'textbox',name:`text-${s.shapes.items.length}`,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 a.text=t;a.text.style={fontSize:size,typeface:FONT,color,bold,alignment:align,verticalAlignment:'top',autoFit:'none',wrap:'square',insets:0};return a;
}
function box(s,t,x,y,w,h,accent=false,size=25){
 const a=s.shapes.add({geometry:'rect',name:`diagram-${t.split('\n')[0]}`,position:{left:x,top:y,width:w,height:h},fill:accent?C.ink:'#FFFFFF',line:{fill:accent?C.ink:C.line,width:1.5}});
 a.text=t;a.text.style={fontSize:size,typeface:FONT,color:accent?C.white:C.ink,bold:false,alignment:'center',verticalAlignment:'middle',autoFit:'none',insets:12};return a;
}
function arrow(s,a,b,from='right',to='left',dashed=false){s.shapes.connect(a,b,{kind:'straight',fromSide:from,toSide:to,line:{fill:C.muted,width:2,style:dashed?'dashed':'solid'},tail:{type:'triangle',width:'med',length:'med'}});}
async function img(s,name,x,y,w,h,fit='contain'){
 const buf=await fs.readFile(path.join(root,'assets',name));
 s.images.add({blob:buf.buffer.slice(buf.byteOffset,buf.byteOffset+buf.byteLength),contentType:name.endsWith('.jpg')?'image/jpeg':'image/png',alt:name,position:{left:x,top:y,width:w,height:h},fit});
}
function bottom(s,t){if(t)tx(s,t,64,607,1140,54,22,C.muted);}
function base(d,i){const s=p.slides.add();s.background.fill=C.bg;tx(s,d.title,64,48,1150,104,44,C.ink,true);tx(s,String(i+1).padStart(2,'0'),1170,674,46,22,16,C.muted,false,'right');s.speakerNotes.text=`${current}–${current+d.minutes} minutes (${d.minutes} min)\n\n${d.notes}\n\nSources (verified 18 October 2026):\n${d.sources.join('\n')}`;current+=d.minutes;return s;}
function list(s,items,x=64,y=232,w=670,size=27,gap=85){items.forEach((t,i)=>{tx(s,t,x,y+i*gap,w,gap-12,size,C.ink);});}
function cols(s,items,y=190){const n=items.length,w=(1152-(n-1)*48)/n;items.forEach((c,i)=>{const x=64+i*(w+48);tx(s,c.title,x,y,w,54,30,C.ink,true);tx(s,c.body,x,y+76,w,270,n===3?25:28,C.muted);});}
function chain(s,labels,y=190,reverse=false){const n=labels.length,w=(1152-(n-1)*34)/n;const a=labels.map((t,i)=>box(s,t,64+i*(w+34),y,w,100,i===(reverse?0:n-1),24));for(let i=1;i<a.length;i++)reverse?arrow(s,a[i],a[i-1],'left','right'):arrow(s,a[i-1],a[i]);return a;}
function diagram(s,kind){
 if(kind==='osm'){
  const a=box(s,'Contributors\niD / JOSM',64,190,230,110);const b=box(s,'OpenStreetMap\nobjects + tags',350,190,250,110,true);const c=box(s,'Regional extracts\nGeofabrik PBF',656,190,235,110);const d=box(s,'YouSpeed\noffline bundles',947,190,269,110);arrow(s,a,b);arrow(s,b,c);arrow(s,c,d);
  const e=box(s,'Panoramax\ngeolocated imagery',180,418,320,110);const f=box(s,'Human verification\nreviewed map changes',650,418,390,110);arrow(s,e,f);arrow(s,f,b,'top','bottom',true);
 }
 if(kind==='system'){
  const a=box(s,'OSM extracts',64,170,235,78),b=box(s,'SQLite bundles',399,170,290,78),c=box(s,'iPhone + Android\nlocal decisions',809,170,407,78,true);arrow(s,a,b);arrow(s,b,c);
  const d=box(s,'Selected full photos',64,300,235,88),e=box(s,'Panoramax\nblur + annotations',399,300,290,88),f=box(s,'YouSpeed PostGIS\nevidence + catalog',809,422,407,94,true);arrow(s,d,e);
  const g=box(s,'Sign observations\n+ captured crops',64,422,235,94),h=box(s,'Edge SQLite spool\nprivate signed transfer',399,422,290,94);arrow(s,g,h);arrow(s,h,f);arrow(s,e,f,'right','top');
  tx(s,'Integrated 1.4 development path',65,526,325,28,18,C.muted);tx(s,'Inspector: local files + authorized backend views',401,550,812,38,25,C.ink);
 }
 if(kind==='bundles'){
  chain(s,['OSM / PBF','Regional build','Manifest + hash','Phone SQLite'],200);
  tx(s,'Download',64,377,300,40,30,C.ink,true);tx(s,'Choose region and package version',64,435,320,110,26,C.muted);
  tx(s,'Validate',462,377,300,40,30,C.ink,true);tx(s,'Check identity, bytes and integrity',462,435,320,110,26,C.muted);
  tx(s,'Activate',860,377,300,40,30,C.ink,true);tx(s,'Match location and direction locally',860,435,338,110,26,C.muted);
 }
 if(kind==='training'){
  const upper=chain(s,['Approved imagery','Server inference','Human review'],190);
  const lower=chain(s,['Core ML / LiteRT','Train + evaluate','Frozen datasets'],412,true);
  // The lower row flows back toward deployment, forming one continuous path.
  arrow(s,upper[2],lower[2],'bottom','top');
  tx(s,'Server inference and review',64,321,760,42,25,C.muted);
  tx(s,'Training and mobile export',64,532,760,42,25,C.muted);
 }
 if(kind==='database'){
  const a=box(s,'Observations\nevents + optional crops',64,184,340,135),b=box(s,'Panoramax corpus\nitems + annotations + crops',64,376,340,135);const c=box(s,'Review + provenance\nraw predictions ≠ human truth',489,264,340,150,true),d=box(s,'Versioned catalog\ngenerations, panels, links',914,264,302,150);arrow(s,a,c);arrow(s,b,c);arrow(s,c,d);
  tx(s,'Vehicle GPS ≠ sign position\nRepeated sightings ≠ distinct signs',489,465,727,100,27,C.muted);
 }
 if(kind==='github'){
  const a=box(s,'Original project\nupstream',64,200,300,120,true),b=box(s,'Team fork on GitHub\norigin',490,200,300,120),c=box(s,'Local clone\nfiles + Git history',916,200,300,120);arrow(s,a,b);arrow(s,b,c);
  tx(s,'Fork',371,236,114,34,23,C.muted,false,'center');tx(s,'Clone',796,236,114,34,23,C.muted,false,'center');
  tx(s,'Edit → stage → commit → push to your fork',64,405,1152,60,35,C.ink,true);
  tx(s,'A reviewed pull request proposes an upstream change',64,500,1152,60,28,C.muted);
 }
}

for(const [i,d] of slides.entries()){
 const s=base(d,i);
 if(d.type==='cover'){
  s.background.fill=C.dark; // Separate text and photo preserve contrast.
  // Remove the ordinary slide heading and page marker by covering their region.
  s.shapes.add({geometry:'rect',position:{left:0,top:0,width:1280,height:720},fill:C.dark,line:{fill:'none',width:0}});
  await img(s,d.image,664,0,616,720,'cover');
  tx(s,'YouSpeed.de',64,187,600,108,68,C.white,true);
  tx(s,d.subtitle,64,318,560,136,36,C.white);
  tx(s,'19 October 2026  ·  90 minutes',64,610,575,46,25,C.gold);
 }else if(d.type==='agenda'){
  d.rows.forEach(([time,t],j)=>{tx(s,time,64,172+j*71,175,42,28,C.accent,true);tx(s,t,260,172+j*71,950,50,29,C.ink);});
 }else if(['image','assignmentSigns'].includes(d.type)){
  if(d.lead)tx(s,d.lead,64,174,704,90,31,C.ink,true);
  list(s,d.body,64,d.lead?296:180,700,26,d.type==='assignmentSigns'?85:81);
  if(i===16)await img(s,d.image,824,214,392,320);
  else await img(s,d.image,884,164,310,451);
  tx(s,d.caption??'',850,631,366,40,15,C.muted);
  if(d.type==='assignmentSigns'){await img(s,'de-310.png',64,550,128,85);await img(s,'de-311.png',238,550,128,85);tx(s,'DE:310          DE:311',64,644,420,26,20,C.muted);}
 }else if(d.type==='clients'){
  d.columns.forEach((c,j)=>{tx(s,c.title,64+j*590,174,350,50,33,C.ink,true);tx(s,c.body,64+j*590,243,340,155,26,C.muted);});
  await img(s,d.images[0],424,173,160,348);await img(s,d.images[1],1014,173,180,348);bottom(s,d.bottom);
 }else if(d.type==='columns'||d.type==='columns3'){
  cols(s,d.columns);bottom(s,d.bottom);
 }else if(d.type==='diagram'){
  diagram(s,d.diagram);bottom(s,d.bottom);
 }else if(d.type==='oracles'){
  d.rows.forEach(([n,t,b],j)=>{const y=188+j*123;tx(s,n,64,y,75,64,48,C.accent,true);tx(s,t,170,y,470,48,32,C.ink,true);tx(s,b,645,y,558,88,27,C.muted);});bottom(s,d.bottom);
 }else if(d.type==='scenario'){
  tx(s,d.lead,64,180,1152,112,36,C.ink,true);list(s,d.body,64,323,1110,29,80);bottom(s,d.bottom);
 }else if(d.type==='table'){
  const vals=[d.headers,...d.rows];const colWidths=d.headers[0]==='Family'?[284,430,438]:[230,490,432];
  const t=s.tables.add({rows:vals.length,columns:3,left:64,top:179,width:1152,height:368,columnWidths:colWidths,values:vals});
  for(let r=0;r<vals.length;r++){t.rows[r].height=r?80:54;for(let c=0;c<3;c++){const cell=t.getCell(r,c);cell.fill=r?C.bg:C.ink;cell.text.style={fontSize:r?24:25,typeface:FONT,color:r?C.ink:C.white,bold:!r,insets:10,verticalAlignment:'middle'};}}
  t.borders.assign({fill:C.line,width:1});bottom(s,d.bottom);
 }else if(d.type==='pipeline'){
  chain(s,d.steps,181);list(s,d.body,64,337,1140,28,74);bottom(s,d.bottom);
 }else if(d.type==='code'){
  tx(s,d.lead,64,171,1152,62,30,C.ink,true);
  tx(s,d.code,64,250,1152,226,d.title.includes('annotations')?25:23,C.ink);
  list(s,d.body,64,510,1130,24,53);
 }else if(d.type==='steps'){
  d.rows.forEach(([n,t,b],j)=>{const y=178+j*101;tx(s,n,64,y,80,52,30,C.accent,true);tx(s,t,172,y,370,52,29,C.ink,true);tx(s,b,576,y,640,75,26,C.muted);});bottom(s,d.bottom);
 }else if(d.type==='imagewide'){
  await img(s,d.image,64,157,775,430);list(s,d.body,878,182,332,25,132);tx(s,d.caption,64,613,1152,45,18,C.muted);
 }else if(d.type==='assignmentTraining'){
  list(s,d.body,64,174,1140,30,96);bottom(s,d.bottom);
 }else if(d.type==='assignmentLanes'){
  list(s,d.body,64,174,1140,30,96);bottom(s,d.bottom);
 }else if(d.type==='assignmentFinal'){
  list(s,d.body,64,174,1140,30,96);bottom(s,d.bottom);
 }else throw new Error('Unknown layout '+d.type);
}
if(current!==90||slides.length!==36)throw Error(`Unexpected timings ${current} / ${slides.length}`);

// Keep a readable, editable text companion including slide-specific source notes.
let elapsed=0;let notes=`# ${meta.title}: presenter notes\n\n${meta.date} · ${meta.minutes} minutes · ${slides.length} slides\n\n`;
for(const [i,d] of slides.entries()){
 notes+=`## ${String(i+1).padStart(2,'0')} · ${d.title} (${elapsed}–${elapsed+d.minutes} min)\n\n${d.notes}\n\nSources:\n\n${d.sources.map(x=>'- '+x).join('\n')}\n\n`;elapsed+=d.minutes;
}
await fs.writeFile(path.join(root,'SPEAKER_NOTES.md'),notes);
await fs.writeFile(path.join(build,'content.json'),JSON.stringify({meta,slides},null,2));
const candidate=path.join(build,'candidate.pptx');
console.log('Exporting',slides.length,'slides');
await (await PresentationFile.exportPptx(p)).save(candidate);
console.log('PPTX draft saved');
for(let i=0;i<p.slides.items.length;i++){
 const s=p.slides.items[i];const png=await p.export({slide:s,format:'png',scale:1});await fs.writeFile(path.join(build,'renders',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
 if((i+1)%6===0)console.log('Rendered',i+1);
}
// PDF is assembled from these verified renders by render_pdf.py. The bundled
// Artifact Tool PDF export currently fails on its missing Helvetica module.
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const final=path.join(out,'youspeed-lecture-2026-10-19.pptx');
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:final,pythonExecutable:python,integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','13','--require-native-table-slide','18'],fontPolicy:{basis:'design',families:[FONT]},explicitTotalSlideCount:36,requiredNativeTableOwnerSlides:[13,18],requiredNativeChartOwnerSlides:[],verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')});
console.log('Finalized',JSON.stringify(result));
