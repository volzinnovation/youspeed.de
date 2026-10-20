// Update the bound cloud deck using the same editable objects as the portable deck.
import {drawSlide} from './author.mjs';
import {slides,meta} from './slides.mjs';
export async function syncBatch({presentation,input}) {
 if(input.reorder){
  const old=[...presentation.slides.items];
  if(old.length!==25)throw Error('Unexpected deck size');
  const order=[0,1,2,3,4,5,7,6,9,8,...Array.from({length:15},(_,i)=>i+10)];
  await presentation.slides.reorder(order.map(i=>'sl/'+old[i].id));
 }
 const done=[];
 for(const i of input.indices??[]){
  const target=presentation.slides.items[i];
  const owned=[...target.shapes.items,...target.images.items,...target.tables.items].map(x=>x.toSnapshot().aid);
  if(owned.length)await presentation.delete(owned);
  drawSlide(presentation,slides[i],i,target);
  done.push({index:i+1,id:target.id,title:slides[i].title});
 }
 if(input.notes){
  let elapsed=0;
  presentation.slides.items.forEach((s,i)=>{
   const d=slides[i];
   s.speakerNotes.text=`${elapsed.toLocaleString('de-DE')}–${(elapsed+d.minutes).toLocaleString('de-DE')} Minuten (${d.minutes.toLocaleString('de-DE')} Min.)\n\n${d.notes}\n\nQuellen (geprüft ${meta.evidenceDate}):\n${d.sources.join('\n')}`;
   elapsed+=d.minutes;
   for(const sh of s.shapes.items){
    const f=sh.toSnapshot().frame;
    if(Math.abs(f.left-1170)<1&&Math.abs(f.top-684)<1)sh.text.set(String(i+1).padStart(2,'0'));
   }
  });
  if(elapsed!==45)throw Error('Timing');
 }
 return {updated:done,slideCount:presentation.slides.items.length};
}
