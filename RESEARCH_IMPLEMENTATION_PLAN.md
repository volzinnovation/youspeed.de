# Research and Implementation Plan (Before Coding)

Date: 2026-02-22
Scope: iPhone app for German speed-sign recognition, current speed-limit display, and fine estimation.

## 1) Legal baseline to encode

### 1.1 Default speed limits (Germany)
- Inside built-up areas (`geschlossene Ortschaften`): `50 km/h` for all motor vehicles.
- Outside built-up areas:
  - Passenger cars and other motor vehicles up to 3.5 t: `100 km/h`.
  - Other categories depend on vehicle class and trailer combinations.
- The `100 km/h` default for cars does not apply on Autobahn or comparable separated multi-lane roads unless a sign imposes a limit.

Source basis:
- `StVO §3` (speed rules and default limits)
- `StVO Anlage 3, Zeichen 310/311` (start/end of built-up area)

### 1.2 Sign-based speed rules relevant for recognition
- `Zeichen 274`: explicit maximum speed begins.
- `Zeichen 274.1/274.2`: start/end of tempo-30 zone.
- `Zeichen 278`: end of a previously imposed maximum speed.
- If no end sign is present, limit can still end by context according to StVO sign rules.

Source basis:
- `StVO Anlage 2` (Vorschriftzeichen, section for speed limits)

### 1.3 Autobahn behavior
- For passenger cars up to 3.5 t, Autobahn has a recommended speed (`Richtgeschwindigkeit`) of `130 km/h`, not a universal mandatory maximum.
- Mandatory limits still apply where signed.

Source basis:
- `BABRiGeschwV §1`

### 1.4 Fine schedule for speeding (initial app scope)
For an MVP focused on typical private-car use, implement `BKatV Anhang Tabelle 1, Abschnitt 11.3` (`andere als a/b genannte Kraftfahrzeuge`).

| Exceeding limit by | Fine inside town | Fine outside town | Typical driving ban |
|---|---:|---:|---|
| up to 10 km/h | 30 EUR | 20 EUR | none |
| 11-15 km/h | 50 EUR | 40 EUR | none |
| 16-20 km/h | 70 EUR | 60 EUR | none |
| 21-25 km/h | 115 EUR | 100 EUR | none |
| 26-30 km/h | 180 EUR | 150 EUR | none |
| 31-40 km/h | 260 EUR | 200 EUR | 1 month (inside only) |
| 41-50 km/h | 400 EUR | 320 EUR | 1 month (inside/outside) |
| 51-60 km/h | 560 EUR | 480 EUR | 2 months inside, 1 outside |
| 61-70 km/h | 700 EUR | 600 EUR | 3 months inside, 2 outside |
| above 70 km/h | 800 EUR | 700 EUR | 3 months inside/outside |

Notes:
- This is a helper estimate in-app, not legal advice.
- Keep data versioned so legal updates can be shipped quickly.

Source basis:
- `BKatV Anhang (zu Nr. 11 der Anlage), Tabelle 1, Nr. 11.3`
- `BKatV §4` (relation to regular driving-ban orders)

## 2) Rule precedence for app logic

Use deterministic precedence to merge camera, map, and defaults:

1. Active sign from camera (`274`, zone signs, end signs) with confidence + freshness window.
2. Active map-derived legal limit (`OSM maxspeed` and explicit road attributes).
3. Jurisdiction default (`50` inside, `100` outside for passenger-car profile).
4. Unknown state if confidence is too low or data conflicts are unresolved.

Implementation guidance:
- Always store both `displayed_limit` and `source_of_truth` (`camera`, `map`, `default`, `unknown`).
- Add confidence score and expiration timestamp to sign detections.
- Apply end-of-limit semantics on detected end signs (`278`, `274.2`) or validated map transitions.

## 3) Data model proposal

### 3.1 Core entities
- `SpeedObservation`
  - timestamp, lat/lon, heading, detected_sign_type, detected_value, confidence, frame_id
- `RoadContext`
  - osm_way_id, inside_built_up_area, map_maxspeed, maxspeed_source, road_type
- `EffectiveLimit`
  - value_kmh, source, valid_from, valid_until, confidence
- `FineRule`
  - vehicle_profile, location_type (`inside`/`outside`), over_min, over_max, fine_eur, ban_months
- `TripEvent`
  - vehicle_speed_kmh, limit_kmh, exceeded_by_kmh, estimated_fine_eur, warning_level_triggered

