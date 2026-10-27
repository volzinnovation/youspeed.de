# Traffic-speed candidate prototype

A local, offline viewer and reproducible Python pipeline for comparing aggregate
VerkehrsInfo BW / INRIX historical average speeds (Durchschnitt) with explicitly
mapped OSM limits. The study can
follow an ordered GPX route or a map window. It does not change either mobile
client or the governed speed-reference state machine.

Open `index.html` after preparing the data. There is no build step, CDN, external
map tile request, telemetry or automatic refresh. The map uses saved OSM road
geometry. Local results and source files are ignored by Git because they can
contain the user's route. Nothing is published.

## Run a route study

From the repository root, using Python 3.10 or later and the standard library:

```sh
python3 scripts/research/prepare_traffic_hotspot_inputs.py \
  --gpx /absolute/path/to/route.gpx \
  --fetch --analyze --speed-field average_speed \
  --output-dir prototypes/traffic-hotspots
```

`--fetch` sends the study bounding box to the public traffic API and a bounding
box covering the returned traffic geometry to OSM Overpass. It does not upload
the GPX file or point sequence. If the route area must remain private, provide
previously downloaded data with `--traffic-file traffic.geojson --osm-file
osm.json` instead of `--fetch`. No network request is made in that mode.

For a map window, omit `--gpx` and provide `--map-url`; `--width` and `--height`
default to 1280 × 800. The link's zoom uses MapLibre's 512-pixel convention.

The preparation step saves exact source responses, query text, source hashes,
the OSM replication timestamp and a small SQLite study extract under `inputs/`.
The ranking step writes `report.json`, `data.js`, `candidates.geojson` and
`candidates.csv`. The report includes every traffic section's diagnostics,
matched OSM IDs, source tags and reasons for exclusion. It can be regenerated
without network access from the retained inputs.

`average_speed` (Durchschnitt) is the default for both command-line tools.
`--speed-field speed` explicitly selects Aktuell instead. Changing the field
recalculates eligibility, ranking, excess, coverage and exports; it does not
fetch a new snapshot when offline inputs are supplied.

## Interpretation

- `average_speed` (Durchschnitt) is the historical typical speed for the selected
  day of week and time. `speed` (Aktuell) is the current aggregate estimate;
  `reference_speed` represents free-flow conditions. Only the selected field
  is compared with the mapped legal limit, with no fallback to another field.
- Durchschnitt has no separate confidence score or sample size in this feed.
  Current `score`, `c_value` and closure state do not filter or rate a historical
  average. They remain explicitly labelled current-source context. In Aktuell
  mode only, retain measured-source `score=30` and `c_value >= 70`. The c-value
  is a provider quality index, not a probability of speeding.
- GPX selection follows ordered line segments, including long intervals between
  vertices. A metadata creation timestamp is not a recorded journey time.
- Match the complete traffic geometry at up to 5 m intervals, within 15 m and
  35° of directed OSM road geometry. Respect one-way direction. Exclude
  ambiguous parallel alignments, spatial gaps and disconnected matched paths.
- Require a single explicit numeric limit over the complete traffic link.
  Preserve directional tags. Exclude missing, unlimited, variable, conditional,
  vehicle-specific and lane-specific uncertainty. No missing urban/rural limit
  is guessed. This intentionally excludes some valid observations.
- For a GPX study, at least 99.5% of the traffic link must align within 30 m and
  35° of the route, and all matched directed OSM ways must occur on the GPX's
  unambiguous OSM match. This is a corridor screen, not a production route matcher.
- Rank excess by km/h, then percent, then stable section ID. Aktuell mode can
  also use its provider c-value as a tie-breaker; Durchschnitt never uses it.
  “Threshold met” means excess ≥ max(10 km/h, 20% of mapped limit). Smaller
  positive differences are labelled “Small excess”. The top five eligible
  comparisons also include zero and negative differences, labelled at/below
  the limit; only positive differences count as speeding candidates. Adjacent same-road,
  same-direction, same-limit candidates are grouped; displayed speed remains
  the strongest member's exact reported speed. Return fewer than ten when
  fewer qualify.
- A link average cannot locate speeding within a short lower-limit section.
  The tool excludes mixed-limit links instead of assigning their average to
  each smaller OSM subsection.
- Unknown source timestamp offsets remain visibly unknown. In Durchschnitt
  mode, the snapshot time identifies the selected historical day/time profile;
  it is not the measurement time of the trips underlying that profile. The
  historical training/aggregation period is not supplied. Saved evidence is
  a snapshot, not a claim about current traffic or persistent speeding. OSM
  tags can also be wrong or outdated. The output cannot establish individual
  violations, speeding prevalence or vehicle counts.

## Source status

Public GeoJSON access to the traffic collection was verified on 27 October
2026. Its ID and schema are discovered implementation details, not a promised
stable API contract. Reuse/caching terms and speed capping/filtering remain
unconfirmed. OSM data is © OpenStreetMap contributors, licensed under ODbL.
The prototype is local research; public delivery needs source-specific terms.

- [Traffic collection](https://geoapi.goat.plan4better.de/collections/58f3d092-4837-473b-bf8b-c14dfb26f049)
- [INRIX speed field definitions](https://docs.inrix.com/traffic/segmentspeed/)
- [INRIX confidence definitions](https://docs.inrix.com/ra/datanetworkandxdtraffic/)
- [OSM maxspeed](https://wiki.openstreetmap.org/wiki/Key:maxspeed)
- [OSM attribution and licence](https://www.openstreetmap.org/copyright)

## Validation

```sh
python3 -m unittest discover -s tests/research -p 'test_traffic_hotspot*.py' -v
```

Tests cover coordinate preservation, exact direction, mixed limits, conditional
uncertainty, historical fallbacks, parallel-road ambiguity, one-way rejection,
GPX direction and branch exclusion, disconnected paths and grouping.
