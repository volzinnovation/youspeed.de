const test=require('node:test');const assert=require('node:assert/strict');const tiles=require('../../inspector/map-tiles.js');
test('Inspector maps start with standard OSM tiles and visible attribution without authentication',()=>{
 const created=[];
 const L={tileLayer(url,options){assert.equal(url,'https://tile.openstreetmap.org/{z}/{x}/{y}.png');assert.equal(options.referrerPolicy,'origin');assert.equal(options.maxZoom,19);assert.match(options.attribution,/https:\/\/www\.openstreetmap\.org\/copyright/);assert.match(options.attribution,/contributors/);const layer={options};created.push(layer);return layer;}};
 assert.equal(tiles.create(L),created[0]);assert.equal(tiles.create(L),created[1]);
 created[0].options.maxZoom=18;assert.equal(created[1].options.maxZoom,19);assert.equal(tiles.options.maxZoom,19);
});