### 3.2 Storage stages
- Local only for MVP (`SQLite`/`Core Data`).
- Versioned rule table (`fine_rules_version`, `law_source_version`, `effective_from`).
- Later: optional sync to global backend.

## 4) Karlsruhe-region bootstrap plan (OSM)

Input region for early testing:
- `karlsruhe-regbez-latest.osm.pbf`

Constraint:
- Do not use PostgreSQL/PostGIS for MVP map data processing.
- Use direct `osmium`/PBF processing and generate compact artifacts for on-device lookup.

Pipeline (Osmium-first, similar to tankzeit-style offline data prep):
1. Acquire regional PBF and keep the raw file immutable (`input/karlsruhe-regbez-latest.osm.pbf`).
2. Run `osmium tags-filter` to keep only speed-relevant road network objects (`highway=*`, speed tags, place/boundary context needed for inside/outside town logic).
3. Normalize extracted objects into a compact intermediate format (GeoJSON/line records), then convert to binary app data packs.
4. Build spatial lookup structures directly from extracted ways:
   - way geometry index (R-tree or grid buckets),
   - way metadata table (`maxspeed`, `source:maxspeed`, conditionals, road class),
   - settlement/built-up-area index for `50 km/h` default logic.
5. Generate versioned artifacts for app/runtime:
   - `ways.idx` (spatial index),
   - `ways.meta` (speed attributes),
   - `areas.idx` (built-up-area polygons or tiles),
   - `manifest.json` (region, source timestamp, generator version).
6. Validate artifacts with deterministic replay traces before shipping.

Operational model:
- Heavy preprocessing runs offline on desktop/CI.
- iPhone app loads read-only artifacts and performs local nearest-way + heading-aware matching.
- Optional later backend can serve the same artifact format, but runtime stays database-independent.

Minimum extracted OSM tags:
- `highway`
- `maxspeed`
- `maxspeed:type`
- `source:maxspeed`
- `maxspeed:conditional`
- `zone:maxspeed`
- `traffic_sign`
- `name` (debugging only)
- Administrative/boundary tags required to infer built-up context when sign/map data is incomplete.

Recommended repository structure:
- `mapdata/raw/` for source PBF
- `mapdata/build/` for intermediate extraction outputs
- `mapdata/dist/` for generated app artifacts
- `scripts/map/` for reproducible osmium + packer pipeline scripts

## 5) iOS implementation plan (phased)

### Phase 0: Foundation (no ML training)
- Define legal constants and fine tables in JSON.
- Implement deterministic rules engine + unit tests.
- Build simulator feed replayer for deterministic test runs.

Exit criteria:
- Given sign/map/default inputs, effective limit and fine estimate are stable and test-covered.

### Phase 1: Vision integration
- Integrate an on-device sign-recognition model for German speed signs.
- Track sign states over time (debounce, confidence smoothing, end-sign handling).
- Show official-like sign UI plus effective limit source indicator.

Exit criteria:
- Real-time detection latency acceptable on target iPhones; false positives bounded by test set.

### Phase 2: Geolocation + map matching
- Add GPS + heading + local map matcher against Karlsruhe artifact pack.
- Fuse camera + map with precedence rules using only on-device indices/artifacts.
- Handle uncertain states explicitly (do not overstate certainty).

Exit criteria:
- Route tests show robust limit continuity and reasonable transition handling without a live map database dependency.

### Phase 3: Warning and UX safety
- User-configurable warnings by `km/h over` and/or `estimated fine`.
- Visual + audio warnings with cooldown logic (avoid alert flooding).
- Optional voice confirmation flow for newly detected limits.

Exit criteria:
- Warning behavior passes distraction/safety UX review and controlled drive tests.

### Phase 4: Persistence and analytics
- Local history storage of observed limits and exceedance events.
- Basic review screens and export for debugging.
- Prepare schema/API contract for future global database.

Exit criteria:
- Durable local logs and migration-safe schema.

## 6) Validation and compliance checklist before coding features

- Confirm vehicle-profile scope for MVP (private car only vs multiple categories).
- Add in-app disclaimer that fines are indicative and can change.
- Add law-data update mechanism (versioned static file or remote config).
- Add tests for edge cases: entering/exiting town signs, zone 30, end-sign transitions, conflicting map vs camera data.
- Add map artifact regression tests (same input PBF must produce deterministic output hashes).
- Add fallback behavior when map artifacts are missing/corrupt (camera + legal defaults only).

