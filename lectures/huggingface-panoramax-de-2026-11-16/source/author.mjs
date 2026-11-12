// Layout primitives reused from the existing October lecture author.mjs.
// The connected presentation is always mutated inside an Artifact Session callback.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {meta,slides} from './slides.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const C={bg:'#F4F2EB',ink:'#0B2F38',muted:'#50646A',gold:'#F5D34C',accent:'#A9720A',white:'#FFFFFF'};
function text(s,t,x,y,w,h,size=28,color=C.ink,bold=false,font='Arial'){
 const a=s.shapes.add({geometry:'textbox',name:t.slice(0,60),position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 a.text=t;a.text.style={fontSize:size,typeface:font,color,bold,alignment:'left',verticalAlignment:'top',autoFit:'none',wrap:'square',insets:0};return a;
}
function link(s,label,url,x=64,y=596,w=1152,size=21){const a=text(s,label,x,y,w,35,size,'#12647B');a.text.get(label).link={uri:url,isExternal:true};a.text.get(label).underline='sng';return a;}
function image(s,name,x,y,w,h,crop){const a=s.images.add({blob:new Uint8Array(fs.readFileSync(path.join(root,'assets',name))),contentType:'image/png',alt:name,position:{left:x,top:y,width:w,height:h},fit:'contain'});if(crop){const [cx,cy,cw,ch]=crop;a.crop={left:cx/2758,top:cy/2168,right:1-(cx+cw)/2758,bottom:1-(cy+ch)/2168};}return a;}
function takeaway(s,t){text(s,t,64,638,1152,57,22,C.muted);}
function base(p,d,i){const s=p.slides.add({width:1280,height:720});s.background.fill=C.bg;if(d.type!=='cover'){text(s,d.title,64,43,1152,115,d.title.length>53?39:43,C.ink,true);text(s,String(i+1).padStart(2,'0'),1170,684,45,22,15,C.muted);}s.speakerNotes.text=d.notes+'\n\nQuellenstand: '+meta.evidenceDate+'\n'+d.sources.join('\n');return s;}
function draw(p,d,i){const s=base(p,d,i);
 if(d.type==='cover'){s.background.fill=C.ink;text(s,meta.title,64,85,1120,170,62,C.white,true);text(s,'Modelle und Datensätze\nam Beispiel Panoramax',64,275,1152,110,39,C.gold);text(s,'KI für intelligente Mobilität\nKurzvorlesung mit Browserübung',64,428,940,100,29,C.white);text(s,meta.author,64,596,1152,36,24,C.white);text(s,meta.date+' · ca. 20 Minuten',64,649,1152,35,23,'#CBDADB');}
 else if(d.type==='steps'){d.items.forEach(([a,b],j)=>{text(s,String(j+1).padStart(2,'0'),64,184+j*106,74,55,35,C.accent,true);text(s,a,164,184+j*106,350,60,29,C.ink,true);text(s,b,530,184+j*106,686,83,26,C.muted);});}
 else if(d.type==='hub'){text(s,d.intro,64,164,1152,55,28,C.accent,true);d.items.forEach(([a,b,c],j)=>{text(s,a,64,255+j*115,270,55,32,C.ink,true);text(s,b,360,252+j*115,856,50,29);text(s,c,360,295+j*115,856,43,24,C.muted);});takeaway(s,d.takeaway);}
 else if(d.type==='screenshot'){image(s,d.image,64,168,760,410,d.crop);d.body.forEach(([a,b],j)=>{text(s,a,872,173+j*135,344,37,26,C.ink,true);text(s,b,872,216+j*135,344,91,25);});link(s,d.link[0],d.link[1]);takeaway(s,d.takeaway);}
 else if(d.type==='download'){link(s,d.link[0],d.link[1],64,176,1152,25);text(s,d.intro,64,239,1152,48,28,C.ink,true);text(s,d.code,64,303,1152,185,24,C.ink,false,'Courier New');d.body.forEach((t,j)=>text(s,t,64,512+j*55,1152,47,27));takeaway(s,d.takeaway);}
 else if(d.type==='compare'){text(s,d.leftTitle,64,185,550,70,31,C.ink,true);text(s,d.rightTitle,666,185,550,70,31,C.ink,true);d.left.forEach((v,j)=>text(s,v,64,290+j*100,550,80,28));d.right.forEach((v,j)=>text(s,v,666,290+j*100,550,80,28));takeaway(s,d.takeaway);}
 else if(d.type==='exercise'){d.items.forEach(([a,b],j)=>{text(s,a,64,186+j*125,75,60,40,C.accent,true);text(s,b,170,186+j*125,1046,100,30);});text(s,d.takeaway,64,604,1152,65,28,C.ink,true);}
 return s;
}
export async function authorBatch({presentation,input}){for(let i=input.start;i<input.end;i++)draw(presentation,slides[i],i);return {count:presentation.slides.items.length,range:[input.start+1,input.end],talkDate:meta.date};}
