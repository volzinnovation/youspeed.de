(function initializeSignPositions() {
  "use strict";
  const core = window.YouSpeedSignPositionsCore;
  const el = name => document.getElementById("sign-positions-" + name);
  if (!core || !el("map")) return;
  let active = false, request = 0, controller = null, expiryTimer = null;
  let data = null, map = null, layers = null;
  const colors = {fit: "#dd8e16", capture: "#2676b9", exit: "#d45430", alternative: "#6f617e"};
  const meters = value => value < 1000 ? Math.round(value) + " m" : (value / 1000).toFixed(1) + " km";
  const date = value => new Intl.DateTimeFormat("de-DE", {dateStyle: "short", timeStyle: "medium", timeZone: "Europe/Berlin"}).format(new Date(value));
  function tooltip(value) { const node = document.createElement("span"); node.textContent = value; return node; }
  function clearMap() { if (map) map.remove(); map = null; layers = null; }
  function clearData() {
    clearTimeout(expiryTimer); expiryTimer = null;
    clearMap(); data = null; el("case").replaceChildren(); el("case").disabled = true;
    el("summary").textContent = ""; el("detail").textContent = ""; el("source").textContent = "";
    el("map-wrap").hidden = true;
  }
  function deactivate() {
    active = false; ++request; controller?.abort(); controller = null; clearData();
    el("status").textContent = "Beim Öffnen werden die aktuell freigegebenen Tempolimit-Positionen geladen.";
  }
  function selected() { return data?.cases.find(c => c.label === el("case").value); }
  function draw() {
    const c = selected(); if (!active || !c || !map) return;
    if (Date.parse(data.meta.availableUntil) <= Date.now()) { clearData(); el("status").textContent = "Freigabe abgelaufen. Bitte aktualisieren."; return; }
    layers.clearLayers();
    const mainline = new Set(c.portals.flatMap(p => [p.incoming, ...p.mainline]).filter(i => i !== null));
    const links = new Set(c.portals.map(p => p.link).filter(i => i !== null));
    c.roadIds.forEach(i => {
      const road = data.roads[i], prominent = mainline.has(i) || links.has(i) || i === c.nearestRoad;
      if (!prominent) return; // OSM supplies the ordinary background; only pinned diagnostic roads are emphasized.
      L.polyline(road.coordinates.map(core.latLng), {color: links.has(i) ? colors.exit : "#64748b", weight: links.has(i) ? 5 : 3, opacity: .8})
        .bindTooltip(tooltip(`${road.ref || road.name || road.highway} · OSM ${road.id}\nKartengeometrie, keine bestätigte Zeichenzuordnung`)).addTo(layers);
    });
    if (el("region").checked) L.polygon(core.closedRegion(c).map(core.latLng), {color: colors.fit, weight: 1.5, dashArray: c.clipped ? "6 5" : null, fillOpacity: .14})
      .bindTooltip(tooltip(c.clipped ? "Annahmebereich am künstlichen Entfernungsrand abgeschnitten" : "Annahmebereich ohne Randabschnitt; keine gemessene Genauigkeit")).addTo(layers);
    if (el("rays").checked) c.captures.forEach(p => L.polyline([core.latLng(p.point), core.latLng(p.end)], {color: colors.capture, weight: 1.5, dashArray: "5 5", opacity: .75}).addTo(layers));
    L.polyline(c.captures.map(p => core.latLng(p.point)), {color: colors.capture, weight: 2.5}).addTo(layers);
    c.captures.forEach(p => L.circleMarker(core.latLng(p.point), {radius: 5, color: "#fff", weight: 1, fillColor: colors.capture, fillOpacity: 1})
      .bindTooltip(tooltip(`Aufnahme ${date(p.time)}\nAngenommener Sichtstrahl ${p.bearing}° ± ${p.bound}°\nPositionsbereich ${meters(p.error)}${p.interpolated ? " · nachträglich interpoliert" : ""}`)).addTo(layers));
    if (el("alternatives").checked) c.scenarios.filter(s => s.point && !(s.fov === 60 && s.yaw === 0)).forEach(s => L.circleMarker(core.latLng(s.point), {radius: 4, color: colors.alternative, fillOpacity: .25, weight: 1.5})
      .bindTooltip(tooltip(`Andere Kameraannahme: ${s.fov}° Bildwinkel, ${s.yaw}° Ausrichtung\nBedingte Positionshypothese`)).addTo(layers));
    c.portals.forEach(p => L.circleMarker(core.latLng(p.point), {radius: 8, color: colors.exit, weight: 3, fillColor: "#fff", fillOpacity: .95})
      .bindTooltip(tooltip(`Kartierte ${p.highway === "motorway" ? "Autobahn" : "Straßen"}-Ausfahrt ${p.ref}\n${meters(p.distance)} von der Positionshypothese\nNähe belegt keine Gültigkeit für diese Straße.`)).addTo(layers));
    L.circleMarker(core.latLng(c.point), {radius: 8, color: "#fff", weight: 2, fillColor: colors.fit, fillOpacity: 1})
      .bindTooltip(tooltip(`Fall ${c.label} · ${core.limitLabel(c)}\n${c.point[1].toFixed(6)}, ${c.point[0].toFixed(6)}\nBerechnete Hypothese, kein vermessener Schildstandort.`)).addTo(layers);
    const bounds = L.latLngBounds(core.extentPoints(c, el("extent").value));
    map.invalidateSize(); map.fitBounds(bounds.pad(el("extent").value === "close" ? .3 : .5), {maxZoom: el("extent").value === "close" ? 19 : 18, animate: false});
    const status = core.categoryLabels[c.category];
    el("detail").textContent = `Fall ${c.label} · Vorhersage ${core.limitLabel(c)} (${c.country}) · ${c.prediction}\n${status} · ${c.captures.length} Aufnahmepositionen · ${date(c.time)}\n${c.clipped ? "Unsicherheitsbereich am Entfernungsrand abgeschnitten" : "Unsicherheitsbereich ohne Randabschnitt"}. Nominale Kameraannahme: 60° Bildwinkel, 0° seitliche Ausrichtung.`;
    el("source").textContent = `${c.source === "ch" ? "Schweizer Kartengeometrie nur als ergänzende Ansicht; Ausfahrtkontext unbekannt." : "Diagnosegeometrie: Baden-Württemberg, 13.09.2026; Ausfahrtkontext aus eingefrorenem Index."} OSM-Hintergrundkacheln können einen anderen Stand haben. Freigabe geprüft: ${date(data.meta.lifecycleCheckedAt)}.`;
  }
  function render() {
    const counts = core.counts(data.cases), near = counts.motorway + counts["other-exit"];
    el("summary").textContent = `${data.cases.length} freigegebene Tempolimit-Positionen · ${near} bei kartierten Ausfahrten · ${counts.covered} ohne indexierten Ausfahrtkandidaten · ${counts.unknown} mit unbekanntem Ausfahrtkontext.${near === 0 ? " Unter den Tempolimit-Hypothesen liegt keine bei einer indexierten Ausfahrt im 500-m-Radius." : ""}`;
    if (!data.cases.length) { el("status").textContent = "Zurzeit sind keine Tempolimit-Positionen zur Ansicht freigegeben."; return; }
    core.categories.forEach(category => {
      const cases = core.orderedCases(data.cases).filter(c => c.category === category); if (!cases.length) return;
      const group = document.createElement("optgroup"); group.label = `${core.categoryLabels[category]} · ${cases.length}`;
      cases.forEach(c => { const option = document.createElement("option"); option.value = c.label; option.textContent = `Fall ${c.label} · ${core.limitLabel(c)} · ${c.country}`; group.append(option); });
      el("case").append(group);
    });
    el("case").disabled = false; el("case").value = core.orderedCases(data.cases)[0].label;
    el("map-wrap").hidden = false;
    map = L.map(el("map"), {preferCanvas: true, zoomControl: true});
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 19, keepBuffer: 0, updateWhenIdle: true,
      updateWhenZooming: false, referrerPolicy: "origin",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap-Mitwirkende</a>'}).addTo(map);
    layers = L.layerGroup().addTo(map); el("status").textContent = "Nur vorhergesagte Höchstgeschwindigkeiten und Tempo-Zonen; keine Mindest- oder Richtgeschwindigkeiten."; draw();
  }
  async function activate() {
    if (document.hidden) return;
    active = true; const own = ++request; controller?.abort(); controller = new AbortController(); clearData();
    el("status").textContent = "Freigabe und Positionsdaten werden geladen …";
    try {
      const response = await fetch("./api/sign-positions", {cache: "no-store", credentials: "omit", signal: controller.signal});
      if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) throw new Error("Positionsdaten sind derzeit nicht verfügbar. Bitte später aktualisieren.");
      const body = await response.text(); if (body.length > 8 * 1024 * 1024) throw new Error("Positionsdaten überschreiten die zulässige Größe.");
      const parsed = core.parsePayload(JSON.parse(body));
      if (!active || own !== request || document.hidden) return;
      data = parsed; render();
      expiryTimer = setTimeout(() => { if (own === request) { clearData(); el("status").textContent = "Freigabe abgelaufen. Bitte aktualisieren."; } }, Math.min(2147483647, Math.max(1, Date.parse(data.meta.availableUntil) - Date.now())));
    } catch (error) {
      if (own !== request || !active) return;
      clearData(); el("status").textContent = error.name === "AbortError" ? "Ladevorgang abgebrochen." : error.message;
    }
  }
  el("case").addEventListener("change", draw); el("extent").addEventListener("change", draw);
  ["region", "rays", "alternatives"].forEach(id => el(id).addEventListener("change", draw));
  el("refresh").addEventListener("click", () => { if (document.body.dataset.inspectorMode === "positions") void activate(); });
  window.addEventListener("youspeed:mode", event => { if (event.detail === "positions") void activate(); else deactivate(); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) deactivate(); else if (document.body.dataset.inspectorMode === "positions") void activate(); });
  window.addEventListener("pagehide", deactivate);
  if (document.body.dataset.inspectorMode === "positions") void activate();
})();
