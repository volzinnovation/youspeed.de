const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const reference=require('../shared/traffic-sign-documentation/renderer.js');
assert.deepEqual(reference.languages,['en','fr','de','nl']);
let total=0,spoken=0;
for(const country of ['de','fr','nl','be','ch']){
  const catalog=JSON.parse(fs.readFileSync(`shared/tsr/prolix-${country}-class-catalog-v1.json`));
  const signs=reference.signs(catalog);assert(signs.length>0);total+=signs.length;
  for(const sign of signs){
    assert.equal(sign.display_eligible,true);assert(sign.sign_code);assert(sign.image_path.startsWith('tsr/sign-pictograms/'));
    const bytes=fs.readFileSync('shared/'+sign.image_path);
    if(sign.source_provenance?.png_sha256)assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),sign.source_provenance.png_sha256);
    for(const language of reference.languages)assert.equal(reference.spoken(sign,language),sign.speech?.[language]?.trim()||null);
    if(sign.speech)spoken++;
  }
  const changed=structuredClone(catalog);changed.signs[0].display_eligible=false;assert(!reference.signs(changed).some(s=>s.class_id===changed.signs[0].class_id));
  const reversed=structuredClone(catalog);reversed.signs.reverse();assert.deepEqual(reference.signs(reversed),signs);
  const example=signs.find(s=>s.speech?.en);assert(reference.signs(catalog,example.speech.en).some(s=>s.class_id===example.class_id));
  assert(reference.signs(catalog,example.sign_code).some(s=>s.class_id===example.class_id));
}
assert.equal(reference.spoken({label:{en:'Display name only'}},'en'),null);
const translated=JSON.parse(fs.readFileSync('shared/traffic-sign-documentation/translations.json'));
assert.equal(Object.keys(translated).length,9);for(const value of Object.values(translated))assert.deepEqual(Object.keys(value),Object.keys(translated.en));
console.log(`PASS: ${total} catalogue entries, ${spoken} spoken entries, original PNG hashes, exact speech, silent signs, country search and English/French/German/Dutch order.`);
