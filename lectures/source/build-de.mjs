import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {Presentation,PresentationFile} from '@oai/artifact-tool';
import {meta,slides} from './slides-de.mjs';
const root=path.resolve(import.meta.dirname,'..');
const work=path.join(root,'.build/de');
const out=path.join(root,'output');
const stem='ki-intelligente-mobilitaet-2026-10-19-de-v6';
const SK='/Users/raphaelvolz/.codex/plugins/cache/openai-primary-runtime/presentations/26.1017.11052/skills/presentations';
const PY='/Users/raphaelvolz/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3';
const C={bg:'#F4F2EB',ink:'#0B2F38',muted:'#50646A',accent:'#B27D10',gold:'#F5D34C',line:'#C9D3D2',white:'#FFFFFF',dark:'#092C35'};
const FONT='Arial';
await fs.mkdir(path.join(work,'renders'),{recursive:true});await fs.mkdir(path.join(work,'validated'),{recursive:true});await fs.mkdir(out,{recursive:true});
const p=Presentation.create({slideSize:{width:1280,height:720}});let elapsed=0;
function tx(s,t,x,y,w,h,size=26,color=C.ink,bold=false,align='left'){
 const a=s.shapes.add({geometry:'textbox',name:`text-${s.shapes.items.length}`,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});a.text=t;a.text.style={fontSize:size,typeface:FONT,color,bold,alignment:align,verticalAlignment:'top',autoFit:'none',wrap:'square',insets:0};return a;
}
function link(s,label,url,x,y,w,size=22,color='#12647B'){const a=tx(s,label,x,y,w,44,size,color,false);a.text.get(label).link={uri:url,isExternal:true};a.text.get(label).underline='sng';return a;}
function box(s,t,x,y,w,h,dark=false,size=25){const a=s.shapes.add({geometry:'rect',name:`diagram-${t.split('\n')[0]}`,position:{left:x,top:y,width:w,height:h},fill:dark?C.ink:C.white,line:{fill:dark?C.ink:C.line,width:1.5}});a.text=t;a.text.style={fontSize:size,typeface:FONT,color:dark?C.white:C.ink,alignment:'center',verticalAlignment:'middle',insets:14,autoFit:'none'};return a;}
function arrow(s,a,b,from='right',to='left',kind='straight'){return s.shapes.connect(a,b,{kind,fromSide:from,toSide:to,line:{fill:C.muted,width:2},tail:{type:'triangle',width:'med',length:'med'}});}
async function img(s,name,x,y,w,h,fit='contain'){
 const buf=await fs.readFile(path.join(root,'assets/de',name));s.images.add({blob:buf.buffer.slice(buf.byteOffset,buf.byteOffset+buf.byteLength),contentType:/\.jpe?g$/.test(name)?'image/jpeg':'image/png',alt:name,position:{left:x,top:y,width:w,height:h},fit});
}
function footer(s,t,y=620){if(t)tx(s,t,64,y,1150,52,21,C.muted);}
function list(s,items,x=64,y=190,w=1140,size=28,gap=93){items.forEach((t,j)=>tx(s,t,x,y+j*gap,w,gap-12,size));}
function chain(s,labels,y=195){const w=(1152-40*(labels.length-1))/labels.length;const nodes=labels.map((t,i)=>box(s,t,64+i*(w+40),y,w,105,i===labels.length-1,25));for(let i=1;i<nodes.length;i++)arrow(s,nodes[i-1],nodes[i]);return nodes;}
function base(d,i){const s=p.slides.add();s.background.fill=C.bg;if(d.type!=='cover'&&d.type!=='questions'){tx(s,d.title,64,45,1152,110,d.title.length>54?40:44,C.ink,true);tx(s,String(i+1).padStart(2,'0'),1170,680,46,20,15,C.muted,false,'right');}s.speakerNotes.text=`${elapsed}–${elapsed+d.minutes} Minuten (${d.minutes} Min.)\n\n${d.notes}\n\nQuellen:\n${d.sources.join('\n')}`;elapsed+=d.minutes;return s;}
function diagram(s,kind){
 if(kind==='osm'){
  const n=chain(s,['Mapper\niD / JOSM','OpenStreetMap\nObjekte und Tags','Regionale Extrakte\nGeofabrik','YouSpeed\nOffline-Bundles'],185);
  const a=box(s,'Panoramax\nBildbelege + Annotationen',130,408,365,110),b=box(s,'Menschliche Prüfung\nOSM-Changeset',650,408,440,110);arrow(s,a,b);arrow(s,b,n[0],'top','bottom');
 }
 if(kind==='app'){
  const a=box(s,'Regionale Bundles\nOffline-Kartendaten',64,185,320,115),b=box(s,'KI Modelle\nZeichen, Text und Spuren',64,395,320,115),c=box(s,'iPhone / Android\nDrei Informationsquellen\nErkennung auf dem Gerät',488,281,325,170,true,25),d=box(s,'Tempohinweise\nund Rückmeldung',918,185,298,115),e=box(s,'Beobachtungen\nBildausschnitte / Fotos',918,395,298,115);arrow(s,a,c);arrow(s,b,c);arrow(s,c,d);arrow(s,c,e);tx(s,'Standort + Kamera + Sprache',450,205,425,42,23,C.muted,false,'center');
 }
 if(kind==='server'){
  const a=box(s,'App-Beiträge',64,245,214,120,true),b=box(s,'Panoramax\nFotos + Annotationen',350,170,335,105),c=box(s,'Prolix + Server-OCR\nModelle auf dem KI-Server',800,170,416,105),d=box(s,'Sichtungen / Crops\nYouSpeed PostGIS',350,348,335,105),e=box(s,'Inspector\nMenschliche Prüfung',800,348,416,105),f=box(s,'OSM-Vorschlag → Editor → bewusst veröffentlichter Changeset',160,530,1056,66,true,25);arrow(s,a,b);arrow(s,a,d);arrow(s,b,c);arrow(s,c,e,'bottom','top');arrow(s,d,e);arrow(s,e,f,'bottom','top');
 }
 if(kind==='bundles'){
  chain(s,['OSM / PBF','GitHub Actions\nBauen + Prüfen','Release-Assets\nManifest + Hash','Lokale SQLite\nin der App'],202);
  tx(s,'Offline nutzbar',64,398,350,54,32,C.ink,true);tx(s,'Straße und Richtung\nlokal zuordnen',64,466,350,100,28,C.muted);
  tx(s,'Versioniert',458,398,350,54,32,C.ink,true);tx(s,'Paketstand und\nDatenherkunft prüfen',458,466,350,100,28,C.muted);
  tx(s,'Aktualisierbar',852,398,350,54,32,C.ink,true);tx(s,'Bessere OSM-Daten\nwerden zu neuen Bundles',852,466,350,100,28,C.muted);
 }
 if(kind==='learning'){
  const a=box(s,'Menschliche Labels\nTrain / Validation / Test',64,175,340,108),b=box(s,'Training\nGewichte lernen',474,175,332,108),c=box(s,'Validierung\nModell auswählen',876,175,340,108);arrow(s,a,b);arrow(s,b,c);
  const d=box(s,'Unabhängiger Test\nQualität + Fehleranalyse',876,363,340,116,true),e=box(s,'Bereitstellung\nServer + Core ML / LiteRT',474,363,332,116),f=box(s,'Neue Datenversion\nLabel- und Fehleranalyse',64,363,340,116);arrow(s,c,d,'bottom','top');arrow(s,d,e,'left','right');arrow(s,e,f,'left','right');arrow(s,f,a,'top','bottom');
  tx(s,'Servermodell und Geräteexport werden jeweils geprüft',64,535,1152,55,29,C.muted);
 }
 if(kind==='github'){
  chain(s,['Originalprojekt\nupstream','Team-Fork\norigin','Lokaler Clone\nDateien + Historie'],205);
  tx(s,'Bearbeiten → Commit → Push in den eigenen Fork',64,405,1152,76,35,C.ink,true);
  tx(s,'Issues planen die Arbeit; Reviews und Checks prüfen Änderungen',64,510,1152,60,28,C.muted);
 }
 if(kind==='deployment'){
  const a=box(s,'Trainierter Modellstand\nGewichte + Datenversion',64,277,310,140,true),b=box(s,'Server\nProlix / KI-Dienst',490,163,310,100),c=box(s,'iPhone\nCore ML',490,313,310,100),d=box(s,'Android\nLiteRT',490,463,310,100),e=box(s,'Prüfen\nQualität + Laufzeit\nauf jedem Zielsystem',910,290,306,146);arrow(s,a,b);arrow(s,a,c);arrow(s,a,d);arrow(s,b,e);arrow(s,c,e);arrow(s,d,e);
 }
}
for(const [i,d] of slides.entries()){
 const s=base(d,i);
 if(d.type==='cover'){
  s.background.fill=C.dark;await img(s,d.image,790,0,490,720,'cover');tx(s,'KI für intelligente\nMobilität',64,150,715,185,62,C.white,true);tx(s,meta.subtitle,64,380,700,90,30,C.gold);tx(s,meta.author,64,515,715,60,28,C.white);tx(s,meta.date,64,626,650,42,22,'#CBDADB');
 }else if(d.type==='agenda'){
  d.items.forEach((t,j)=>{tx(s,String(j+1).padStart(2,'0'),64,182+j*83,90,48,31,C.accent,true);tx(s,t,184,182+j*83,1032,65,31);});
 }else if(d.type==='website'){
  await img(s,d.image,64,155,713,401);list(s,d.body,824,177,392,26,111);d.links.forEach(([label,url],j)=>link(s,label,url,64+j*540,600,528,23));
 }else if(d.type==='map'){
  await img(s,d.image,64,164,814,458);d.items.forEach((t,j)=>box(s,t,922,178+j*105,294,80,j===2,28));footer(s,d.caption,641);
 }else if(d.type==='tags'){
  tx(s,'Straßenklasse und Kartenstil',64,174,465,50,28,C.ink,true);
  for(const [j,k] of ['motorway','primary','residential'].entries()){await img(s,`latest/highway-${k}.png`,64,231+j*136,125,125);tx(s,`highway=${k}`,215,273+j*136,325,70,25);}
  tx(s,'Tempo 50: Schild und Straßenwirkung',564,174,652,58,27,C.ink,true);await img(s,'latest/osm-tempo50-node-way.png',564,235,652,337);
  link(s,'OSM Verkehrszeichen-Tool öffnen',d.links[0][1]+'?signs=DE:274-50',564,597,652,25);tx(s,'OSM-Carto-Beispiele · Tag-Empfehlungen vor dem Edit prüfen',564,646,652,40,18,C.muted);
 }else if(d.type==='diagram'){
  diagram(s,d.diagram);footer(s,d.bottom);
 }else if(d.type==='oracles'){
  d.rows.forEach(([n,t,b],j)=>{const y=170+j*112;tx(s,n,64,y,80,58,44,C.accent,true);tx(s,t,166,y,430,60,30,C.ink,true);tx(s,b,620,y,596,85,26,C.muted);});
  const old=box(s,'Kamera-Referenz\nim alten Ortskontext',64,532,333,86,false,24),change=box(s,'Bestätigter Wechsel\ninnerorts ↔ außerorts',461,532,349,86,true,24),reset=box(s,'Referenz ungültig\nKontext neu bestimmen',874,532,342,86,false,24);arrow(s,old,change);arrow(s,change,reset);footer(s,'Kurze unbekannte oder schwache Kontextzustände lösen diesen Wechsel nicht aus',636);
 }else if(d.type==='clients'){
  await img(s,d.images[0],64,161,400,443);await img(s,d.images[1],508,205,708,398);tx(s,d.captions[0],64,626,423,50,23,C.muted);tx(s,d.captions[1],508,626,708,50,23,C.muted);
 }else if(d.type==='columns'){
  for(const [j,v] of d.columns.entries()){const x=64+j*397;tx(s,v.title,x,176,350,52,31,C.ink,true);tx(s,v.body,x,242,350,126,25,C.muted);await img(s,v.image,x,391,350,247);}
 }else if(d.type==='table'){
  const vals=[d.headers,...d.rows],t=s.tables.add({rows:vals.length,columns:3,left:64,top:180,width:1152,height:460,columnWidths:[265,415,472],values:vals});for(let r=0;r<vals.length;r++){t.rows[r].height=r?82:50;for(let c=0;c<3;c++){const cell=t.getCell(r,c);cell.fill=r?C.bg:C.ink;cell.text.style={fontSize:r?23:25,typeface:FONT,color:r?C.ink:C.white,bold:!r,insets:8,verticalAlignment:'middle'};}}t.borders.assign({fill:C.line,width:1});
 }else if(d.type==='countryStats'){
  tx(s,'Stand '+d.snapshot,64,160,1152,40,23,C.muted);const vals=[d.headers,...d.rows],t=s.tables.add({rows:vals.length,columns:4,left:64,top:211,width:1152,height:384,columnWidths:[318,278,278,278],values:vals});for(let r=0;r<vals.length;r++){t.rows[r].height=48;for(let c=0;c<4;c++){const cell=t.getCell(r,c);cell.fill=r?C.bg:C.ink;cell.text.style={fontSize:25,typeface:FONT,color:r?C.ink:C.white,bold:!r||r===vals.length-1,insets:9,verticalAlignment:'middle',alignment:c?'right':'left'};}}t.borders.assign({fill:C.line,width:1});
  tx(s,'Panoramax: importierte fertige Schild-Crops. Crops / Sightings: Apps inkl. Replay und Altbestand.',64,614,1152,42,21,C.muted);tx(s,'* Zuordnungskonflikte bzw. unklar. Länder entsprechen der Modellzuordnung.',64,656,1090,32,20,C.muted);
 }else if(d.type==='deadlines'){
  const vals=[['Termin','Meilenstein'],...d.rows],t=s.tables.add({rows:vals.length,columns:2,left:64,top:186,width:1152,height:460,columnWidths:[430,722],values:vals});for(let r=0;r<vals.length;r++){t.rows[r].height=r?82:50;for(let c=0;c<2;c++){const cell=t.getCell(r,c);cell.fill=r?C.bg:C.ink;cell.text.style={fontSize:r?29:25,typeface:FONT,color:r?C.ink:C.white,bold:!r,insets:12,verticalAlignment:'middle'};}}t.borders.assign({fill:C.line,width:1});
 }else if(d.type==='wide'){
  await img(s,d.image,64,162,800,450);list(s,d.body,904,184,312,25,134);if(d.links){d.links.forEach(([label,url])=>link(s,label,url,64,622,800,24));tx(s,d.caption,64,664,1090,28,18,C.muted);}else footer(s,d.caption,637);
 }else if(d.type==='detection'){
  await img(s,d.images[0],64,160,800,385);await img(s,d.images[1],925,220,245,185);list(s,d.body,64,548,1152,24,44);
 }else if(d.type==='classification'){
  await img(s,d.images[0],96,172,240,180);await img(s,d.images[1],441,172,240,180);await img(s,d.images[2],860,164,230,204);tx(s,'DE:310 · Ortseingang',64,374,360,40,25);tx(s,'DE:311 · Ortsausgang',435,374,390,40,25);tx(s,'Realer Crop',891,374,300,40,25);list(s,d.body,64,444,1152,26,53);footer(s,d.bottom,635);
 }else if(d.type==='ocr'){
  for(let j=0;j<3;j++){const x=64+j*397;await img(s,d.images[j],x,160,350,235);tx(s,d.labels[j],x,420,350,45,30,C.ink,true,'center');}list(s,d.body,64,495,1152,26,54);
 }else if(d.type==='arithmetic'){
  tx(s,'Periodendauer T = 1 / f',64,167,1152,62,36,C.ink,true);const v=[['Frequenz','Zeitabstand / Budget je Bild','Zurückgelegter Weg'],...d.rows],t=s.tables.add({rows:4,columns:3,left:64,top:265,width:1152,height:265,columnWidths:[215,452,485],values:v});for(let r=0;r<4;r++){t.rows[r].height=r?72:50;for(let c=0;c<3;c++){const cell=t.getCell(r,c);cell.fill=r?C.bg:C.ink;cell.text.style={fontSize:r?29:25,typeface:FONT,color:r?C.ink:C.white,bold:!r,insets:10,verticalAlignment:'middle'};}}t.borders.assign({fill:C.line,width:1});footer(s,d.bottom,592);tx(s,'Frequenz ist nicht gleich Ende-zu-Ende-Latenz',64,644,1100,35,22,C.muted);
 }else if(d.type==='code'){
  tx(s,d.lead,64,165,1152,52,30,C.ink,true);tx(s,d.code,64,250,1152,220,23);list(s,d.body,64,520,1152,25,51);
 }else if(d.type==='steps'){
  d.rows.forEach(([n,t,b],j)=>{const y=178+j*103;tx(s,n,64,y,80,52,31,C.accent,true);tx(s,t,165,y,365,58,30,C.ink,true);tx(s,b,564,y,652,85,27,C.muted);});footer(s,d.bottom,628);
 }else if(d.type==='install'){
  await img(s,d.images[0],893,164,293,400);list(s,d.body,64,190,760,29,106);d.links.forEach(([label,url],j)=>link(s,label,url,64+j*365,580,340,26));
 }else if(d.type==='appUpload'){
  await img(s,d.captureImage,64,164,220,475);await img(s,d.images[0],372,164,210,456);await img(s,d.images[1],644,164,253,450);
  const captureLabel=tx(s,'Panoramax-Fotoaufnahme\nein-/ausschalten',64,646,304,62,23,C.ink,true);
  const captureTarget=s.shapes.add({geometry:'rect',name:'Panoramax-Kamerabutton-zweiter-von-links',position:{left:117,top:598,width:2,height:2},fill:'none',line:{fill:'none',width:0}});
  const captureArrow=s.shapes.connect(captureLabel,captureTarget,{kind:'straight',fromSide:'top',toSide:'bottom',line:{fill:C.accent,width:4},tail:{type:'triangle',width:'lg',length:'lg'}});captureArrow.bringToFront();
  tx(s,'iPhone: Upload-Pfeil',372,633,250,38,22,C.muted);tx(s,'Android: Hochladen',644,633,270,38,22,C.muted);list(s,d.body,946,181,270,25,142);tx(s,'Danach im Panoramax-Webviewer annotieren',946,614,270,66,23,C.muted);
 }else if(d.type==='setup'){
  await img(s,d.image,900,162,270,425);list(s,d.body,64,180,752,28,102);
 }else if(d.type==='metrics'){
  await img(s,d.image,64,163,745,419);list(s,d.body,854,186,362,25,135);footer(s,d.caption,627);
 }else if(d.type==='teams'){
  d.rows.forEach(([n,t,b],j)=>{const y=185+j*191;tx(s,n,64,y,260,68,44,C.accent,true);tx(s,t,374,y,842,64,34,C.ink,true);tx(s,b,374,y+78,842,82,28,C.muted);});footer(s,d.bottom,630);
 }else if(d.type==='signAssignment'){
  list(s,d.body,64,174,720,27,90);await img(s,d.image,910,161,270,432);await img(s,'../de-310.png',64,552,135,90);await img(s,'../de-311.png',244,552,135,90);tx(s,'DE:310         DE:311',64,653,400,28,21,C.muted);tx(s,'Bernbach · admin · CC BY-SA 4.0',853,625,364,50,17,C.muted);
 }else if(d.type==='assignment'){
  list(s,d.body,64,180,1152,30,98);footer(s,d.bottom,632);
 }else if(d.type==='questions'){
  s.background.fill=C.dark;tx(s,'Nur Fragen?',64,292,1152,116,76,C.white,true,'center');
 }else throw Error(d.type);
}
if(slides.length!==42||elapsed!==90)throw Error(`Folien / Minuten: ${slides.length} / ${elapsed}`);
let notes=`# ${meta.title}\n\n${meta.subtitle}  \n${meta.author}  \n${meta.date} · 90 Minuten · ${slides.length} Folien\n\n`;let time=0;
for(const [i,d] of slides.entries()){notes+=`## ${i+1}. ${d.title} (${time}–${time+d.minutes} Min.)\n\n${d.notes}\n\nQuellen:\n\n${d.sources.map(a=>'- '+a).join('\n')}\n\n`;time+=d.minutes;}
await fs.writeFile(path.join(root,'SPEAKER_NOTES_DE.md'),notes);
const candidate=path.join(work,'candidate-v6.pptx');console.log('Export',slides.length,'Folien');await(await PresentationFile.exportPptx(p)).save(candidate);
for(const [i,s] of p.slides.items.entries()){const b=await p.export({slide:s,format:'png',scale:1});await fs.writeFile(path.join(work,'renders',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await b.arrayBuffer()));if((i+1)%10===0)console.log('Gerendert',i+1);}
const {finalizePresentation}=await import(pathToFileURL(path.join(SK,'container_tools/artifact_tool_utils.mjs')).href);
const finalPath=path.join(work,'validated',stem+'.pptx');const owners=[14,19,22,24];
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath,pythonExecutable:PY,integrityValidatorPath:path.join(SK,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(SK,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...owners.flatMap(a=>['--require-native-table-slide',String(a)])],explicitTotalSlideCount:42,requiredNativeTableOwnerSlides:owners,requiredNativeChartOwnerSlides:[],fontPolicy:{basis:'design',families:[FONT]},verifyArtifactToolImport:true,receiptPath:path.join(work,'validation-v6.json')});console.log('Fertig',result.finalSha256);
