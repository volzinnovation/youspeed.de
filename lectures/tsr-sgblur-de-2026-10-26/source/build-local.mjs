// Portable file deliverables for the same content authored in the live deck.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {Presentation,PresentationFile,FileBlob} from '@oai/artifact-tool';
import {drawSlide,addSourceLink} from './author.mjs';
import {meta,slides} from './slides.mjs';
import {studentText} from './student-wording.mjs';
const root=path.resolve(import.meta.dirname,'..');
const revision=process.env.LECTURE_REVISION ?? 'v9.1';
const work=path.join(root,'.build',revision);
const out=path.join(root,'output');
const skill='/Users/raphaelvolz/.codex/plugins/cache/openai-primary-runtime/presentations/26.1017.22136/skills/presentations';
const python='/Users/raphaelvolz/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3';
process.env.RUNTIME_NODE_MODULES ??= '/Users/raphaelvolz/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
await fs.mkdir(work,{recursive:true});await fs.mkdir(out,{recursive:true});
// Preserve the existing deck, its master, native tables, pictures and all
// unchanged slide objects. Add the data-source and metrics explanations and
// update human-facing terminology. Resolve original slides by their anchor IDs.
const sourcePath=path.join(out,'tsr-sgblur-de-2026-10-26-v8.pptx');
const sourceSha256=createHash('sha256').update(await fs.readFile(sourcePath)).digest('hex');
const presentation=await PresentationFile.importPptx(await FileBlob.load(sourcePath));
if(presentation.slides.items.length!==25||slides.length!==27)throw Error('Unexpected source/output slide count');
const before=await presentation.inspect({select:'$.slides[*]',include:['id','layout','elements.id','elements.kind','elements.text','elements.position']});
await fs.writeFile(path.join(work,'source-inspection.ndjson'),before.ndjson+'\n');
for(const [i,d] of slides.entries()){
 let target;
 if(d.sourceSlide){
  const record=before.records[d.sourceSlide-1];
  target=presentation.resolve(record.id);
  for(const element of record.elements){
   if(element.kind!=='textbox'||typeof element.text!=='string')continue;
   let replacement=studentText(element.text);
   if(d.sourceSlide===2&&element.text.startsWith('Geprüfte Crops'))replacement=d.items[1][1];
   if(element.position?.top===684&&element.position?.left===1170)replacement=String(i+1).padStart(2,'0');
   if(replacement!==element.text)presentation.resolve(element.id).text=replacement;
  }
  if(['yolo','modelTable','gpuTable','beginnerEvaluation'].includes(d.type)){
   const anchor=record.elements.find(e=>e.kind==='table');
   if(!anchor)throw Error('Missing native table on source slide '+d.sourceSlide);
   const table=presentation.resolve(anchor.id),values=[d.headers,...d.rows];
   for(let r=0;r<values.length;r++)for(let c=0;c<values[r].length;c++)table.getCell(r,c).value=values[r][c];
  }
  if(d.sourceSlide===4)d.links.forEach(([label,url],j)=>addSourceLink(target,label,url,584,548+j*42,632,20));
 }else target=drawSlide(presentation,d,i);
 target.moveTo(i);
 const elapsed=slides.slice(0,i).reduce((a,b)=>a+b.minutes,0);
 target.speakerNotes.text=`${elapsed.toLocaleString('de-DE')}–${(elapsed+d.minutes).toLocaleString('de-DE')} Minuten (${d.minutes.toLocaleString('de-DE')} Min.)\n\n${d.notes}\n\nQuellenstand: ${d.evidenceDate??meta.evidenceDate}\n${d.sources.join('\n')}`;
}
const candidatePath=path.join(work,'candidate.pptx');
await(await PresentationFile.exportPptx(presentation)).save(candidatePath);
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const finalPath=path.join(out,`tsr-sgblur-de-2026-10-26-${revision}.pptx`);
const tableOwners=slides.flatMap((d,i)=>['yolo','modelTable','gpuTable','evaluation','beginnerEvaluation','classificationMetrics'].includes(d.type)?[i+1]:[]);
const result=await finalizePresentation({workspaceDir:root,candidatePath,finalPath,pythonExecutable:python,integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...tableOwners.flatMap(n=>['--require-native-table-slide',String(n)])],explicitTotalSlideCount:slides.length,requiredNativeTableOwnerSlides:tableOwners,requiredNativeChartOwnerSlides:[],fontPolicy:{basis:'reference',families:['Arial','Courier New'],referencePath:sourcePath,referenceSha256:sourceSha256},verifyArtifactToolImport:true,receiptPath:path.join(work,'validation.json')});
console.log('Final PPTX:',result.finalSha256);
const final=await PresentationFile.importPptx(await FileBlob.load(finalPath));
if(final.slides.items.length!==slides.length)throw Error('Unexpected slide count');
const renders=path.join(work,'final-renders');await fs.mkdir(renders,{recursive:true});
for(const [i,s] of final.slides.items.entries()){
 for(const format of ['png','layout']){
  const b=await final.export({slide:s,format,scale:1});
  await fs.writeFile(path.join(renders,`slide-${String(i+1).padStart(2,'0')}.${format==='layout'?'layout.json':format}`),new Uint8Array(await b.arrayBuffer()));
 }
 if((i+1)%6===0)console.log('Rendered final file:',i+1);
}
let elapsed=0;
let notes=`# ${meta.title}\n\n## ${meta.subtitle}\n\n${meta.date} · ${slides.length} Folien · ${meta.minutes} Minuten\n\nTechnischer Quellenstand: ${meta.evidenceDate}. Hugging-Face-Modellkarte und Trainingsversuch: 20. Oktober 2026. Datenpakete: 20. Oktober 2026, Hugging-Face-Commit 6837ae4fae0d1d216612afa739c9dfefd6b277ab. Repository-Links sind auf die dokumentierten HEAD-Revisionen gepinnt; tatsächlich gelesene Arbeitsdateien sind zusätzlich im Modellinventar gehasht.\n\n`;
const timing=[];
for(const [i,d] of slides.entries()){
 const a=elapsed;elapsed+=d.minutes;
 const interval=`${a.toLocaleString('de-DE')}–${elapsed.toLocaleString('de-DE')}`;
 timing.push(`| ${String(i+1).padStart(2,'0')} | ${interval} | ${d.title} |`);
 notes+=`## ${i+1}. ${d.title}\n\n**${interval} Minuten · ${d.minutes.toLocaleString('de-DE')} Min.**\n\n${d.notes}\n\nQuellen:\n\n${d.sources.map(u=>`- [${u.split('/').pop()}](${u})`).join('\n')}\n\n`;
}
if(elapsed!==45)throw Error('Timing changed');
await fs.writeFile(path.join(root,'SPRECHERNOTIZEN.md'),notes.trimEnd()+'\n');
await fs.writeFile(path.join(work,'timings.md'),timing.join('\n')+'\n');
await fs.writeFile(path.join(work,'slides.json'),JSON.stringify({meta,slides},null,2)+'\n');
console.log(slides.length+' slides /45 minutes; notes and final-file previews ready.');
