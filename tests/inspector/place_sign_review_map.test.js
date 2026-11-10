const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const tiles = require("../../inspector/map-tiles.js");

const source = fs.readFileSync(require.resolve("../../inspector/place-sign-review-map.js"), "utf8");

function harness() {
  const layers = [];
  const fits = [];
  const selections = [];
  let removals = 0;
  function bounds(points) {
    return {
      points,
      isValid() { return this.points.length > 0; },
      extend(other) { this.points.push(...other.points); return this; },
    };
  }
  const map = {
    invalidateSize() {},
    fitBounds(extent, options) { fits.push({extent, options}); },
    remove() { removals++; },
  };
  function layer(kind, coordinates, options) {
    const item = {
      kind, coordinates, options: {...options}, events: {},
      addTo(target) { target.items?.push(this); return this; },
      bindTooltip(content) { assert.equal(typeof content, "object"); this.tooltip = content.textContent; return this; },
      on(event, callback) { this.events[event] = callback; return this; },
      setStyle(style) { Object.assign(this.options, style); },
      bringToFront() { this.raised = true; },
    };
    layers.push(item);
    return item;
  }
  const L = {
    map() { return map; },
    featureGroup() {
      return {
        items: [],
        addTo() { return this; },
        clearLayers() { for (const item of this.items) item.removed = true; this.items = []; },
        getBounds() { return bounds(this.items.map(item => item.coordinates)); },
      };
    },
    tileLayer(url, options) { return layer("tileLayer", url, options); },
    polyline(coordinates, options) { return layer("polyline", coordinates, options); },
    polygon(coordinates, options) { return layer("polygon", coordinates, options); },
    circle(coordinates, options) { return layer("circle", coordinates, options); },
    circleMarker(coordinates, options) { return layer("circleMarker", coordinates, options); },
  };
  const window = {L, YouSpeedInspectorTiles: tiles};
  vm.runInNewContext(source, {window});
  const element = {ownerDocument: {createElement() { return {}; }}};
  const control = window.YouSpeedPlaceSignReviewMap.create(element, {onSelectObservation: index => selections.push(index)});
  return {control, layers, fits, selections, removals: () => removals};
}

const place = {
  bbox_wgs84: [8.42, 48.78, 8.45, 48.81],
  bounds_ring_wgs84: [[8.421, 48.78], [8.45, 48.781], [8.449, 48.81], [8.42, 48.809], [8.421, 48.78]],
  roads: [{highway: "residential", coordinates: [[8.43, 48.79], [8.44, 48.8]]}],
};
const observations = [
  {longitude: 8.43, latitude: 48.79, camera_heading_deg: 0, bearing_deg: 0, bearing_error_deg: 20, horizontal_error_m: 7},
  {longitude: 8.431, latitude: 48.79, camera_heading_deg: 100, bearing_deg: 90, bearing_error_deg: 15, horizontal_error_m: 6},
];

test("renders the exact place ring on the shared OSM basemap even when the snapshot contains roads", () => {
  const app = harness();
  app.control.show(place, null, 0);
  const outline = app.layers.find(layer => layer.kind === "polygon");
  assert.deepEqual(Array.from(outline.coordinates, coordinate => Array.from(coordinate)), place.bounds_ring_wgs84.map(([lon, lat]) => [lat, lon]));
  const basemap = app.layers.find(layer => layer.kind === "tileLayer");
  assert.equal(basemap.coordinates, tiles.url);
  assert.equal(basemap.options.attribution, tiles.options.attribution);
  assert.equal(app.layers.filter(layer => layer.kind === "polyline").length, 0);
  assert.equal(app.fits[0].options.maxZoom, 17);
  app.control.show({...place, roads: []}, null, 0);
  assert.deepEqual(app.layers.filter(layer => layer.kind === "tileLayer"), [basemap]);
});

