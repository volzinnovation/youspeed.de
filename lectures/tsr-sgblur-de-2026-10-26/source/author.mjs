import path from 'node:path';
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';
import {meta,slides} from './slides.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const C={bg:'#F4F2EB',ink:'#0B2F38',muted:'#50646A',gold:'#F5D34C',accent:'#A9720A',line:'#C9D3D2',white:'#FFFFFF'};
const FONT='Arial';
function text(s,t,x,y,w,h,size=28,color=C.ink,bold=false,align='left',font=FONT){
 const a=s.shapes.add({geometry:'textbox',name:t.slice(0,60),position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 a.text=t;a.text.style={fontSize:size,typeface:font,color,bold,alignment:align,verticalAlignment:'top',autoFit:'none',wrap:'square',insets:0};return a;
}
function block(s,t,x,y,w,h,dark=false,size=26){const a=s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:dark?C.ink:C.white,line:{fill:dark?C.ink:C.line,width:1.3}});a.text=t;a.text.style={fontSize:size,typeface:FONT,color:dark?C.white:C.ink,alignment:'center',verticalAlignment:'middle',insets:12,autoFit:'none'};return a;}
function arrow(s,a,b,from='right',to='left',color=C.muted,width=2){return s.shapes.connect(a,b,{kind:'straight',fromSide:from,toSide:to,line:{fill:color,width},tail:{type:'triangle',width:'sm',length:'sm'}});}
function image(s,rel,x,y,w,h,fit='contain'){const bytes=fs.readFileSync(path.resolve(root,rel));return s.images.add({blob:new Uint8Array(bytes),contentType:/\.jpe?g$/i.test(rel)?'image/jpeg':'image/png',alt:path.basename(rel),position:{left:x,top:y,width:w,height:h},fit});}
function lines(s,items,x=64,y=194,w=1152,size=29,gap=88){items.forEach((t,i)=>text(s,t,x,y+i*gap,w,gap-10,size));}
function link(s,label,url,x,y,w,size=21){const a=text(s,label,x,y,w,40,size,'#12647B');a.text.get(label).link={uri:url,isExternal:true};a.text.get(label).underline='sng';return a;}
export function addDetectorBaselineLink(s,d){
 if(!d.baselineLink)return;
 const [label,url]=d.baselineLink;
 const a=text(s,label,64,650,1152,30,20,'#12647B');
 a.text.get(label).link={uri:url,isExternal:true};a.text.get(label).underline='sng';
}
function takeaway(s,t){if(t)text(s,t,64,638,1152,57,22,C.muted);}
function chain(s,labels,y=205,h=125){const gap=32,w=(1152-gap*(labels.length-1))/labels.length;const ns=labels.map((v,i)=>block(s,v,64+i*(w+gap),y,w,h,i===labels.length-1,labels.length>3?24:25));for(let i=1;i<ns.length;i++)arrow(s,ns[i-1],ns[i]);return ns;}
function nativeTable(s,headers,rows,x,y,width,colWidths,rowH=86,fontSize=25,headerH=54){
 const v=[headers,...rows];const h=headerH+rowH*rows.length;
 const t=s.tables.add({rows:v.length,columns:headers.length,left:x,top:y,width,height:h,columnWidths:colWidths,values:v});
 for(let r=0;r<v.length;r++){t.rows[r].height=r?rowH:headerH;for(let c=0;c<headers.length;c++){const cell=t.getCell(r,c);cell.fill=r?C.bg:C.ink;cell.text.style={fontSize:r?fontSize:23,typeface:FONT,color:r?C.ink:C.white,bold:r===0,insets:12,verticalAlignment:'middle'};}}
 t.borders.assign({fill:C.line,width:1});return t;
}
function steps(s,items,y=184,gap=106){items.forEach(([a,b],i)=>{text(s,String(i+1).padStart(2,'0'),64,y+i*gap,74,55,35,C.accent,true);text(s,a,164,y+i*gap,350,60,29,C.ink,true);text(s,b,530,y+i*gap,686,83,26,C.muted);});}
function circle(s,x,y,d=36,color=C.gold){return s.shapes.add({geometry:'ellipse',position:{left:x,top:y,width:d,height:d},fill:color,line:{fill:C.ink,width:1.5}});}
function base(p,d,i,target){const s=target ?? p.slides.add({width:1280,height:720});s.background.fill=C.bg;if(d.type!=='cover'&&d.type!=='questions'){text(s,d.title,64,43,1152,115,d.title.length>53?39:43,C.ink,true);text(s,String(i+1).padStart(2,'0'),1170,684,45,22,15,C.muted,false,'right');}const elapsed=slides.slice(0,i).reduce((a,b)=>a+b.minutes,0);if(d.subtitle)text(s,d.subtitle,64,128,1152,44,27,C.accent,true);s.speakerNotes.text=`${elapsed.toLocaleString('de-DE')}–${(elapsed+d.minutes).toLocaleString('de-DE')} Minuten (${d.minutes.toLocaleString('de-DE')} Min.)\n\n${d.notes}\n\nQuellen (geprüft ${meta.evidenceDate}):\n${d.sources.join('\n')}`;return s;}
function draw(p,d,i,target){const s=base(p,d,i,target);
 if(d.type==='cover'){
  s.background.fill=C.ink;text(s,meta.title,64,85,1120,170,62,C.white,true);text(s,meta.subtitle,64,305,1152,80,39,C.gold);text(s,'TSR · SGBlur · Panoramax\nDE:310 und DE:311 mit Bildbeispielen',64,428,750,100,29,C.white);image(s,'../assets/de-310.png',860,410,145,110);image(s,'../assets/de-311.png',1040,410,145,110);text(s,meta.author,64,596,1152,36,24,C.white);text(s,meta.date+' · 45 Minuten',64,649,1152,35,23,'#CBDADB');
 }else if(d.type==='steps'){steps(s,d.items);}
 else if(d.type==='failure'){
  const im=image(s,d.image,64,219,460,323);im.crop={left:1827/2376,top:2244/4224,right:1-2039/2376,bottom:1-2392/4224};text(s,'Realer Bildausschnitt · 212 × 148 Pixel',64,567,500,30,22,C.muted);lines(s,d.body,584,203,632,31,116);if(d.links)d.links.forEach(([label,url],j)=>link(s,label,url,584,548+j*42,632,20));takeaway(s,d.takeaway);text(s,'admin / Panoramax · CC BY-SA 4.0',64,611,500,25,17,C.muted);
 }else if(d.type==='failureComparison'){
  text(s,d.leftTitle,64,174,550,65,30,C.ink,true);text(s,d.rightTitle,666,174,550,65,30,C.ink,true);
  const left=image(s,d.leftImage,64,250,550,275);left.crop={left:0.36,top:0.24,right:0.19,bottom:0.36};
  const right=image(s,d.rightImage,744,250,394,275);right.crop={left:1827/2376,top:2244/4224,right:1-2039/2376,bottom:1-2392/4224};
  text(s,d.leftBody,64,547,550,82,24);text(s,d.rightBody,666,547,550,82,24);takeaway(s,d.takeaway);
 }else if(d.type==='network'){
  const a=[0,1,2].map(n=>circle(s,105,236+n*81));const b=[0,1,2,3].map(n=>circle(s,345,195+n*78));const c=[0,1,2].map(n=>circle(s,610,236+n*81));for(const x of a)for(const y of b)arrow(s,x,y,'right','left',C.line,1);for(const x of b)for(const y of c)arrow(s,x,y,'right','left',C.line,1);
  text(s,'Pixelwerte',64,548,160,50,25,C.ink,true);text(s,'Gelernte Merkmale',258,548,270,50,25,C.ink,true);text(s,'Klassenscores',554,548,220,50,25,C.ink,true);lines(s,d.body,810,192,406,25,102);text(s,'z = Σ wᵢxᵢ + b → Aktivierung',64,463,700,54,27,C.muted);takeaway(s,d.takeaway);
 }else if(d.type==='cnn'){
  const a=block(s,'Backbone\nFaltungen + Merkmalsblöcke',64,181,660,100,false,27),b=block(s,'C2PSA\nMerkmale gewichten (Attention)',64,326,660,100,false,27),c=block(s,'Classification Head\n1×1-Conv → Pooling → Linear (134)',64,471,660,100,true,26);arrow(s,a,b,'bottom','top');arrow(s,b,c,'bottom','top');lines(s,d.body,810,181,406,25,108);if(d.links)link(s,d.links[0][0],d.links[0][1],64,592,1152,19);takeaway(s,d.takeaway);
 }else if(d.type==='yolo'){
  text(s,d.body[0],64,171,1152,56,31,C.accent,true);nativeTable(s,d.headers,d.rows,64,235,1152,[322,360,470],80,26);text(s,'Detektor',64,456,1152,28,21,C.muted);chain(s,d.stages,491,114);text(s,d.body[2],64,620,1152,38,25,C.ink,true);if(d.links)link(s,d.links[0][0],d.links[0][1],64,662,1120,18);
 }else if(d.type==='pipeline'){
  chain(s,d.stages,205,153);lines(s,d.body,64,437,1152,29,89);
 }else if(d.type==='sgblur'){
  chain(s,d.stages,177,125);d.origins.forEach((o,j)=>{const x=64+j*602;text(s,o.name,x,337,550,44,30,C.ink,true);text(s,o.meaning,x,391,550,80,25);text(s,o.credit,x,478,550,42,20,C.muted);link(s,o.label,o.url,x,531,550,21);});text(s,d.body[2],64,611,1152,65,23,C.muted);
 }else if(d.type==='dataAndModel'){
  d.columns.forEach((col,j)=>{const x=64+j*602;text(s,col.title,x,185,550,55,31,C.ink,true);link(s,col.label,col.url,x,250,550,23);lines(s,col.body,x,325,550,27,82);});
  text(s,d.body,64,584,1152,42,26,C.ink,true);takeaway(s,d.takeaway);
 }else if(d.type==='classificationMetrics'){
  text(s,d.intro,64,166,1152,43,28,C.accent,true);
  nativeTable(s,d.matrixHeaders,d.matrixRows,64,229,520,[230,145,145],72,24,70);
  text(s,d.counts,64,457,520,57,22,C.muted);
  text(s,'Precision (P)',640,218,576,35,27,C.ink,true);
  text(s,'Wie viele Vorhersagen stimmen?\nrichtig / Vorhersagen dieser Klasse',640,256,576,58,23);
  text(s,'Recall (R)',640,320,576,35,27,C.ink,true);
  text(s,'Wie viele echte Beispiele finden wir?\nrichtig / tatsächliche Beispiele dieser Klasse',640,358,576,58,23);
  text(s,'F1: gemeinsamer Wert',640,422,576,35,27,C.ink,true);
  text(s,'2 × P × R / (P + R)',640,460,576,35,25);
  text(s,'Nur hoch, wenn beide Werte hoch sind.',640,496,576,28,21,C.muted);
  nativeTable(s,d.headers,d.rows,64,536,1152,[330,274,274,274],46,24,44);
 }else if(d.type==='detectorCandidate'){
  text(s,d.intro,64,170,1152,48,27,C.accent,true);
  nativeTable(s,d.headers,d.rows,64,245,1152,[350,300,250,252],84,25,60);
  text(s,d.body[0],64,505,1152,43,22,C.muted);
  text(s,d.body[1],64,551,1152,43,22,C.muted);
  link(s,d.link[0],d.link[1],64,602,1152,21);
  text(s,d.takeaway,64,650,1152,39,21,C.muted);
 }else if(d.type==='modelTable'){
  nativeTable(s,d.headers,d.rows,64,182,1152,[350,192,300,310],105,24,74);d.links.forEach(([label,url],j)=>link(s,label,url,64+j*602,486,550,23));text(s,d.memoryNotes[0],64,543,1152,44,20,C.muted);text(s,d.memoryNotes[1],64,585,1152,44,20,C.muted);text(s,d.takeaway,64,642,1152,42,19,C.muted);
 }else if(d.type==='platforms'){
  const a=block(s,d.stages[0],64,287,430,146,true,28);for(let n=0;n<3;n++){const b=block(s,d.stages[n+1],696,174+n*143,520,105,false,29);arrow(s,a,b);}takeaway(s,d.takeaway);
 }else if(d.type==='gpuTable'){
  nativeTable(s,d.headers,d.rows,64,180,1152,[235,310,607],117,24);takeaway(s,d.takeaway);
 }else if(d.type==='annotation'){
  image(s,d.image,64,168,760,436);lines(s,d.body,872,181,344,25,143);takeaway(s,d.takeaway);
 }else if(d.type==='datasets'){
  for(let j=0;j<2;j++){const x=64+j*592;text(s,d.headers[j],x,181,550,66,32,C.ink,true);lines(s,d.columns[j],x,280,550,26,78);}takeaway(s,d.takeaway);
 }else if(d.type==='split'){
  ['Training','Entwicklungsvalidierung','Test / Holdout'].forEach((v,j)=>block(s,v,64+j*395,184,362,84,j===2,24));text(s,'Disjunkte Gruppen · Kalibrationsdaten zusätzlich getrennt halten',64,282,1152,30,21,C.muted);lines(s,d.body,64,324,1152,28,71);takeaway(s,d.takeaway);
 }else if(d.type==='datasetPlan'){
  text(s,d.tree,64,189,580,290,27,C.ink,false,'left','Courier New');d.roles.forEach(([title,body],j)=>{text(s,title,720,185+j*121,496,45,29,C.ink,true);text(s,body,720,233+j*121,496,67,25,C.muted);});text(s,d.command,64,558,1152,60,30,C.ink,true,'left','Courier New');takeaway(s,d.takeaway);
 }else if(d.type==='prolix'){
  text(s,d.code,64,172,1152,298,22,C.ink,false,'left','Courier New');lines(s,d.body,64,504,1152,27,62);takeaway(s,d.takeaway);
 }else if(d.type==='serverDownload'){
  link(s,d.datasetLabel,d.datasetUrl,64,176,1152,25);
  text(s,d.intro,64,239,1152,48,28,C.ink,true);
  text(s,d.code,64,303,1152,185,24,C.ink,false,'left','Courier New');
  lines(s,d.body,64,512,1152,27,55);takeaway(s,d.takeaway);
 }else if(d.type==='serverSetup'||d.type==='parity'){
  d.steps.forEach(([n,t,b],j)=>{text(s,n,64,179+j*108,66,62,39,C.accent,true);text(s,t,164,179+j*108,310,70,29,C.ink,true);text(s,b,505,179+j*108,711,82,26,C.muted);});takeaway(s,d.takeaway);
 }else if(d.type==='fineTuning'){
  text(s,d.definition,64,172,1152,86,29);
  link(s,d.modelLabel,d.modelUrl,64,274,1152,27);
  text(s,d.modelSpec,64,322,1152,40,24,C.muted);
  lines(s,d.body,64,387,1152,26,58);
  text(s,d.code,64,574,1152,44,28,C.ink,false,'left','Courier New');
  takeaway(s,d.takeaway);
 }else if(d.type==='training'){
  text(s,d.code,64,179,1152,235,26,C.ink,false,'left','Courier New');lines(s,d.body,64,452,1152,27,62);takeaway(s,d.takeaway);
 }else if(d.type==='detector'){
  lines(s,d.body,64,184,1152,29,88);text(s,d.code,64,532,1152,114,22,C.muted,false,'left','Courier New');addDetectorBaselineLink(s,d);
 }else if(d.type==='evaluation'){
  nativeTable(s,d.headers,d.rows,64,174,1152,[244,462,446],103,24);
 }else if(d.type==='beginnerEvaluation'){
  text(s,d.command,64,171,1152,98,26,C.ink,false,'left','Courier New');nativeTable(s,d.headers,d.rows,64,308,1152,[340,812],85,26);takeaway(s,d.takeaway);
 }else if(d.type==='exercise'){
  d.items.forEach(([a,b],j)=>{text(s,a,64,186+j*125,75,60,40,C.accent,true);text(s,b,170,186+j*125,1046,100,30);});text(s,d.question,64,604,1152,65,28,C.ink,true);
 }else if(d.type==='questions'){
  s.background.fill=C.ink;text(s,'Fragen?',64,180,1152,150,100,C.white,true);text(s,d.body[0],64,418,1090,150,37,C.gold);text(s,'DE:310 · DE:311',64,639,1152,42,25,'#CBDADB');
 }else throw new Error('Unknown layout '+d.type);
 return s;
}
export async function authorBatch({presentation,input}){
 if(input.start===0)presentation.slides.keep([]);
 for(let i=input.start;i<input.end;i++)draw(presentation,slides[i],i);
 return {count:presentation.slides.items.length,minutes:slides.reduce((a,d)=>a+d.minutes,0),range:[input.start+1,input.end]};
}

export {draw as drawSlide,link as addSourceLink};
