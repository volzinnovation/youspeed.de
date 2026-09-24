(function () {
  "use strict";
  const core = window.YouSpeedTrackTSR;
  const bridge = window.YouSpeedInspectorBridge;
  const map = bridge.trackMap;
  const el = id => document.getElementById(`track-tsr-${id}`);
  const escape = value => String(value ?? "—").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const labels = {detection: "Detektiert", applied: "Angewendet", rejected: "Abgelehnt"};
  const semanticLabels = {maximum_speed: "Höchstgeschwindigkeit", restriction_end: "Streckenlimit Ende",
    zone_start: "Zone Beginn", zone_end: "Zone Ende", city_entry: "Ortseingang", city_exit: "Ortsausgang",
    unknown: "Unbekannte Semantik", pedestrian_zone_start: "Fußgängerzone Beginn", pedestrian_zone_end: "Fußgängerzone Ende"};
  const clock = time => new Date(time).toLocaleTimeString([], {hour12: false});
  const title = e => { const [kind, value, unit] = e.semantic.split(":");
    if (core.category(e, catalogs, manifests, el("country").value) === "secondary") {
      const art = core.artwork(e, catalogs, manifests, el("country").value);
      return art.sign?.label?.de ?? art.sign?.label?.en ?? e.classId;
    }
    return `${semanticLabels[kind] ?? kind}${value ? ` ${value}${unit ? ` ${unit}` : ""}` : ""}`; };
  let parsed = null, fileName = "", events = [], markers = new Map(), selected = null, importVersion = 0;
  const layer = L.layerGroup().addTo(map), catalogs = {}, manifests = {};
  let resources;
  function loadResources() {
    if (!resources) resources = Promise.allSettled(core.countries.map(async country => {
      const paths = [`../shared/tsr/prolix-${country.toLowerCase()}-class-catalog-v1.json`,
        `../iphone/SpeedConsumerApp/TSRModelPacks/${country}.panoramax-bootstrap.tsrmodelpack/manifest.json`];
      const [catalog, manifest] = await Promise.all(paths.map(async url => {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`${country}: HTTP ${response.status}`);
        return response.json();
      }));
      catalogs[country] = catalog;
      manifests[country] = manifest;
    }));
    return resources;
  }
  function pictogram(event) {
    const art = core.artwork(event, catalogs, manifests, el("country").value);
    return { ...art, html: art.url ? `<img src="${escape(art.url)}" alt="${escape(title(event))}" />` :
      `<span class="track-tsr-placeholder" title="Kein belegtes Piktogramm">${escape(event.semantic.split(":")[1] || "?")}</span>` };
  }
  function detail(event) {
    const art = pictogram(event), fix = event.fix;
    const row = (key, value) => `<dt>${escape(key)}</dt><dd>${escape(value)}</dd>`;
    return `<div class="track-tsr-detail-title">${art.html}<strong>${escape(title(event))}</strong></div>
      <dl>${row("Status", labels[event.kind])}${row("Zeit (Browser-Zeitzone)", new Date(event.time).toLocaleString())}
      ${event.endTime > event.time ? row("Letztes Auftreten", clock(event.endTime)) : ""}
      ${row("Land (Log / Modell)", `${art.country ?? "unbekannt"}${!event.country && art.country ? " (manuell ergänzt)" : ""}`)}
      ${row("Piktogramm", art.sign ? `${art.sign.sign_code} · ${art.basis}` : "Keine eindeutige, freigegebene Zuordnung")}
      ${row("Semantik im Log", event.semantic)}${event.classId ? row("Klasse", event.classId) : ""}
      ${row("Beobachtungen", event.count)}${event.score != null ? row("Höchster Erkennungsscore", event.score.toFixed(3)) : ""}
      ${event.kind === "detection" ? row("Erkennungsschwelle erreicht", event.eligible ? "ja (keine Aktivierungszusage)" : "nein") : ""}
      ${event.reason ? row("Aktivierungsgrund", event.reason) : ""}
      ${event.effective != null ? row("Aktivierter Wert", `${event.effective} km/h`) : ""}
      ${row("GPS-Zuordnung", fix ? `${(fix.time - event.time).toFixed(0)} ms · ${fix.lat.toFixed(6)}, ${fix.lon.toFixed(6)}` : "Kein GPS-Fix innerhalb von 2 s")}
      ${fix ? row("Straße / Way", `${fix.entry.result?.streetRef ?? fix.entry.result?.streetName ?? "—"} / ${fix.entry.result?.wayID ?? "—"}`) : ""}
      ${fix ? row("Kartenlimit / wirksames Limit", `${fix.entry.result?.speedLimitKmh ?? "—"} / ${fix.entry.speedLimitOverrideKmh ?? "—"} km/h`) : ""}
      ${fix ? row("Drive-Status", fix.entry.status) : ""}
      ${row("Quelldatei / Zeile", `${fileName} / ${event.line}`)}
      ${event.trackId ? row("Track", event.trackId) : ""}
      ${event.modelId ? row("Modell-ID im Log", event.modelId) : ""}
      ${event.diagnostics?.length ? row("Applicability-Diagnose (kein Aktivierungsnachweis)", event.diagnostics.join(", ")) : ""}</dl>
      <p class="hint compact">Eine Detektion belegt weder die Richtigkeit des Zeichens noch seine Gültigkeit für die befahrene Spur.
        Angewendet/abgelehnt sind separate Aktivierungsereignisse; eine Zuordnung zum gleichen physischen Schild wird nicht behauptet.</p>`;
  }
  function select(index, focus = true, revealVideo = true) {
    selected = index;
    const event = events[index];
    if (!event) return;
    map.closePopup();
    el("detail").innerHTML = detail(event);
    for (const button of el("list").querySelectorAll("[data-tsr-event]")) button.classList.toggle("active", Number(button.dataset.tsrEvent) === index);
    if (event.fix) {
      bridge.selectDriveFix(event.fix.index);
      if (focus) map.setView([event.fix.lat, event.fix.lon], Math.max(16, map.getZoom()));
      markers.get(index)?.openPopup();
    }
    window.dispatchEvent(new CustomEvent("inspector:tsr-select", {detail: {time: event.time, revealVideo}}));
  }
  function renderStatistics() {
    const sort = el("statistics-sort").value;
    el("occurrences-heading").setAttribute("aria-sort", sort === "occurrences" ? "descending" : "none");
    el("detections-heading").setAttribute("aria-sort", sort === "detections" ? "descending" : "none");
    el("statistics-body").replaceChildren();
    if (!parsed) { el("statistics-summary").textContent = "Noch kein TSR-Log geladen."; return; }
    const stats = core.signStatistics(parsed.events, el("country").value, sort);
    el("statistics-summary").textContent = `${stats.occurrences} Vorkommen · ${stats.detections} Einzeldetektionen · ${stats.rows.length} Zeilen. ` +
      (stats.withoutClass ? `${stats.withoutClass} Vorkommen ohne Klassen-ID: separat nach Semantik aufgeführt, keine nachträglich erratene Klasse.` : "");
    const fragment = document.createDocumentFragment();
    for (const row of stats.rows) {
      const art = pictogram(row.example);
      const tr = document.createElement("tr");
      tr.innerHTML = `<th scope="row"><div class="track-tsr-statistics-sign">${art.html}<span><strong>${escape(row.classId ?? "Klasse fehlt")}</strong>
        <small>${escape(row.country ?? "Land unbekannt")}${row.classId ? "" : ` · ${escape(row.semantic)}`}</small></span></div></th>
        <td>${row.occurrences}</td><td>${row.detections}</td>`;
      fragment.append(tr);
    }
    el("statistics-body").append(fragment);
  }
  function render() {
    layer.clearLayers(); markers.clear(); el("list").replaceChildren(); el("detail").replaceChildren();
    renderStatistics();
    if (!parsed) { el("summary").textContent = "Noch kein TSR-Log geladen."; el("secondary-status").textContent = ""; return; }
    events = core.joinTrack(parsed.events, bridge.getDriveEntries());
    const options = {kind: el("kind").value, unknown: el("unknown").checked,
      secondary: el("secondary").checked, country: el("country").value};
    const visible = events.map((event, index) => ({event, index})).filter(({event}) =>
      core.isVisible(event, catalogs, manifests, options));
    const secondaryCount = events.filter(e => core.category(e, catalogs, manifests, options.country) === "secondary").length;
    const unidentified = events.filter(e => e.kind === "detection" && e.semantic.startsWith("unknown:") && !e.classId).length;
    el("secondary-status").textContent = `${secondaryCount} sekundäre Sichtungsgruppen mit nationaler Piktogramm-Zuordnung. ` +
      (unidentified ? `${unidentified} Gruppen ohne Klassen-ID: Diese älteren Aufzeichnungen lassen sich nicht nachträglich als konkrete Zeichen darstellen.` : "") +
      " Detektionen belegen nicht, dass ein Zeichen im sekundären Feld der App angezeigt wurde.";
    const unmatched = events.filter(e => !e.fix).length;
    el("summary").textContent = `${fileName} · ${parsed.frames} Frames · ${parsed.samples} Kandidaten · ${visible.length} sichtbare Ereignisse · ${unmatched} ohne GPS-Zuordnung. ` +
      `${events.filter(e => e.kind === "applied").length} angewendet, ${events.filter(e => e.kind === "rejected").length} abgelehnt. ` +
      (parsed.warnings.length ? `${parsed.warnings.length} fehlerhafte Zeilen übersprungen (${parsed.warnings.slice(0, 3).join("; ")}). ` : "") +
      (core.countries.some(c => !catalogs[c]) ? "Einige Piktogramm-Kataloge konnten nicht geladen werden. " : "") +
      (!bridge.getDriveEntries().length ? "Bitte zugehöriges Drive-Log laden." : "");
    const fragment = document.createDocumentFragment();
    for (const {event, index} of visible) {
      const art = pictogram(event);
      const button = document.createElement("button");
      button.type = "button"; button.className = `track-tsr-row ${event.kind}`; button.dataset.tsrEvent = index;
      button.innerHTML = `${art.html}<span><strong>${escape(clock(event.time))} · ${escape(title(event))}</strong>
        <small>${escape(art.country ?? "Land ?")} · ${labels[event.kind]}${core.category(event, catalogs, manifests, options.country) === "secondary" ? " · Sekundär" : ""} · ${event.count}×${event.fix ? "" : " · ohne GPS"}</small></span>`;
      fragment.append(button);
      if (!event.fix) continue;
      const marker = L.marker([event.fix.lat, event.fix.lon], {title: `${clock(event.time)} · ${title(event)} · ${labels[event.kind]}`,
        icon: L.divIcon({className: `track-tsr-marker ${event.kind}`, html: art.html + `<b>${event.kind === "applied" ? "✓" : event.kind === "rejected" ? "×" : event.count}</b>`,
          iconSize: [42, 48], iconAnchor: [21, 48], popupAnchor: [0, -44]}),
        zIndexOffset: event.kind === "applied" ? 400 : 200}).addTo(layer);
      // Same-coordinate signs remain individually reachable in the chronological list.
      marker.bindPopup(`<strong>${escape(title(event))}</strong><br>${escape(clock(event.time))} · ${labels[event.kind]}<br>${escape(art.country ?? "Land unbekannt")} · GPS-Fix`);
      marker.on("click", () => select(index, false)); markers.set(index, marker);
    }
    el("list").append(fragment);
    if (selected != null && visible.some(x => x.index === selected)) select(selected, false, false);
  }
  el("file").addEventListener("change", async event => {
    const file = event.target.files?.[0]; if (!file) return;
    const version = ++importVersion;
    el("summary").textContent = "TSR-Log wird lokal gelesen …";
    try {
      const text = await file.text();
      const next = core.parseLog(text);
      if (!next.frames && !next.events.length) throw new Error("Keine unterstützten TSR-Ereignisse gefunden.");
      await loadResources();
      if (version !== importVersion) return;
      parsed = next; fileName = file.name; selected = null; render();
    } catch (error) {
      if (version !== importVersion) return;
      parsed = null; selected = null; render(); el("summary").textContent = `Import fehlgeschlagen: ${error.message}`;
    } finally { if (version === importVersion) el("file").value = ""; }
  });
  el("clear").addEventListener("click", () => { importVersion++; parsed = null; selected = null; render(); });
  for (const id of ["country", "kind", "unknown", "secondary"]) el(id).addEventListener("change", render);
  el("statistics-sort").addEventListener("change", renderStatistics);
  el("list").addEventListener("click", event => {
    const button = event.target.closest("[data-tsr-event]"); if (button) select(Number(button.dataset.tsrEvent));
  });
  el("fit").addEventListener("click", () => {
    const points = core.joinTrack(bridge.getDriveEntries().map(e => ({time: Date.parse(e.timestampUTC)})), bridge.getDriveEntries())
      .filter(e => e.fix).map(e => [e.fix.lat, e.fix.lon]);
    if (points.length) map.fitBounds(points, {padding: [48, 48]});
  });
  window.addEventListener("inspector:drive-log", () => { selected = null; render(); });
})();
