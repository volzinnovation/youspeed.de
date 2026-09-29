/* Local logged road geometry replay. No image inference, network or legal-applicability claims. */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.YouSpeedTrackPath = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const marker = "tsr_path_evidence_v1=";
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const identifier = value => typeof value === "string" && value.length > 0 && value.length <= 512;
  const point = p => Array.isArray(p) && p.length === 2 && p.every(v => finite(v) && v >= 0 && v <= 1);
  const points = (value, minimum = 2) => Array.isArray(value) && value.length >= minimum && value.length <= 256 && value.every(point);
  const confidence = value => finite(value) && value >= 0 && value <= 1;

  function normalize(value, line) {
    if (!value || !identifier(value.frameId) || !identifier(value.geometryId) ||
        !finite(value.capturedAtSeconds) || value.capturedAtSeconds < 946684800 || value.capturedAtSeconds > 7258118400) {
      throw new Error("Pfad-Frame ohne gültige Frame-ID, Geometrie oder UTC-Belichtungszeit");
    }
    const boundaries = value.boundaries ?? [], corridors = value.corridors ?? [], boxes = value.signBoxes ?? [];
    if (!Array.isArray(boundaries) || boundaries.length > 6 || boundaries.some(b =>
      !b || !points(b.points) || !confidence(b.confidence) || !["paint", "edge"].includes(b.cue))) {
      throw new Error("Ungültige Grenzlinien");
    }
    if (!Array.isArray(corridors) || corridors.length > 6 || corridors.some(c => !c ||
        !identifier(c.id) || !["current_path", "other_path", "unknown"].includes(c.role) || !confidence(c.confidence) ||
        (c.imagePolygon != null && !points(c.imagePolygon, 3)))) throw new Error("Ungültige Pfadhypothesen");
    if (!Array.isArray(boxes) || boxes.length > 128 || boxes.some(b => !b ||
        ![b.x, b.y, b.width, b.height].every(finite) || b.x < 0 || b.y < 0 || b.width <= 0 || b.height <= 0 ||
        b.x + b.width > 1.000001 || b.y + b.height > 1.000001)) throw new Error("Ungültige Zeichenboxen");
    if (value.trajectoryImage != null && value.trajectoryImage.length && !points(value.trajectoryImage)) throw new Error("Ungültige projizierte Trajektorie");
    if (value.associations != null && (!Array.isArray(value.associations) || value.associations.length > 128)) throw new Error("Ungültige Zeichenzuordnungen");
    return {...value, boundaries, corridors, signBoxes: boxes, line, time: value.capturedAtSeconds * 1000};
  }

  function parseLog(text) {
    let records;
    try {
      const parsed = JSON.parse(text);
      records = Array.isArray(parsed) ? parsed : Array.isArray(parsed.frames) ? parsed.frames : [parsed];
    } catch (_) { records = String(text).split(/\r?\n/); }
    const frames = [], recordings = [], warnings = [], seen = new Map();
    let ignored = 0;
    for (let i = 0; i < records.length; i++) {
      const raw = records[i];
      if (!raw || typeof raw === "string" && !raw.trim()) continue;
      let value = raw, isPath = false;
      try {
        if (typeof raw === "string") {
          if (raw.includes("tsr_path_recording_v1=")) { recordings.push(JSON.parse(raw.slice(raw.indexOf("tsr_path_recording_v1=") + 22))); continue; }
          if (raw.includes(marker)) { value = JSON.parse(raw.slice(raw.indexOf(marker) + marker.length)); isPath = true; }
          else if (raw.trim().startsWith("{")) value = JSON.parse(raw);
          else { ignored++; continue; }
        }
        if (value.event === "tsr_path_recording_v1") {
          let recording = value.details?.evidence ?? value.evidence;
          if (typeof recording === "string") recording = JSON.parse(recording);
          if (recording && typeof recording === "object") recordings.push(recording);
          continue;
        }
        if (value.event === "tsr_path_evidence_v1") {
          isPath = true;
          value = value.details?.evidence ?? value.evidence;
          if (typeof value === "string") value = JSON.parse(value);
        } else if (value?.frameId && value?.geometryId && value?.capturedAtSeconds != null) isPath = true;
        if (!isPath) { ignored++; continue; }
        const frame = normalize(value, i + 1), key = JSON.stringify([frame.geometryId, frame.frameId]);
        const fingerprint = JSON.stringify(value), previous = seen.get(key);
        if (previous) {
          if (previous.fingerprint !== fingerprint) {
            previous.frame.invalid = "Widersprüchlicher doppelter Frame";
            warnings.push(`Zeile ${i + 1}: Widersprüchlicher doppelter Frame`);
          }
          continue;
        }
        seen.set(key, {fingerprint, frame}); frames.push(frame);
      } catch (error) {
        if (isPath || typeof raw === "string" && raw.includes("tsr_path_evidence_v1")) {
          warnings.push(`Zeile ${i + 1}: ${error.message}`);
          // A corrupt newer exposure blocks older geometry; do not silently skip it in replay.
          if (finite(value?.capturedAtSeconds) && identifier(value?.geometryId) && identifier(value?.frameId)) {
            frames.push({...value, time: value.capturedAtSeconds * 1000, line: i + 1, invalid: error.message});
          }
        }
        else ignored++;
      }
    }
    frames.sort((a, b) => a.time - b.time || a.line - b.line);
    return {frames, recordings, warnings, ignored, geometryIds: [...new Set(frames.map(f => f.geometryId))]};
  }

  /** No persistence: every call either selects a closely aligned exposure or explicitly clears it. */
  function selectFrame(parsed, context) {
    const unavailable = reason => ({frame: null, reason});
    if (!parsed?.frames.length) return unavailable("Kein Pfad-Log geladen.");
    if (!context?.videoFile || context.hidden || context.seeking) return unavailable("Kein passendes Videobild.");
    const tolerance = finite(context.toleranceMs) ? Math.max(0, Math.min(100, context.toleranceMs)) : 80;
    const directlyMapped = parsed.frames.filter(f => f.dashcam?.videoFile === context.videoFile &&
      f.dashcam.timingQuality === "exposure_pts_verified" &&
      finite(f.dashcam.videoTimeSeconds) && f.dashcam.geometryId === f.geometryId);
    const direct = directlyMapped.length > 0;
    if (!direct && (!context.alignmentConfirmed || !finite(context.timeMs))) return unavailable("Zeit und Bildausschnitt für dieses Video bestätigen.");
    if (!direct && !identifier(context.geometryId)) return unavailable("Kamerageometrie für dieses Video auswählen.");
    let candidates = direct ? directlyMapped : parsed.frames;
    if (context.frameId) candidates = candidates.filter(f => f.frameId === context.frameId);
    // Keep mismatched/deadline frames in the nearest search: never fall back to stale good evidence.
    let nearest = null, delta = Infinity;
    for (const frame of candidates) {
      const difference = Math.abs(direct ? (frame.dashcam.videoTimeSeconds - context.videoTimeSeconds) * 1000 : frame.time - context.timeMs);
      if (difference < delta || difference === delta && frame.time > nearest?.time) { nearest = frame; delta = difference; }
    }
    if (!nearest || !finite(delta) || delta > tolerance) return unavailable("Keine Belichtung innerhalb von " + tolerance + " ms; Overlay ausgeblendet.");
    if (nearest.invalid) return unavailable(nearest.invalid);
    if (nearest.captureClockKnown !== true) return unavailable("Belichtungsuhr nicht bestätigt; Overlay ausgeblendet.");
    if (nearest.deadlineExceeded || nearest.geometryDeadlineExceeded) return unavailable("Verarbeitungsbudget überschritten; keine gültige Geometrie.");
    if (!direct && nearest.geometryId !== context.geometryId) return unavailable("Kamerageometrie stimmt nicht überein; Overlay ausgeblendet.");
    const expectedWidth = nearest.imageWidth, expectedHeight = nearest.imageHeight;
    if (![expectedWidth, expectedHeight, context.videoWidth, context.videoHeight].every(v => finite(v) && v > 0) ||
        Math.abs((expectedWidth / expectedHeight) / (context.videoWidth / context.videoHeight) - 1) > 0.02) {
      return unavailable("Bildformat stimmt nicht überein; Overlay ausgeblendet.");
    }
    return {frame: nearest, deltaMs: delta, alignment: direct ? "logged_pts" : "confirmed_utc", reason: null};
  }

  function viewport(width, height, imageWidth, imageHeight) {
    if (![width, height, imageWidth, imageHeight].every(v => finite(v) && v > 0)) return null;
    const scale = Math.min(width / imageWidth, height / imageHeight);
    const w = imageWidth * scale, h = imageHeight * scale;
    return {x: (width - w) / 2, y: (height - h) / 2, width: w, height: h};
  }
  return {parseLog, selectFrame, viewport};
});