test("draws true-north sightlines and rotates the displayed proposal azimuth by 180 degrees", () => {
  const app = harness();
  app.control.show(place, {observations, proposal: {
    longitude: 8.435, latitude: 48.795, position_radius_m: 37.3, azimut_deg: 90,
    azimut_method: "road_tangent_with_image_proxy", position_status: "coarse_review",
  }}, 0);
  assert.deepEqual(app.layers.filter(layer => layer.kind === "circle").map(layer => layer.options.radius), [37.3, 7, 6]);
  const paths = app.layers.filter(layer => layer.kind === "polyline");
  const [arrow, north, east] = paths;
  const [origin, tip, head] = arrow.coordinates;
  assert.ok(tip[1] < origin[1] && Math.abs(tip[0] - origin[0]) < 1e-6);
  assert.ok(head[1] > tip[1]);
  assert.ok(app.layers.some(layer => layer.tooltip?.includes("Azimut-Hinweis 270°")));
  assert.equal(arrow.options.dashArray, "5 3");
  assert.ok(north.coordinates[1][0] > north.coordinates[0][0]);
  assert.ok(Math.abs(north.coordinates[1][1] - north.coordinates[0][1]) < 1e-9);
  assert.ok(east.coordinates[1][1] > east.coordinates[0][1]);
  const northWedge = app.layers.filter(layer => layer.kind === "polygon")[1].coordinates;
  assert.ok(northWedge[1][1] < northWedge[0][1]);
  assert.ok(northWedge.at(-1)[1] > northWedge[0][1]);
});

test("synchronizes camera selection and redraws only the group, with no invented position or uncertainty", () => {
  const app = harness();
  const group = {observations, proposal: null};
  app.control.show(place, group, 0);
  const markers = app.layers.filter(layer => layer.kind === "circleMarker");
  assert.equal(markers.length, 2);
  assert.equal(markers[0].options.radius, 8);
  markers[1].events.click();
  assert.deepEqual(app.selections, [1]);
  assert.equal(markers[0].options.radius, 5);
  assert.equal(markers[1].options.radius, 8);
  app.control.selectObservation(0);
  assert.equal(markers[0].options.radius, 8);
  assert.deepEqual(app.selections, [1]);
  app.control.fitGroup();
  assert.equal(app.fits.at(-1).options.maxZoom, 19);
  app.control.show(place, {observations: [observations[0]], proposal: {
    longitude: 8.435, latitude: 48.795, position_radius_m: null, azimut_deg: null, position_status: "nominal_review",
  }}, 0);
  assert.ok(markers.every(marker => marker.removed));
  assert.equal(app.layers.filter(layer => layer.kind === "circle" && !layer.removed).length, 1);
  assert.equal(app.fits.at(-1).options.maxZoom, 19);
  app.control.destroy();
  app.control.destroy();
  assert.equal(app.removals(), 1);
});

test("marks a challenged position separately from the camera evidence and hides its old direction", () => {
  const app = harness();
  app.control.show(place, {observations, proposal: {
    longitude: 8.435, latitude: 48.795, position_status: "challenged_review",
    position_radius_m: 37.3, azimut_deg: 90,
  }}, 0);
  const marker = app.layers.find(layer => layer.tooltip === "Alter Standortvorschlag widerspricht Folgeaufnahmen");
  assert.equal(marker.kind, "circleMarker");
  assert.equal(marker.options.fill, false);
  assert.equal(marker.options.dashArray, "3 3");
  assert.deepEqual(app.layers.filter(layer => layer.kind === "circle").map(layer => layer.options.radius), [7, 6]);
  assert.equal(app.layers.filter(layer => layer.kind === "polyline").length, 2);
  assert.equal(app.layers.filter(layer => layer.kind === "polygon").length, 3);
});

test("draws source inventory positions and azimuth, then clears them for an unmatched group", () => {
  const app = harness();
  const group = {observations, proposal: null, mobidata_matches: [
    {latitude: 48.795, longitude: 8.435, orientation_deg: 360, sign_code: "DE:222"},
    {latitude: 48.796, longitude: 8.436, orientation_deg: null, sign_code: "DE:222"},
  ]};
  app.control.show(place, group, 0);
  const references = app.layers.filter(layer => layer.tooltip?.startsWith("MobiData"));
  assert.equal(references.length, 2);
  assert.match(references[0].tooltip, /0° \(Quelle\)/);
  assert.match(references[1].tooltip, /Ausrichtung offen/);
  const arrows = app.layers.filter(layer => layer.kind === "polyline" && layer.options.color === "#087847");
  assert.equal(arrows.length, 1);
  assert.ok(arrows[0].coordinates[1][0] > arrows[0].coordinates[0][0]);
  app.control.fitGroup();
  assert.ok(app.fits.at(-1).extent.points.some(point => point[0] === 48.796));
  app.control.show(place, {observations, proposal: null}, 0);
  assert.ok([...references, ...arrows].every(layer => layer.removed));
});
