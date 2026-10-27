(function attachSignPositionsCore(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.YouSpeedSignPositionsCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const categories = ["motorway", "other-exit", "covered", "unknown"];
  const categoryLabels = {motorway: "Kartierte Autobahnausfahrt", "other-exit": "Andere kartierte Ausfahrt",
    covered: "Kein indexierter Ausfahrtkandidat im 500-m-Radius", unknown: "Ausfahrtkontext unbekannt"};
  const fail = () => { throw new Error("Ungültige oder unvollständige Positionsdaten."); };
  function number(value, min, max) { if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max) fail(); return value; }
  function text(value, max = 500) { if (typeof value !== "string" || value.length > max) fail(); return value; }
  function array(value, max) { if (!Array.isArray(value) || value.length > max) fail(); return value; }
  function point(value) { if (array(value, 2).length !== 2) fail(); return [number(value[0], -180, 180), number(value[1], -85, 85)]; }
  function bool(value) { if (typeof value !== "boolean") fail(); return value; }
  function index(value, count, nullable = false) {
    if (nullable && value === null) return null;
    if (!Number.isInteger(value) || value < 0 || value >= count) fail(); return value;
  }
  function time(value) { text(value, 64); if (!Number.isFinite(Date.parse(value)) || !/(Z|\+00:00)$/.test(value)) fail(); return value; }
  function speedLimit(value) {
    if (!value || !["maximum_speed", "zone_start"].includes(value.family) || value.unit !== "km/h") fail();
    return {family: value.family, value: number(value.value, Number.MIN_VALUE, 1000), unit: "km/h"};
  }
  function parsePayload(input, now = Date.now()) {
    if (!input || input.version !== 1 || input.meta?.scope !== "maximum_speed_and_zone_start") fail();
    const expiry = time(input.meta.availableUntil);
    if (Date.parse(expiry) <= now) throw new Error("Die Freigabe der Positionsdaten ist abgelaufen. Bitte aktualisieren.");
    const checkedAt = time(input.meta.lifecycleCheckedAt);
    if (Date.parse(checkedAt) > Date.parse(expiry)) fail();
    const classes = array(input.roadClasses, 100).map(value => text(value, 100));
    let vertices = 0;
    const roads = array(input.roads, 20000).map(row => {
      if (array(row, 5).length !== 5) fail();
      const id = text(row[0], 200), kind = classes[index(row[1], classes.length)];
      const deltas = array(row[4], 200000); if (deltas.length < 4 || deltas.length % 2) fail();
      vertices += deltas.length / 2; if (vertices > 500000) fail();
      let lon = 0, lat = 0; const coordinates = [];
      for (let i = 0; i < deltas.length; i += 2) {
        if (!Number.isSafeInteger(deltas[i]) || !Number.isSafeInteger(deltas[i + 1])) fail();
        lon += deltas[i]; lat += deltas[i + 1];
        coordinates.push(point([lon / 1e6, lat / 1e6]));
      }
      return {id, highway: kind, name: text(row[2]), ref: text(row[3]), coordinates};
    });
    if (new Set(roads.map(r => r.id)).size !== roads.length) fail();
    const cases = array(input.cases, 1000).map(c => {
      if (!c || !categories.includes(c.category) || !["bw", "ch"].includes(c.source)) fail();
      const limit = speedLimit(c.speedLimit);
      const roadIds = array(c.roadIds, 20000).map(i => index(i, roads.length));
      if (new Set(roadIds).size !== roadIds.length) fail();
      const portals = array(c.portals, 100).map(p => ({point: point(p.point), distance: number(p.distance, 0, 500.05),
        ref: text(p.ref), highway: text(p.highway, 100), incoming: index(p.incoming, roads.length, true),
        mainline: array(p.mainline, 100).map(i => index(i, roads.length)), link: index(p.link, roads.length, true)}));
      if ((c.category === "motorway") !== portals.some(p => p.highway === "motorway")
        || (["covered", "unknown"].includes(c.category) && portals.length)
        || (c.category === "other-exit" && !portals.length)) fail();
      const region = array(c.region, 512).map(point); if (region.length < 3) fail();
      const captures = array(c.captures, 64).map(p => ({point: point(p.point), end: point(p.end),
        bearing: number(p.bearing, 0, 360), bound: number(p.bound, 0, 180), error: number(p.error, 0, 100000),
        time: time(p.time), interpolated: bool(p.interpolated)}));
      if (captures.length < 2) fail();
      const scenarios = array(c.scenarios, 100).map(s => {
        if (!['estimated', 'invalid_input', 'underconstrained', 'degenerate', 'behind_camera', 'inconsistent', 'ambiguous'].includes(s.status)) fail();
        if ((s.status === 'estimated') !== (s.point !== null)) fail();
        return {fov: number(s.fov, Number.MIN_VALUE, 179.99), yaw: number(s.yaw, -180, 180), status: s.status, point: s.point === null ? null : point(s.point)};
      });
      const nearestRoad = index(c.nearestRoad, roads.length, true);
      if (nearestRoad !== null && !roadIds.includes(nearestRoad)) fail();
      if (portals.some(p => [p.incoming, p.link, ...p.mainline].some(i => i !== null && !roadIds.includes(i)))) fail();
      return {label: text(c.label, 80), category: c.category, point: point(c.point), region,
        clipped: bool(c.clipped), bounded: bool(c.bounded), prediction: text(c.prediction), country: text(c.country, 2),
        time: time(c.time), source: c.source, roadIds, nearestRoad, roadDistance: c.roadDistance === null ? null : number(c.roadDistance, 0, 1000000),
        portals, captures, scenarios, speedLimit: limit};
    });
    if (new Set(cases.map(c => c.label)).size !== cases.length) fail();
    return {cases, roads, meta: {scope: input.meta.scope, lifecycleCheckedAt: checkedAt, availableUntil: expiry,
      totalSourceFits: number(input.meta.totalSourceFits, cases.length, 100000)}};
  }
  function orderedCases(cases) {
    return [...cases].sort((a, b) => categories.indexOf(a.category) - categories.indexOf(b.category)
      || (a.portals[0]?.distance ?? Infinity) - (b.portals[0]?.distance ?? Infinity) || a.label.localeCompare(b.label, "de", {numeric: true}));
  }
  function counts(cases) { return Object.fromEntries(categories.map(k => [k, cases.filter(c => c.category === k).length])); }
  const latLng = p => [p[1], p[0]];
  function closedRegion(c) {
    const result = c.region.map(p => [...p]);
    if (result.length && (result[0][0] !== result.at(-1)[0] || result[0][1] !== result.at(-1)[1])) result.push([...result[0]]);
    return result;
  }
  function extentPoints(c, mode) {
    const points = [c.point, ...c.captures.map(p => p.point)];
    if (mode === "uncertainty") points.push(...c.region, ...c.scenarios.filter(s => s.point).map(s => s.point));
    else if (mode === "context") points.push(...c.portals.map(p => p.point));
    return points.map(latLng);
  }
  function limitLabel(c) { return `${c.speedLimit.family === "zone_start" ? "Tempo-Zone " : ""}${c.speedLimit.value} km/h`; }
  return {parsePayload, orderedCases, counts, categories, categoryLabels, latLng, closedRegion, extentPoints, limitLabel};
});