## 7) Authoritative sources (used in this research)

- StVO main text (`§3`, `§41`, `§42`): https://www.gesetze-im-internet.de/stvo_2013/BJNR036710013.html
- StVO `§3` direct: https://www.gesetze-im-internet.de/stvo_2013/__3.html
- StVO Anlage 2 (incl. Zeichen 274/274.1/274.2/278): https://www.gesetze-im-internet.de/stvo_2013/anlage_2.html
- StVO Anlage 3 (Zeichen 310/311): https://www.gesetze-im-internet.de/stvo_2013/anlage_3.html
- Autobahn-Richtgeschwindigkeits-VO (`130 km/h` recommendation): https://www.gesetze-im-internet.de/babrigeschwv_1978/__1.html
- BKatV main: https://www.gesetze-im-internet.de/bkatv_2013/BJNR049800013.html
- BKatV Anhang Tabelle 1 (speeding fines): https://www.gesetze-im-internet.de/bkatv_2013/anhang.html
- OSM `maxspeed` tagging reference: https://wiki.openstreetmap.org/Key:maxspeed
- Karlsruhe test PBF source: https://download.geofabrik.de/europe/germany/baden-wuerttemberg/karlsruhe-regbez-latest.osm.pbf

## 8) Daily updates via Geofabrik diffs (delta process)

Date researched: 2026-02-23

Goal:
- Avoid repeated full `*.osm.pbf` downloads for routine refreshes.
- Apply incremental Geofabrik extract updates (`.osc.gz`) and rebuild only changed artifacts where possible.

What Geofabrik provides:
- Regional extract update feeds at `*-updates/` endpoints (for example Germany):
  - `https://download.geofabrik.de/europe/germany-updates/`
- A replication `state.txt` with `sequenceNumber` and timestamp.
- Daily extract regeneration; Geofabrik also publishes update URLs in `index-v1*.json`.

Important behavior:
- Geofabrik extracts are clipped to boundaries, so update files can contain additional objects needed for consistency around cut edges.
- For long offline gaps, local data can become too old for available diffs; then a full snapshot re-bootstrap is required.

Recommended production workflow:
1. Bootstrap once from a timestamped regional PBF (not only `-latest`) and store source metadata.
2. Track local replication state (`sequenceNumber`, timestamp) per region.
3. On each refresh run:
   - fetch and apply diffs from the region `*-updates/` feed,
   - advance local state,
   - run delta-aware artifact rebuild (or full rebuild if delta path fails validation).
4. If diff chain is unavailable (too old/corrupt), download a new full PBF and reset state.

Preferred patch toolchain:
- `pyosmium-up-to-date` for automatic catch-up of an existing `.osm.pbf`.
- `pyosmium-get-changes` if explicit change files are needed for downstream delta pipelines.
- `osmium apply-changes` as a deterministic fallback/alternative patcher.

Example commands (Germany):

```bash
# A) Keep an existing germany snapshot up-to-date directly
pyosmium-up-to-date \
  --server https://download.geofabrik.de/europe/germany-updates/ \
  mapdata/raw/germany.osm.pbf
```

```bash
# B) Fetch explicit diff(s) for custom delta processing
pyosmium-get-changes \
  --server https://download.geofabrik.de/europe/germany-updates/ \
  -o mapdata/build/germany-delta.osc.gz
```

```bash
# C) Apply one or more diffs manually (oldest -> newest)
osmium apply-changes \
  mapdata/raw/germany.osm.pbf \
  mapdata/build/germany-delta.osc.gz \
  -o mapdata/raw/germany.updated.osm.pbf
```

Integration notes for this repository:
- Add `scripts/map/update_from_geofabrik_diffs.sh` to:
  - read/write a per-region state file,
  - run `pyosmium-up-to-date`,
  - emit a machine-readable update report (`before_seq`, `after_seq`, `objects_changed`, `duration_s`),
  - trigger downstream rebuild/benchmark jobs only when changes exist.
- Keep weekly full-refresh benchmark (already planned) as correctness and performance guardrail against delta drift.

Additional sources for update mechanics:
- Geofabrik technical details: https://download.geofabrik.de/technical.html
- Germany updates endpoint example: https://download.geofabrik.de/europe/germany-updates/
- pyosmium replication/update tools: https://docs.osmcode.org/pyosmium/latest/user_manual/10-Replication-Tools/
- osmium apply-changes manual: https://docs.osmcode.org/osmium/latest/osmium-apply-changes.html
