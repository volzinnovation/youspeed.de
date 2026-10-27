(function attachCropReviewCore(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.YouSpeedCropReviewCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const verdicts = ["confirmed", "wrong_class", "not_a_sign", "uncertain", "unreviewed"];
  const labels = {unreviewed: "Nicht geprüft", confirmed: "Klasse bestätigt", wrong_class: "Falsche Klasse",
    not_a_sign: "Kein Verkehrszeichen", uncertain: "Unsicher"};
  const exitLabels = {near_exit_candidate: "Mögliche Ausfahrtnähe", no_candidate_in_covered_radius: "Kein Kandidat im abgedeckten Radius",
    ambiguous: "Mehrdeutiger Kontext", location_missing: "Position fehlt", map_coverage_missing: "Kartenabdeckung fehlt",
    alignment_unresolved: "Zeitabgleich offen", unenriched: "Noch nicht angereichert",
    near_exit: "Mögliche Ausfahrtnähe", no_exit: "Kein Kandidat im abgedeckten Radius", unknown: "Kontext unbekannt", not_computed: "Noch nicht angereichert"};
  const exitReasons = {gps_unavailable: "Keine Aufnahmeposition verfügbar", gps_malformed: "Positionsdaten unvollständig",
    gps_accuracy_insufficient: "Position zu ungenau", gps_fix_not_aligned: "Position und Aufnahmezeit nicht sicher zugeordnet",
    gps_outside_geometry_domain: "Position außerhalb des untersuchten Kartenbereichs",
    map_coverage_incomplete: "Kartenabdeckung im Suchbereich unvollständig", map_topology_incomplete: "Verbindungen oder Fahrtrichtung in der Karte unvollständig",
    mapped_directed_exit_in_buffer: "Kartierte Ausfahrt im Suchbereich", no_mapped_directed_exit_in_complete_buffer: "Keine kartierte Ausfahrt im vollständig abgedeckten Suchbereich"};
  function identity(row) {
    return {installation_id: row.installation, collection_epoch: row.epoch, crop_id: row.crop_id};
  }
  function key(row) { return JSON.stringify(identity(row)); }
  function replayEvidence(row) {
    // Defense in depth only: the backend remains authoritative. Missing GPS by
    // itself is not evidence of replay, and a reviewer cannot override exclusion.
    const values = [row.manifest?.local_frame_token, row.manifest?.source_frame_token,
      row.observation?.observer_version, row.observation?.app?.version, row.observation?.app?.build,
      ...(Array.isArray(row.observation?.evidence?.quality_flags) ? row.observation.evidence.quality_flags : [])];
    return values.some(value => typeof value === "string" && /replay|archive|simulat/i.test(value));
  }
  function eligible(row, scope = "live") {
    return scope === "live" && row?.analysis_eligible === true && !replayEvidence(row);
  }
  function classificationLabel(value) {
    if (!value) return "Keine Ersatzklasse angegeben";
    return [value.canonical_code || value.model_label || "Unbekannte Klasse",
      value.country, value.value == null ? null : `${value.value}${value.unit ? " " + value.unit : ""}`].filter(Boolean).join(" · ");
  }
  function reviewLabel(review) {
    if (!review) return labels.unreviewed;
    const state = review.verdict || "unreviewed";
    return labels[state] + (state === "wrong_class" ? " · " + classificationLabel(review.corrected_classification) : "");
  }
  function validateClassification(value) {
    if (!value || !/^[A-Z]{2}$/.test(value.country || "") || typeof value.canonical_code !== "string"
      || !value.canonical_code.trim() || (/^[A-Z]{2}:/.test(value.canonical_code) && !value.canonical_code.startsWith(value.country + ":")) || !value.mapping_revision
      || !/^[a-f0-9]{64}$/i.test(value.mapping_sha256 || "")) throw new Error("Bitte eine gültige kanonische Klasse auswählen.");
    if (value.value != null && (typeof value.value !== "number" || !Number.isFinite(value.value))) throw new Error("Ungültiger numerischer Wert.");
    // Only the server's exact pinned registry tuple is selectable. End signs
    // legitimately contain "speed" in their family and no numeric value.
    return structuredClone(value);
  }
  function decision(row, history, form, requestId, scope = "live") {
    if (!eligible(row, scope) || history?.eligible !== true) throw new Error("Dieser Crop ist nicht für die Live-Analyse freigegeben.");
    if (!Number.isInteger(history.current_revision) || history.current_revision < 0) throw new Error("Prüfrevision fehlt. Verlauf neu laden.");
    if (!verdicts.includes(form.verdict)) throw new Error("Prüfstatus fehlt.");
    const reviewer = String(form.reviewer || "").trim();
    if (!reviewer || reviewer.length > 160) throw new Error("Bitte einen Prüfernamen eingeben (maximal 160 Zeichen).");
    const reason = String(form.reason || "").trim();
    if (reason.length > 2000) throw new Error("Begründung darf höchstens 2000 Zeichen enthalten.");
    if (!row.manifest?.observation_id || !/^[a-f0-9]{64}$/i.test(row.digest || "")) throw new Error("Unveränderliche Quellidentität fehlt.");
    return {request_id: requestId, ...identity(row), observation_id: row.manifest.observation_id,
      encoded_sha256: row.digest, previous_revision: history.current_revision, verdict: form.verdict,
      corrected_classification: form.verdict === "wrong_class" && form.corrected ? validateClassification(form.corrected) : null,
      reviewer, reason: reason || null};
  }
  function exportMembers(rows, scope = "live") {
    return rows.filter(row => eligible(row, scope) && Number.isInteger(row.current_revision) && row.current_revision > 0
      && (row.current_review?.verdict === "confirmed" || row.current_review?.verdict === "not_a_sign"
        || (row.current_review?.verdict === "wrong_class" && row.current_review.corrected_classification)))
      .map(row => ({...identity(row), revision: row.current_revision}));
  }
  function safeArtwork(url) {
    return typeof url === "string" && /^\/?(?:\.\.\/)?shared\/tsr\/sign-pictograms\/[a-zA-Z0-9_./-]+\.png$/.test(url)
      && !url.split("/").includes("..") ? url : null;
  }
  return {verdicts, labels, exitLabels, exitReasons, identity, key, replayEvidence, eligible, classificationLabel, reviewLabel,
    validateClassification, decision, exportMembers, safeArtwork};
});
