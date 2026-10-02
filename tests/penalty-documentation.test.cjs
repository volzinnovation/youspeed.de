const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const doc=require('../shared/penalty-documentation/renderer.js');
const rules=Object.fromEntries(fs.readdirSync('shared/Rules').filter(name=>name.endsWith('-rules.json')).map(name=>[name.slice(0,3),JSON.parse(fs.readFileSync(path.join('shared/Rules',name)))]));
assert.equal(Object.keys(rules).length,12);
for(const rule of Object.values(rules)){assert(doc.categories(rule).length);for(const context of doc.categories(rule)){const rows=doc.rows(rule,context);assert(rows.length);assert(rows.every(row=>Number.isInteger(row.min)));}}
// Foundation and JSONObject serialize keys differently; UI defaults must agree.
function reverseKeys(value){if(Array.isArray(value))return value.map(reverseKeys);if(value && typeof value==='object')return Object.fromEntries(Object.entries(value).reverse().map(([key,item])=>[key,reverseKeys(item)]));return value;}
for(const rule of Object.values(rules)){assert.deepEqual(doc.categories(rule),doc.categories(reverseKeys(rule)));}
assert.equal(doc.rows(rules.DEU,'urban')[0].fine,30);assert.equal(doc.rows(rules.DEU,'rural')[0].fine,20);
assert.equal(doc.rows(rules.FRA,'at_most_50')[0].fine,135);assert.equal(doc.rows(rules.FRA,'above_50')[0].fine,68);
assert.equal(doc.rows(rules.CHE,'motorway')[0].fine,20);assert.equal(doc.rows(rules.CHE,'urban')[3].fine,null);
assert.equal(doc.rows(rules.NLD,'urban').find(row=>row.min===12).fine,140);assert.equal(doc.rows(rules.NLD,'urban_30').find(row=>row.min===12).fine,194);assert.equal(doc.rows(rules.NLD,'rural').find(row=>row.min===12).fine,134);assert.equal(doc.rows(rules.NLD,'motorway').find(row=>row.min===12).fine,126);
assert.equal(doc.rows(rules.NLD,'motorway')[0].min,4);assert.equal(doc.rows(rules.NLD,'motorway_130')[0].fine,12);
assert.equal(doc.rows(rules.NLD,'motorway').at(-1).condition,'criminal');assert.equal(doc.rows(rules.NLD,'motorway').at(-1).fine,null);
assert.equal(doc.rows(rules.GBR,'general')[0].fine,100);assert.equal(doc.field(rules.GBR,'currency_code'),'GBP');
assert.equal(doc.rows(rules.BEL,'general')[1].fine,null);assert.equal(doc.rows(rules.ISL,'general')[0].fine,20000);
const translations=JSON.parse(fs.readFileSync('shared/penalty-documentation/translations.json'));assert.equal(Object.keys(translations).length,9);
for(const [locale,text] of Object.entries(translations)){assert.deepEqual(Object.keys(text),Object.keys(translations.en));assert(Object.values(text).every(value=>typeof value==='string' && value.length),locale);assert(text.disclaimer.length,locale);}
// A source edit must flow through without regenerating documentation data.
const changed=structuredClone(rules.NLD);changed.speeding_tariffs.road_categories.urban.fines_eur['12']=999;assert.equal(doc.rows(changed,'urban').find(row=>row.min===12).fine,999);
console.log('PASS: 12 JSON rule countries, road/limit variants, Dutch thresholds, missing values, non-EUR currencies, source mutation and 9 complete presentation locales.');
