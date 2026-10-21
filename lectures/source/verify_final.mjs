import fs from 'node:fs/promises';
import path from 'node:path';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const root=path.resolve(import.meta.dirname,'..');
const p=await PresentationFile.importPptx(await FileBlob.load(path.join(root,'output/youspeed-lecture-2026-10-19.pptx')));
if(p.slides.items.length!==36)throw Error('Slide count');
const dir=path.join(root,'.build/final-renders');await fs.mkdir(dir,{recursive:true});
for(const [i,s] of p.slides.items.entries()){
 const b=await p.export({slide:s,format:'png',scale:1});
 await fs.writeFile(path.join(dir,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await b.arrayBuffer()));
}
console.log('Reimported and rendered all 36 final PPTX slides');
