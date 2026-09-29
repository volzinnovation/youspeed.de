(function () {
  "use strict";
  const core = window.YouSpeedTrackPath;
  const el = id => document.getElementById("track-path-" + id);
  const video = document.getElementById("track-video"), canvas = el("overlay"), ctx = canvas.getContext("2d");
  let parsed = null, state = null, source = "", importVersion = 0, alignmentKey = null, selection = null;
  const percent = n => Math.round(n * 100) + "%";

  function render() {
    canvas.hidden = true;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    el("detail").textContent = "";
    if (!el("enabled").checked) { el("status").textContent = "Overlay ausgeschaltet."; return; }
    const offset = Number(el("offset").value);
    if (!Number.isFinite(offset) || Math.abs(offset) > 86400000) { el("status").textContent = "Gültigen Logversatz innerhalb von ±24 h eingeben."; return; }
    const context = {...state, geometryId: el("geometry").value, alignmentConfirmed: el("confirmed").checked,
      timeMs: state?.timeMs == null ? null : state.timeMs + offset};
    if (selection?.frameId && Math.abs(selection.time - context.timeMs) <= 80) context.frameId = selection.frameId;
    const result = core.selectFrame(parsed, context);
    if (!result.frame) { el("status").textContent = result.reason; return; }
    const frame = result.frame;
    const width = video.clientWidth, height = video.clientHeight;
    const box = core.viewport(width, height, state.videoWidth, state.videoHeight);
    if (!box) { el("status").textContent = "Videobild noch nicht verfügbar."; return; }
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const at = p => [box.x + p[0] * box.width, box.y + p[1] * box.height];
    function line(points, color, dash = [], fill = false) {
      if (!points?.length) return;
      ctx.beginPath();
      points.forEach((point, index) => { const [x, y] = at(point); index ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.setLineDash(dash);
      if (fill) { ctx.closePath(); ctx.fillStyle = color; ctx.globalAlpha = .14; ctx.fill(); ctx.globalAlpha = 1; }
      ctx.stroke(); ctx.setLineDash([]);
    }
    const labels = [];
    function label(text, point, color) {
      const [x, y] = at(point);
      ctx.font = "12px ui-monospace, monospace";
      const labelWidth = ctx.measureText(text).width + 8, left = Math.min(Math.max(box.x, x + 4), box.x + box.width - labelWidth);
      let top = Math.max(box.y, Math.min(box.y + box.height - 17, y - 20));
      // Boundaries often converge near the horizon; stack their labels so every score remains readable.
      const origin = top;
      for (let attempt = 0; attempt < 32; attempt++) {
        const overlaps = labels.some(r => left < r.x + r.width && left + labelWidth > r.x && top < r.y + 19 && top + 19 > r.y);
        if (!overlaps) break;
        const step = Math.ceil((attempt + 1) / 2) * 20 * (attempt % 2 ? -1 : 1);
        top = Math.max(box.y, Math.min(box.y + box.height - 17, origin + step));
      }
      labels.push({x: left, y: top, width: labelWidth});
      ctx.fillStyle = "rgba(0,0,0,.82)"; ctx.fillRect(left, top, labelWidth, 17);
      ctx.fillStyle = color; ctx.fillText(text, left + 4, top + 13);
    }
    for (const corridor of frame.corridors) {
      if (!corridor.imagePolygon?.length) continue;
      const color = corridor.role === "current_path" ? "#5bdcc1" : corridor.role === "other_path" ? "#ad9cff" : "#ffcf70";
      line(corridor.imagePolygon, color, corridor.role === "unknown" ? [5, 5] : [], true);
      label(corridor.role + " " + percent(corridor.confidence), corridor.imagePolygon[0], color);
    }
    for (const boundary of frame.boundaries) {
      const color = boundary.cue === "paint" ? "#ffdb78" : "#c8d2df";
      line(boundary.points, color, boundary.cue === "edge" ? [4, 5] : []);
      label((boundary.cue === "paint" ? "Markierung? " : "Kante? ") + percent(boundary.confidence), boundary.points[0], color);
    }
    if (frame.trajectoryImage?.length) line(frame.trajectoryImage, "#66e4ff", [7, 4]);
    for (const sign of frame.signBoxes) {
      const association = (frame.associations ?? []).find(a => a.trackId === sign.trackId);
      line([[sign.x, sign.y], [sign.x + sign.width, sign.y], [sign.x + sign.width, sign.y + sign.height],
        [sign.x, sign.y + sign.height], [sign.x, sign.y]], "#e8efff");
      label(association?.classification ?? "unknown", [sign.x, sign.y], "#e8efff");
    }
    canvas.hidden = false;
    el("status").textContent = `Frame ${frame.frameId} · Δ ${result.deltaMs.toFixed(0)} ms · ` +
      `${frame.boundaries.length} Grenzen · ${frame.corridors.length} Pfadhypothesen · ` +
      (frame.calibrationAvailable ? "Kamerakonfiguration vorhanden" : "Kalibrierung unbekannt") + " · visuelle Evidenz, keine Gültigkeitsentscheidung.";
    el("detail").textContent = JSON.stringify({
      frameId: frame.frameId, exposureUTC: new Date(frame.time).toISOString(), geometryId: frame.geometryId,
      alignment: result.alignment, alignmentDeltaMs: result.deltaMs, mountProfile: frame.mountProfile,
      calibrationAvailable: frame.calibrationAvailable, calibration: frame.calibration,
      cameraHeightMeters: frame.cameraHeightMeters, cameraLateralOffsetMeters: frame.cameraLateralOffsetMeters,
      trajectorySamples: frame.trajectorySamples, trajectory: frame.trajectory,
      preprocessingMs: frame.preprocessingMs, geometryMs: frame.geometryMs, addedProcessingMs: frame.addedProcessingMs,
      totalAddedProcessingMs: frame.totalAddedProcessingMs, captureAgeAtEvaluationMs: frame.captureAgeAtEvaluationMs,
      deadlineExceeded: frame.deadlineExceeded, geometryDeadlineExceeded: frame.geometryDeadlineExceeded,
      corridors: frame.corridors, associations: frame.associations
    }, null, 2);
  }

  function load(text, name) {
    parsed = core.parseLog(text); source = name; selection = null;
    el("confirmed").checked = false;
    el("geometry").replaceChildren(new Option("Bitte auswählen", ""));
    for (const geometry of parsed.geometryIds) el("geometry").append(new Option(geometry, geometry));
    const anchors = parsed.recordings.filter(r => r?.event === "start" && r.timingQuality === "callback_anchor_estimated");
    el("summary").textContent = `${source || "Log"} · ${parsed.frames.length} Pfad-Frames · ${parsed.warnings.length} fehlerhafte Zeilen. ` +
      (anchors.length ? `${anchors.length} geschätzte Aufnahmeanker; Callback-Zeiten sind keine exakten Video-PTS. ` : "") +
      "UTC-Start unter Zeitabgleich prüfen. Positiver Logversatz wählt spätere Logzeiten. Maximal 80 ms Zuordnungsabstand.";
    render();
  }
  el("file").addEventListener("change", async event => {
    const file = event.target.files?.[0], version = ++importVersion;
    if (!file) return;
    try { const text = await file.text(); if (version === importVersion) load(text, file.name); }
    catch (error) { if (version === importVersion) { parsed = null; render(); el("status").textContent = error.message; } }
    finally { if (version === importVersion) el("file").value = ""; }
  });
  for (const id of ["enabled", "confirmed", "geometry", "offset"]) el(id).addEventListener("change", () => {
    if (id === "offset" || id === "geometry") el("confirmed").checked = false;
    render();
  });
  window.addEventListener("inspector:path-log", event => { importVersion++; load(event.detail.text, event.detail.name); });
  window.addEventListener("inspector:tsr-select", event => { selection = event.detail; render(); });
  window.addEventListener("inspector:video-frame", event => {
    state = event.detail;
    const nextKey = JSON.stringify([state.version, state.videoFile, state.startMs, state.videoWidth, state.videoHeight]);
    if (nextKey !== alignmentKey) { alignmentKey = nextKey; el("confirmed").checked = false; selection = null; }
    render();
  });
  window.addEventListener("resize", render);
})();
