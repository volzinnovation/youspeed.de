const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(require.resolve('../../inspector/app.js'), 'utf8');

function productionFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  const end = source.indexOf('\nfunction ', start + 1);
  assert.ok(start >= 0 && end > start, `production function ${name} exists`);
  return source.slice(start, end);
}

function harness(executeRows = () => { throw new Error('Unexpected database query'); }) {
  const layers = [];
  const map = {};
  const document = {
    createElement(tag) {
      return {
        tagName: tag.toUpperCase(),
        textContent: '',
        set innerHTML(_) { throw new Error('Tooltip content must remain text'); }
      };
    }
  };
  function layer(type, points, options) {
    const value = {
      type, points, options, removed: false,
      bindTooltip(content, tooltipOptions) {
        this.content = content;
        this.tooltipOptions = tooltipOptions;
        return this;
      },
      addTo(target) { assert.equal(target, map); return this; },
      remove() { this.removed = true; }
    };
    layers.push(value);
    return value;
  }
  const sandbox = {
    document, map, portalOverlayLayers: [], sqlDatabase: {}, executeRows,
    tableExists: name => ['corridor_progress', 'corridor_pairs', 'way_endpoints'].includes(name),
    L: {
      polyline: (points, options) => layer('way', points, options),
      circleMarker: (points, options) => layer('portal', points, options)
    }
  };
  vm.createContext(sandbox);
  const styleStart = source.indexOf('const corridorPortalStyles =');
  const styleEnd = source.indexOf('\nconst adminBoundaryLimit', styleStart);
  assert.ok(styleStart >= 0 && styleEnd > styleStart);
  vm.runInContext(source.slice(styleStart, styleEnd), sandbox);
  for (const name of [
    'normalizeWayID', 'safeString', 'finiteNumber', 'streetDisplay', 'corridorKindLabel',
    'parseWayPoints', 'parseCoordinatePairs', 'formatCoordinatePair',
    'queryWayCorridorMemberships', 'queryCorridorSideRows', 'queryCorridorPairsByMain',
    'queryCorridorPairsByPaired', 'queryPortalNodePoint', 'queryPortalWayRows',
    'buildPortalFocusState', 'queryPortalContextsForWayIDs',
    'portalLineStyle', 'portalPointStyle', 'clearPortalOverlay', 'drawPortalOverlay'
  ]) vm.runInContext(productionFunction(name), sandbox);
  return {layers, draw: sandbox.drawPortalOverlay, query: sandbox.queryPortalContextsForWayIDs};
}

function way(overrides = {}) {
  return {
    way_id: 123,
    street_name: 'Teststraße',
    ref: 'B 10',
    points_json: JSON.stringify([[49, 8.4], [49.001, 8.401]]),
    ...overrides
  };
}

function context(overrides = {}) {
  return {
    mainKind: 'tunnel', sideNodeKey: 'synthetic-node',
    insideWays: [], outsideCorridors: [], portalPoint: null,
    ...overrides
  };
}

function roadContext(row, trigger) {
  return trigger
    ? context({outsideCorridors: [{kind: 'motorway_link', ways: [row]}]})
    : context({insideWays: [row]});
}

function assertTextTooltip(layer, expected) {
  assert.equal(typeof layer.content, 'object', 'Leaflet must receive a text element');
  assert.equal(layer.content.tagName, 'SPAN');
  assert.equal(layer.content.textContent, expected);
  assert.equal(layer.tooltipOptions.sticky, true);
  assert.deepEqual(Object.keys(layer.tooltipOptions), ['sticky']);
}

const imagePayload = '<img src=x onerror="globalThis.__tooltipXss=1">';
const svgPayload = '<svg onload="globalThis.__tooltipXss=2"></svg>';
for (const trigger of [false, true]) {
  const prefix = trigger ? 'Motorway-Link trigger' : 'Tunnel inside';
  for (const [label, streetName, ref, expected] of [
    ['street name', imagePayload, null, imagePayload],
    ['ref without name', null, svgPayload, svgPayload],
    ['both fields', imagePayload, svgPayload, `${imagePayload} (${svgPayload})`],
    ['encoded markup', '&lt;img src=x onerror=alert(1)&gt;', 'B &amp; 10',
      '&lt;img src=x onerror=alert(1)&gt; (B &amp; 10)']
  ]) {
    test(`${prefix} keeps malicious ${label} as literal tooltip text`, () => {
      const app = harness();
      app.draw([roadContext(way({street_name: streetName, ref}), trigger)]);
      assert.equal(app.layers.length, 1);
      assertTextTooltip(app.layers[0], `${prefix} · ${expected}`);
    });
  }

  test(`${prefix} preserves Unicode, punctuation, and display trimming`, () => {
    const app = harness();
    app.draw([roadContext(way({street_name: '  Müller & Söhne <West>  ', ref: '  "B 10" & A 8  '}), trigger)]);
    assertTextTooltip(app.layers[0], `${prefix} · Müller & Söhne <West> ("B 10" & A 8)`);
  });

  for (const [label, streetName, ref] of [
    ['null', null, null], ['empty', '', ''], ['whitespace', ' \t ', ' \n ']
  ]) {
    test(`${prefix} retains the Way-ID fallback for ${label} labels`, () => {
      const app = harness();
      app.draw([roadContext(way({street_name: streetName, ref}), trigger)]);
      assertTextTooltip(app.layers[0], `${prefix} · Way 123`);
    });
  }
}

