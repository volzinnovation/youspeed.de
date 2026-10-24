/* Source inventory overlay only. It never participates in map matching or speed resolution. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.YouSpeedTrafficSignInventory = api;
})(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';
  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const literalLike = value => String(value).replace(/[\\%_]/g, '\\$&');
  function querySpec({bounds = null, code = '', text = '', limit = 401, rtree = false} = {}) {
    const where = [], params = [];
    let from = 'traffic_sign_inventory s';
    if (bounds) {
      const {west, south, east, north} = bounds;
      if (![west, south, east, north].every(Number.isFinite) || west > east || south > north) throw new Error('Ungültiger Kartenausschnitt');
      if (rtree) {
        from += ' JOIN traffic_sign_inventory_rtree r USING(row_id)';
        where.push('r.min_lon<=? AND r.max_lon>=? AND r.min_lat<=? AND r.max_lat>=?');
        params.push(east, west, north, south);
      } else {
        where.push('s.longitude BETWEEN ? AND ? AND s.latitude BETWEEN ? AND ?');
        params.push(west, east, south, north);
      }
    }
    if (code) {where.push('s.sign_code=?'); params.push(code);}
    if (text.trim()) {
      where.push("(s.municipality_name LIKE ? ESCAPE '\\' OR s.group_id LIKE ? ESCAPE '\\' OR s.location_id LIKE ? ESCAPE '\\')");
      const value = '%' + literalLike(text.trim()) + '%'; params.push(value, value, value);
    }
    params.push(Math.max(1, Math.min(401, Math.trunc(limit) || 1)));
    return {sql: 'SELECT s.row_id,s.sign_code,s.longitude,s.latitude,s.municipality_name,s.orientation_deg FROM ' + from +
      (where.length ? ' WHERE ' + where.join(' AND ') : '') + ' ORDER BY s.row_id LIMIT ?', params};
  }
  function artworkIndex(catalog) {
    const result = new Map();
    for (const sign of catalog?.signs ?? []) {
      if (sign.display_eligible && typeof sign.sign_code === 'string' &&
          /^tsr\/sign-pictograms\/png\/de-[a-z0-9.-]+\.png$/.test(sign.image_path ?? '')) {
        result.set(sign.sign_code, {url: '../shared/' + sign.image_path, label: sign.label?.de ?? sign.sign_code});
      }
    }
    return result;
  }
  function safeLink(value) {
    try {const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password ? u.href : null;} catch {return null;}
  }
  function createController({map, executeRows, tableExists}) {
    const el = id => document.getElementById('inventory-' + id);
    if (!el('panel')) return {databaseChanged() {}};
    let enabled = false, layer = null, art = new Map(), timer = null, rtree = true;
    const filter = () => ({code: el('class').value, text: el('query').value});
    const clear = () => {if (layer) map.removeLayer(layer); layer = null;};
    function query(options) {
      let spec = querySpec({...options, rtree: rtree && tableExists('traffic_sign_inventory_rtree')});
      try {return executeRows(spec.sql, spec.params);} catch (error) {
        if (!options.bounds || !rtree || !/rtree|module/i.test(String(error))) throw error;
        rtree = false; spec = querySpec({...options, rtree: false}); return executeRows(spec.sql, spec.params);
      }
    }
    function icon(row) {
      const a = art.get(row.sign_code);
      return L.divIcon({className: 'inventory-map-marker', html: a ?
        `<img src="${escapeHTML(a.url)}" alt="${escapeHTML(row.sign_code)}" />` :
        `<span>${escapeHTML(row.sign_code)}</span>`, iconSize: a ? [32, 32] : [86, 24], iconAnchor: a ? [16, 16] : [43, 12]});
    }
    function select(row) {
      const r = executeRows('SELECT s.*,p.publisher,p.dataset_url,p.license_id,p.license_url,p.snapshot_timestamp,p.usage_role FROM traffic_sign_inventory s JOIN traffic_sign_source p USING(source_id) WHERE s.row_id=?', [row.row_id])[0];
      if (!r) return;
      const a = art.get(r.sign_code);
      const entries = [['Gemeinde',r.municipality_name],['Koordinaten',`${Number(r.latitude).toFixed(6)}, ${Number(r.longitude).toFixed(6)}`],
        ['Ausrichtung',r.orientation_deg == null ? 'unbekannt' : `${r.orientation_deg}° (Quellenangabe)`],
        ['Bestandsstand',r.snapshot_timestamp],['Letzte Aktualisierung',r.updated_at],['Aufstellungsdatum (Quelle)',r.installed_at],
        ['OpenLR-Referenz',r.openlr_binary],['OpenLR-Zuordnungsscore',r.openlr_confidence],['Standort-ID',r.location_id],['Gruppen-ID',r.group_id],['Quelle',r.publisher]];
      const link = safeLink(r.dataset_url), license = safeLink(r.license_url);
      el('detail').innerHTML = `<h3>${escapeHTML(r.sign_code)}</h3>${a ? `<img class="inventory-detail-icon" src="${escapeHTML(a.url)}" alt="${escapeHTML(a.label)}" />` : ''}` +
        `<p>${escapeHTML(a?.label ?? r.sign_code)}</p><dl>${entries.map(([k,v]) => `<dt>${escapeHTML(k)}</dt><dd>${escapeHTML(v ?? 'unbekannt')}</dd>`).join('')}</dl>` +
        `<p>${link ? `<a href="${escapeHTML(link)}" target="_blank" rel="noopener">Datensatz</a>` : ''} · ${license ? `<a href="${escapeHTML(license)}" target="_blank" rel="noopener">${escapeHTML(r.license_id)}</a>` : escapeHTML(r.license_id)}</p>`;
      const details = document.createElement('details'), summary = document.createElement('summary'), pre = document.createElement('pre');
      summary.textContent = 'Quellattribute'; pre.className = 'raw-block';
      try {pre.textContent = JSON.stringify(JSON.parse(r.raw_properties_json), null, 2);} catch {pre.textContent = r.raw_properties_json;}
      details.append(summary, pre);el('detail').append(details);
      map.setView([Number(r.latitude),Number(r.longitude)], Math.max(17,map.getZoom()));
    }
    function list(rows) {
      el('results').replaceChildren();
      for (const row of rows.slice(0,30)) {
        const button = document.createElement('button');button.type = 'button';button.className = 'inventory-result';
        button.textContent = `${row.sign_code} · ${row.municipality_name ?? 'Gemeinde unbekannt'}`;
        button.addEventListener('click', () => select(row));el('results').append(button);
      }
    }
    function refresh() {
      clear(); if (!enabled) return;
      if (!el('show').checked) {el('status').textContent='Zeichenbestand ausgeblendet.';return;}
      if (map.getZoom()<13) {el('status').textContent='Für einzelne Zeichen auf Zoomstufe 13 oder näher zoomen; die Bestandssuche funktioniert auch ohne Zoom.';return;}
      try {
        const b = map.getBounds(), rows = query({...filter(), bounds: {west:b.getWest(),south:b.getSouth(),east:b.getEast(),north:b.getNorth()}});
        layer = L.layerGroup().addTo(map);
        for (const row of rows.slice(0,400)) {
          const marker = L.marker([Number(row.latitude),Number(row.longitude)], {icon:icon(row)}).addTo(layer);
          marker.bindTooltip(escapeHTML(`${row.sign_code} · ${row.municipality_name ?? ''}`));marker.on('click', () => select(row));
        }
        el('status').textContent = rows.length>400 ? '400 Zeichen im Ausschnitt angezeigt; für weitere Zeichen näher zoomen oder filtern.' : `${rows.length} Zeichen im Kartenausschnitt.`;
      } catch (error) {el('status').textContent='Zeichen konnten nicht geladen werden: '+String(error);}
    }
    el('show').addEventListener('change', refresh);el('class').addEventListener('change', refresh);
    el('search').addEventListener('click', () => {
      if (!enabled) return;
      try {const rows=query({...filter(),limit:31});list(rows);el('status').textContent=rows.length>30 ? 'Erste 30 Bestandstreffer. Gemeinde oder Zeichenklasse genauer eingrenzen.' : `${rows.length} Bestandstreffer.`;} catch(error){el('status').textContent=String(error);}
    });
    el('query').addEventListener('keydown', e => {if(e.key==='Enter') el('search').click();});
    map.on('moveend', () => {clearTimeout(timer);timer=setTimeout(refresh,100);});
    async function databaseChanged() {
      clear();el('detail').replaceChildren();el('results').replaceChildren();rtree=true;
      enabled=tableExists('traffic_sign_inventory') && tableExists('traffic_sign_source');
      for(const id of ['show','class','query','search']) el(id).disabled=!enabled;
      el('class').replaceChildren(new Option('Alle Zeichenklassen',''));
      if(!enabled){el('summary').textContent='Dieses Bundle enthält keinen externen Zeichenbestand.';el('status').textContent='';return;}
      const counts=executeRows('SELECT sign_code,COUNT(*) AS n FROM traffic_sign_inventory GROUP BY sign_code ORDER BY sign_code');
      for(const r of counts) el('class').add(new Option(`${r.sign_code} (${Number(r.n).toLocaleString('de-DE')})`,r.sign_code));
      const sources=executeRows('SELECT publisher,record_count,snapshot_timestamp FROM traffic_sign_source ORDER BY source_id');
      el('summary').textContent=`${counts.reduce((n,r)=>n+Number(r.n),0).toLocaleString('de-DE')} Zeichen · ${counts.length} Klassen · ${sources.map(s=>s.publisher+' · Stand '+s.snapshot_timestamp).join('; ')}`;
      refresh();
      if(!art.size) {
        try {const response=await fetch('../shared/tsr/prolix-de-class-catalog-v1.json');if(response.ok)art=artworkIndex(await response.json());} catch { /* Codes remain visible when optional artwork is unavailable. */ }
        if(enabled) refresh();
      }
    }
    return {databaseChanged};
  }
  return {querySpec, artworkIndex, escapeHTML, safeLink, createController};
});
