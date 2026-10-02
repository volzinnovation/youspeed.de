# Corrected topology for the offline exit experiment

These small public OpenStreetMap extracts preserve original node/way identity,
raw relevant tags, explicit traversal directions and interior-node connections.
They were fetched through the main OSM API on 28 September 2026; each JSON records
its exact request, original XML SHA-256, retrieval time and ODbL attribution.

They are **current-map counterfactual context**, not the bundle that the vehicle
or historical Panoramax photographer used. No mobile bundle was changed. A lane
tag or topological connection does not establish the ego lane or a sign's
governing road. Missing explicit direction stays unknown; turn restrictions and
conditional access are not interpreted. Coincident coordinates do not merge
distinct OSM nodes.

| Extract | Purpose |
| --- | --- |
| `brouck.json` | Logged A4 service-area failure: real departure at an interior mainline node |
| `a10-orleans.json` | Newly reviewed Panoramax A10/Gidy service-area context |
| `issoire.json` | Newly reviewed Panoramax A75 exit 13, both directions and ramp entry |
| `bourges.json` | A71 exit 7 acquisition candidate; image host unavailable during this run, not scored as an image encounter |

At Brouck, mainline way `216220089` and Aire departure way `4683712` share node
`10532395`, which is **inside** the mainline way. An endpoint-only query can miss
this junction. The nearby way `227886706`, present as a service-road hypothesis
in the recorded log, is tagged `service=emergency_access`; it is not interchangeable
with the actual service-area departure.

At Issoire, current mainline way `546168660` has `maxspeed=110` together with
`maxspeed:lanes=110|110|90`. These tags show why an entire-way/right-image mask is
too coarse, but do not establish which lane the camera occupied. Some current
way edits postdate the public imagery; do not present these values as historical
sign truth or repair the image labels to match them.

Original XML is cached under
`inspector/logs/2026-09-28-fr-exit-experiment/osm/` (ignored). To regenerate a
fixture from its pinned source bytes:

```sh
python3 scripts/tsr/applicability/extract_osm_exit_topology.py INPUT.osm \
  --source-url 'URL_RECORDED_IN_JSON' --site-id SITE \
  --fetched-at 'TIME_RECORDED_IN_JSON' --output OUTPUT.json
python3 -m pytest tests/tsr/test_exit_topology_experiment.py -q
```

Re-fetching a live OSM URL can return different bytes. Preserve the previous
fixture and record a new version/hash instead of silently replacing its source.

`brouck-replay.report.json` compares recorded selected ways against the two
connectivity variants without changing the recorded frames. All 49 frames have
no recorded branches and no endpoint-only departure in this extract; all 49 gain
the interior-node departure when original node identity is used. Forty-six road
snapshots remain stale. This is structural coverage, not sign applicability,
distance-to-junction or native authority replay. A connection anywhere along a
way does not prove that it is near the camera.

```sh
python3 scripts/tsr/applicability/topology_gap_replay.py --recorded shared/tsr/applicability/fixtures/fr-exit-failures-20260928-v1.json --topology shared/tsr/applicability/fixtures/corrected-exit-topology-v1/brouck.json --scenario clip-143435 --output /tmp/brouck-replay.report.json
```