test('safe tooltip content preserves geometry, layer styling, deduplication, and invalid-row filtering', () => {
  const app = harness();
  const row = way();
  const selected = context({
    insideWays: [row, row, way({way_id: '<123>'}),
      way({way_id: 124, points_json: 'not-json'}), way({way_id: 125, points_json: '[[49,8.4]]'})],
    outsideCorridors: [{kind: 'surface', ways: [row, row]}],
    portalPoint: [49, 8.4]
  });
  app.draw([selected, selected]);
  assert.equal(app.layers.length, 3, 'each road role and portal is drawn once');
  const [inside, trigger, portal] = app.layers;
  for (const layer of [inside, trigger]) {
    assert.equal(layer.type, 'way');
    assert.deepEqual(JSON.parse(JSON.stringify(layer.points)), [[49, 8.4], [49.001, 8.401]]);
    assert.equal(layer.options.pane, 'corridorOverlayPane');
  }
  assertTextTooltip(inside, 'Tunnel inside · Teststraße (B 10)');
  assert.equal(inside.options.color, '#48d7ff');
  assert.equal(inside.options.weight, 7);
  assert.equal(inside.options.opacity, 0.42);
  assertTextTooltip(trigger, 'Surface trigger · Teststraße (B 10)');
  assert.equal(trigger.options.color, '#ffe082');
  assert.equal(trigger.options.dashArray, '12 8');
  assert.equal(portal.type, 'portal');
  assert.equal(portal.options.pane, 'corridorPortalPane');
  assertTextTooltip(portal, 'Tunnel entry / exit · 49.000000, 8.400000');
});

for (const [label, mainKind, displayKind] of [
  ['image-handler markup', imagePayload, imagePayload],
  ['SVG-handler markup', svgPayload, svgPayload],
  ['encoded markup', '&lt;svg onload=alert(1)&gt;', '&lt;svg onload=alert(1)&gt;'],
  ['an unknown Unicode label', 'Tunnel über A & B <West> "Süd"', 'Tunnel über A & B <West> "Süd"'],
  ['the standard motorway label', 'motorway', 'Motorway']
]) {
  test(`paired imported corridor with ${label} stays text through database queries, context, and drawing`, () => {
    const queries = [];
    const app = harness((sql, parameters) => {
      const query = sql.replace(/\s+/g, ' ').trim();
      const params = Array.from(parameters);
      queries.push({query, params});
      if (query.includes('FROM corridor_progress WHERE way_id = ?1')) {
        assert.deepEqual(params, [123]);
        return [{corridor_kind: 'surface', corridor_id: 7, side_node_key: 'synthetic-node',
          start_depth_m: 0, end_depth_m: 25}];
      }
      if (query.includes('FROM corridor_pairs WHERE paired_kind = ?1')) {
        assert.deepEqual(params, ['surface', 7]);
        return [{corridor_kind: mainKind, corridor_id: 42, side_node_key: 'synthetic-node'}];
      }
      if (query.includes('FROM corridor_progress WHERE corridor_kind = ?1')) {
        assert.deepEqual(params, [mainKind, 42, 'synthetic-node']);
        return [{corridor_span_m: 120, corridor_span_nodes: 4}];
      }
      if (query.includes('FROM corridor_pairs WHERE corridor_kind = ?1')) {
        assert.deepEqual(params, [mainKind, 42, 'synthetic-node']);
        return [{paired_kind: 'surface', paired_corridor_id: 7}];
      }
      if (query.includes('FROM way_endpoints')) {
        assert.deepEqual(params, ['synthetic-node']);
        return [{lat: 49, lon: 8.4}];
      }
      if (query.includes('FROM corridor_progress cp JOIN ways w')) {
        if (params[0] === mainKind) {
          assert.deepEqual(params, [mainKind, 42, 'synthetic-node']);
          return [way({way_id: 456})];
        }
        assert.deepEqual(params, ['surface', 7, 'synthetic-node']);
        return [way()];
      }
      assert.fail(`Unexpected production query: ${query}`);
    });
    const contexts = app.query([123]);
    assert.equal(queries.length, 7);
    assert.equal(contexts.length, 1, 'unrecognized labels are preserved');
    assert.equal(contexts[0].mainKind, mainKind);
    assert.equal(contexts[0].focusWays.get(123).roles.has('outside'), true);
    app.draw(contexts);
    assert.equal(app.layers.length, 3);
    assertTextTooltip(app.layers[0], `${displayKind} inside · Teststraße (B 10)`);
    assertTextTooltip(app.layers[1], 'Surface trigger · Teststraße (B 10)');
    const portal = app.layers[2];
    assert.equal(portal.type, 'portal');
    assertTextTooltip(portal, `${displayKind} entry / exit · 49.000000, 8.400000`);
    assert.deepEqual(JSON.parse(JSON.stringify(portal.points)), [49, 8.4]);
    assert.equal(portal.options.pane, 'corridorPortalPane');
    assert.equal(portal.options.radius, 8);
    assert.equal(portal.options.color, mainKind === 'motorway' ? '#ffe1dc' : '#c7f4ff');
    assert.equal(portal.options.fillOpacity, 0.95);
  });
}

test('redrawing or clearing portal overlays removes every previous layer', () => {
  const app = harness();
  app.draw([context({insideWays: [way()], portalPoint: [49, 8.4]})]);
  const previous = [...app.layers];
  app.draw([roadContext(way({way_id: 456}), true)]);
  assert.ok(previous.every(layer => layer.removed));
  assert.equal(app.layers[2].removed, false);
  app.draw([]);
  assert.ok(app.layers.every(layer => layer.removed));
  app.draw(null);
  assert.equal(app.layers.length, 3);
});
