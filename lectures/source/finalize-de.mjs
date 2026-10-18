// Reimport the validated German file, render the delivered bytes, update aliases.
import fs from 'node:fs/promises';
import path from 'node:path';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const root=path.resolve(import.meta.dirname,'..');
const source=path.join(root,'.build/de/validated/ki-intelligente-mobilitaet-2026-10-19-de-v6.pptx');
const p=await PresentationFile.importPptx(await FileBlob.load(source));
if(p.slides.items.length!==42)throw Error('Falsche Folienzahl');
const dir=path.join(root,'.build/de/final-renders');await fs.mkdir(dir,{recursive:true});
for(const [i,s] of p.slides.items.entries()){const b=await p.export({slide:s,format:'png',scale:1});await fs.writeFile(path.join(dir,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await b.arrayBuffer()));}
for(const filename of ['ki-intelligente-mobilitaet-2026-10-19-de.pptx','youspeed-lecture-2026-10-19.pptx'])await fs.copyFile(source,path.join(root,'output',filename));
await fs.copyFile(path.join(root,'SPEAKER_NOTES_DE.md'),path.join(root,'SPEAKER_NOTES.md'));
console.log('42 finale Folien erneut importiert und gerendert; kanonische Dateien aktualisiert');
