/* Local drive/TSR correlation. No map, network, or mobile policy dependencies. */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.YouSpeedTrackTSR = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const countries = ["DE", "FR", "BE", "NL", "CH"];
  const number = value => value == null || value === "" || value === "none" ? null :
    (Number.isFinite(Number(value)) ? Number(value) : null);
  const country = value => countries.includes(String(value).toUpperCase()) ? String(value).toUpperCase() : null;
  const scopeKey = s => JSON.stringify([s?.sessionId, s?.generation, s?.contextGeneration,
    s?.traversalEpoch, s?.bundleId, s?.cameraGeometryId]);
  const semanticKey = s => `${s?.kind ?? "unknown"}:${s?.value ?? ""}:${s?.unit ?? ""}`;
  const kv = line => Object.fromEntries(Array.from(line.matchAll(/(?:^|\s)([\w]+)=([^\s]*)/g), m => [m[1], m[2]]));

  function parseLog(text) {
    const observations = [], legacy = [], activations = [], warnings = [];
    let activeCountry = null, frames = 0, ignored = 0;
    const seen = new Map();
    let records;
    try {
      const parsed = JSON.parse(text);
      records = (Array.isArray(parsed) ? parsed : parsed.frames ?? [parsed]).map((value, i) => [value, i + 1]);
    } catch (_) {
      records = String(text).split(/\r?\n/).map((value, i) => [value, i + 1]);
    }
    for (const [raw, line] of records) {
      if (!raw || typeof raw === "string" && !raw.trim()) continue;
      try {
        let value = raw, fields = {};
        if (typeof raw === "string") {
          if (raw.trim().startsWith("{")) value = JSON.parse(raw);
          else {
            fields = kv(raw);
            const marker = "tsr_applicability_v1=";
            value = raw.includes(marker) ? JSON.parse(raw.slice(raw.indexOf(marker) + marker.length)) : fields;
          }
        }
        if (value.event === "tsr_applicability_v1") {
          value = value.details?.evidence ?? value.evidence;
          if (typeof value === "string") value = JSON.parse(value);
        }
        if (value.lifecycle) {
          // Loading/switch events also precede frames in logs without a ready country.
          activeCountry = country(value.country) ?? country(value.pack?.slice(0, 2)) ?? activeCountry;
          continue;
        }
        const batch = value.batch;
        if (batch) {
          if (!Array.isArray(batch.candidates) || number(batch.capturedAtMs) == null || !batch.frameId) {
            throw new Error("Ungültiger Diagnose-Frame");
          }
          if ((value.tracks != null && !Array.isArray(value.tracks)) ||
              (value.decisions != null && !Array.isArray(value.decisions)) ||
              batch.candidates.some(c => !c || typeof c.semanticKey !== "string" ||
                (c.rawClassId != null && typeof c.rawClassId !== "string") ||
                (c.classId != null && typeof c.classId !== "string"))) {
            throw new Error("Ungültige Kandidaten- oder Track-Daten");
          }
          const frameKey = scopeKey(batch.scope) + batch.frameId;
          const fingerprint = JSON.stringify(value);
          if (seen.has(frameKey)) {
            if (seen.get(frameKey) !== fingerprint) throw new Error("Widersprüchlicher doppelter Frame");
            continue;
          }
          seen.set(frameKey, fingerprint);
          frames++;
          for (const candidate of batch.candidates) {
            const track = (value.tracks ?? []).find(t => t.samples?.some(s =>
              s.frameId === batch.frameId && s.candidate?.candidateId === candidate.candidateId));
            const decisions = (value.decisions ?? []).filter(d => track && d.trackId === track.trackId && d.frameId === batch.frameId);
            observations.push({ time: Number(batch.capturedAtMs), line, kind: "detection",
              country: country(batch.country ?? value.country) ?? activeCountry, semantic: candidate.semanticKey ?? "unknown::",
              classId: candidate.rawClassId ?? candidate.classId ?? null,
              score: number(candidate.recognitionScore ?? candidate.rawScore), eligible: candidate.recognitionEligible === true,
              scope: scopeKey(batch.scope), trackId: track?.trackId ?? null, frameId: batch.frameId,
              modelId: batch.modelId, diagnostics: decisions.flatMap(d => [d.classification, ...(d.reasons ?? [])]).filter(Boolean),
              wayId: batch.road?.wayId ?? null });
          }
          continue;
        }
        const time = Date.parse(value.timestamp ?? value.timestampUTC ?? "");
        if (value.passage_activation) {
          if (!Number.isFinite(time)) throw new Error("Aktivierung ohne Zeitstempel");
          const action = {camera_posted_maximum: "maximum_speed", camera_zone_start: "zone_start",
            camera_zone_end: "zone_end", camera_city_entry: "city_entry", camera_city_exit: "city_exit",
            camera_restriction_end: "restriction_end"}[value.reason];
          const numeric = action === "maximum_speed" || action === "zone_start";
          activations.push({time, line, kind: value.passage_activation === "applied" ? "applied" : "rejected",
            country: country(value.country) ?? activeCountry,
            semantic: `${action ?? "unknown"}:${numeric ? number(value.effective_kmh) ?? "" : ""}:${numeric ? "km/h" : ""}`,
            reason: value.reason, effective: number(value.effective_kmh), trackId: value.track,
            diagnostics: [], count: 1});
          continue;
        }
        if (["provisional", "confirmed"].includes(value.state) && Number.isFinite(time)) {
          legacy.push({time, line, kind: "detection", country: country(value.country) ?? activeCountry,
            semantic: number(value.speed_kmh) == null ? "unknown::" : `maximum_speed:${value.speed_kmh}:km/h`,
            score: number(value.confidence), eligible: value.state === "confirmed", legacyState: value.state,
            trackId: value.track === "none" ? null : value.track, scope: "legacy", diagnostics: []});
          continue;
        }
        ignored++;
      } catch (error) { warnings.push(`Zeile ${line}: ${error.message}`); }
    }
    // Legacy state updates are not extra physical detections when frame evidence exists.
    const samples = frames ? observations : legacy;
    const groups = [], latest = new Map();
    samples.sort((a, b) => a.time - b.time || a.line - b.line);
    for (const sample of samples) {
      const key = JSON.stringify([sample.scope, sample.trackId, sample.country, sample.modelId, sample.semantic, sample.classId]);
      const previous = latest.get(key);
      // This is a sighting group, not a claim of physical identity across long gaps.
      if (previous && sample.time - previous.endTime <= 3000 &&
          (!sample.frameId || previous.lastFrameId !== sample.frameId)) {
        previous.endTime = sample.time;
        previous.lastFrameId = sample.frameId;
        previous.count++;
        previous.eligible ||= sample.eligible;
        previous.diagnostics = Array.from(new Set([...previous.diagnostics, ...sample.diagnostics]));
        if ((sample.score ?? -1) > (previous.score ?? -1)) previous.score = sample.score;
      } else {
        const group = {...sample, lastFrameId: sample.frameId, endTime: sample.time, count: 1};
        latest.set(key, group);
        groups.push(group);
      }
    }
    return {events: [...groups, ...activations].sort((a, b) => a.time - b.time || a.line - b.line),
      frames, samples: samples.length, ignored, warnings};
  }

  function joinTrack(events, entries, maxDeltaMs = 2000) {
    const fixes = entries.map((entry, index) => ({entry, index, time: Date.parse(entry.timestampUTC ?? ""),
      lat: number(entry.lat), lon: number(entry.lon)})).filter(f => Number.isFinite(f.time) && f.lat != null &&
        f.lon != null && Math.abs(f.lat) <= 90 && Math.abs(f.lon) <= 180).sort((a, b) => a.time - b.time);
    return events.map(event => {
      let lo = 0, hi = fixes.length;
      while (lo < hi) { const mid = (lo + hi) >>> 1; if (fixes[mid].time < event.time) lo = mid + 1; else hi = mid; }
      const nearest = [fixes[lo - 1], fixes[lo]].filter(Boolean).sort((a, b) =>
        Math.abs(a.time - event.time) - Math.abs(b.time - event.time))[0];
      return {...event, fix: nearest && Math.abs(nearest.time - event.time) <= maxDeltaMs ? nearest : null};
    });
  }

  function artwork(event, catalogs, manifests, fallbackCountry = null) {
    const selectedCountry = event.country ?? country(fallbackCountry);
    const catalog = catalogs[selectedCountry];
    const manifest = manifests[selectedCountry];
    const valid = sign => sign?.display_eligible === true &&
      /^tsr\/sign-pictograms\/(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_.-]+\.png$/.test(sign.image_path ?? "");
    let sign = event.classId ? catalog?.signs.find(s => s.class_id === event.classId) : null;
    let basis = event.classId ? "Klasse aus Log" : "Symbol aus Semantik";
    if (!event.classId && !event.semantic.startsWith("unknown:")) {
      const classes = manifest?.class_mapping?.filter(c => semanticKey(c.semantic) === event.semantic) ?? [];
      const signs = classes.map(c => catalog?.signs.find(s => s.class_id === c.class_id)).filter(valid);
      // Multiple physical variants cannot be inferred from a semantic key.
      if (new Set(signs.map(s => s.image_path)).size === 1) sign = signs[0];
    }
    if (!valid(sign) && event.semantic.startsWith("restriction_end:")) {
      sign = catalog?.signs.find(s => s.class_id === (selectedCountry === "FR" ? "B31" : "no:end"));
      basis = "Nationales Endsymbol; Variante nicht belegt";
    }
    return {country: selectedCountry, sign: valid(sign) ? sign : null, basis,
      url: valid(sign) ? `../shared/${sign.image_path}` : null};
  }
  return {countries, parseLog, joinTrack, artwork};
});
