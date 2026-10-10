/* Canonical, model-independent lane annotations. Also consumed by the CLI loader. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.YouSpeedLaneCore = api;
})(typeof window === "object" ? window : globalThis, function () {
  "use strict";
  const SCHEMA = "youspeed-lane-dataset-v1";
  const COORDINATES = "normalized_pixel_centres_top_left";
  const SPLITS = ["train", "validation", "test"];
  const clone = value => JSON.parse(JSON.stringify(value));
  const fail = message => { throw new Error(message); };
  const id = value => typeof value === "string" && /^[a-zA-Z0-9_-]{1,160}$/.test(value);
  const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  const date = value => typeof value === "string" && Number.isFinite(Date.parse(value));
  const pts = value => typeof value === "string" && /^-?\d{1,16}$/.test(value) && Number.isSafeInteger(Number(value));
  function create(datasetId) {
    return {schema: SCHEMA, id: datasetId, coordinateConvention: COORDINATES,
      curveSemantics: "visible_lane_marking_path_including_dashed_gaps", sources: [], samples: []};
  }
  function defaultSplit(groupId) {
    // FNV-1a over the explicitly chosen drive group, stable across export/import.
    let hash = 2166136261;
    for (const char of groupId) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619) >>> 0;
    const bucket = hash % 10;
    return bucket < 8 ? "train" : bucket === 8 ? "validation" : "test";
  }
  function addSource(dataset, input, groupId = input.id) {
    const existing = dataset.sources.find(s => s.id === input.id);
    if (existing) return existing;
    const group = dataset.sources.find(s => s.groupId === groupId);
    const source = {...clone(input), groupId, split: group?.split ?? defaultSplit(groupId), sequenceId: input.id};
    dataset.sources.push(source);
    return source;
  }
  function setGroup(dataset, sourceId, groupId, split) {
    if (!id(groupId) || !SPLITS.includes(split)) fail("Gültige Drive-ID und Split auswählen.");
    const source = dataset.sources.find(s => s.id === sourceId);
    if (!source) fail("Video fehlt.");
    source.groupId = groupId;
    for (const other of dataset.sources) if (other.groupId === groupId) other.split = split;
  }
  function sampleId(source, index) { return `${source.id}-${index}`; }
  function createSample(source, index, image) {
    const frame = source.frames[index];
    if (!frame) fail("Frame fehlt.");
    return {id: sampleId(source, index), sourceId: source.id, sequenceId: source.sequenceId,
      frameIndex: index, pts: frame.pts, timeSeconds: frame.timeSeconds,
      width: source.width, height: source.height, image, revision: 0,
      status: "draft", reviewedAt: null, updatedAt: new Date().toISOString(),
      draftFrom: null, curves: []};
  }
  function edited(sample, now = new Date().toISOString()) {
    sample.revision++;
    sample.status = "draft"; sample.reviewedAt = null; sample.updatedAt = now;
  }
  function confirm(sample, now = new Date().toISOString()) {
    sample.revision++; sample.status = "reviewed"; sample.reviewedAt = now; sample.updatedAt = now;
  }
  function copyDraft(source, target, nextId) {
    if (source.sourceId !== target.sourceId || source.frameIndex >= target.frameIndex) fail("Eine frühere Annotation desselben Videos auswählen.");
    if (target.curves.length || target.status === "reviewed") fail("Aktueller Frame enthält Arbeit. Zuerst explizit leeren.");
    target.curves = source.curves.map(curve => ({...clone(curve), id: nextId(),
      copiedFrom: {sampleId: source.id, annotationId: curve.id, revision: source.revision}}));
    target.draftFrom = {sampleId: source.id, revision: source.revision};
    edited(target);
  }
  function link(sample, curveId, trackId) {
    const curve = sample.curves.find(c => c.id === curveId);
    if (!curve || !id(trackId)) fail("Annotation oder Track-ID fehlt.");
    if (sample.curves.some(c => c.id !== curveId && c.trackId === trackId)) fail("Ein Track darf nur eine Kurve pro Frame enthalten.");
    curve.trackId = trackId;
    edited(sample);
  }
  function evaluate(points, t) {
    const u = 1 - t;
    return [0, 1].map(axis => u*u*u*points[0][axis] + 3*u*u*t*points[1][axis] + 3*u*t*t*points[2][axis] + t*t*t*points[3][axis]);
  }
  function polyline(curve, width, height, count = 65) {
    if (!Number.isInteger(count) || count < 2 || count > 10001) fail("2–10001 Abtastpunkte erforderlich.");
    return Array.from({length: count}, (_, i) => evaluate(curve.controlPoints, i / (count - 1))
      .map((coordinate, axis) => coordinate * ((axis ? height : width) - 1)));
  }
  function fitRect(boxWidth, boxHeight, imageWidth, imageHeight) {
    const scale = Math.min(boxWidth / imageWidth, boxHeight / imageHeight);
    const width = imageWidth * scale, height = imageHeight * scale;
    return {x: (boxWidth - width) / 2, y: (boxHeight - height) / 2, width, height};
  }
  function pointAt(x, y, rect, clamp = false) {
    const point = [(x - rect.x) / rect.width, (y - rect.y) / rect.height];
    if (!clamp && point.some(v => v < 0 || v > 1)) return null;
    return point.map(v => Math.max(0, Math.min(1, v)));
  }
  function splitManifests(dataset) {
    return Object.fromEntries(SPLITS.map(split => [split, dataset.samples
      .filter(s => s.status === "reviewed" && dataset.sources.find(v => v.id === s.sourceId)?.split === split)
      .sort((a, b) => a.sourceId.localeCompare(b.sourceId) || a.frameIndex - b.frameIndex).map(s => s.id)]));
  }
  function validate(dataset) {
    if (!dataset || dataset.schema !== SCHEMA || dataset.coordinateConvention !== COORDINATES ||
        dataset.curveSemantics !== "visible_lane_marking_path_including_dashed_gaps" || !id(dataset.id)) fail("Unbekanntes Lane-Dataset-Schema.");
    if (!Array.isArray(dataset.sources) || !Array.isArray(dataset.samples)) fail("Quellen oder Samples fehlen.");
    const sources = new Map(), groups = new Map(), samples = new Map(), annotations = new Set();
    for (const s of dataset.sources) {
      if (!sha(s.id) || s.sha256 !== s.id || sources.has(s.id) || !id(s.groupId) || !SPLITS.includes(s.split) || s.sequenceId !== s.id) fail("Ungültige oder doppelte Video-/Gruppenidentität.");
      if (groups.has(s.groupId) && groups.get(s.groupId) !== s.split) fail("Drive-Gruppe über mehrere Splits verteilt.");
      if (![s.width, s.height, s.byteLength].every(v => integer(v) && v > 0) || s.width * s.height > 36_000_000 ||
          s.transform !== "ffmpeg_autorotate_full_frame" || ![0, 90, 180, 270].includes(s.sourceRotation) ||
          typeof s.name !== "string" || !/^\d+\/\d+$/.test(s.timeBase) || !pts(s.startPts) ||
          !Array.isArray(s.frames) || !s.frames.length || s.frames.length > 1_000_000) fail("Ungültige Video-Geometrie/Frame-Liste.");
      const [num, den] = s.timeBase.split("/").map(Number);
      if (!Number.isSafeInteger(num) || !Number.isSafeInteger(den) || num <= 0 || den < num) fail("Ungültige PTS-Zeitbasis.");
      s.frames.forEach((f, i) => {
        const expected = Number(BigInt(f.pts ?? "0") - BigInt(s.startPts)) * num / den;
        if (f.index !== i || !pts(f.pts) || !Number.isFinite(f.timeSeconds) || f.timeSeconds < 0 || Math.abs(f.timeSeconds - expected) > 1e-8 ||
            (i === 0 && f.pts !== s.startPts) || (i && BigInt(f.pts) <= BigInt(s.frames[i-1].pts))) fail("Frame-Index oder PTS stimmen nicht.");
      });
      sources.set(s.id, s); groups.set(s.groupId, s.split);
    }
    for (const s of dataset.samples) {
      const source = sources.get(s.sourceId), frame = source?.frames[s.frameIndex];
      if (!source || !integer(s.frameIndex) || !frame || s.id !== sampleId(source, s.frameIndex) || samples.has(s.id) ||
          s.sequenceId !== source.sequenceId || s.pts !== frame.pts || s.timeSeconds !== frame.timeSeconds || s.width !== source.width || s.height !== source.height) fail("Sample nicht an exakten Video-Frame gebunden.");
      if (!s.image || s.image.path !== `images/${s.id}.png` || !sha(s.image.sha256) || !integer(s.image.byteLength) || !s.image.byteLength ||
          !integer(s.revision) || !["draft", "reviewed"].includes(s.status) || !date(s.updatedAt) ||
          (s.status === "reviewed" ? !date(s.reviewedAt) : s.reviewedAt !== null) || !Array.isArray(s.curves)) fail("Ungültiger Bild-/Review-Vertrag.");
      const tracks = new Set();
      for (const c of s.curves) {
        if (!id(c.id) || annotations.has(c.id) || !id(c.trackId) || tracks.has(c.trackId) || c.degree !== 3 ||
            !["solid", "dashed"].includes(c.marking) || !Array.isArray(c.controlPoints) || c.controlPoints.length !== 4 ||
            c.controlPoints.some(p => !Array.isArray(p) || p.length !== 2 || p.some(v => !Number.isFinite(v) || v < 0 || v > 1))) fail("Ungültige Bézier-Kurve/Track-ID.");
        annotations.add(c.id); tracks.add(c.trackId);
      }
      samples.set(s.id, s);
    }
    for (const s of dataset.samples) {
      for (const p of [s.draftFrom, ...s.curves.map(c => c.copiedFrom)].filter(Boolean)) {
        const from = samples.get(p.sampleId);
        if (!from || from.sourceId !== s.sourceId || from.frameIndex >= s.frameIndex || !integer(p.revision) || p.revision > from.revision ||
            (p.annotationId !== undefined && !id(p.annotationId))) fail("Ungültiger Draft-Ursprung.");
      }
    }
    return dataset;
  }
  return {SCHEMA, COORDINATES, SPLITS, clone, create, defaultSplit, addSource, setGroup,
    sampleId, createSample, edited, confirm, copyDraft, link, evaluate, polyline, fitRect, pointAt, splitManifests, validate};
});
