/* One attributed OpenStreetMap basemap shared by Inspector workspaces. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.YouSpeedInspectorTiles=api;})(typeof window==='undefined'?globalThis:window,function(){
  'use strict';
  const url='https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  const options={maxZoom:19,referrerPolicy:'origin',attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'};
  function create(L){return L.tileLayer(url,{...options});}
  return {url,options,create};
});
