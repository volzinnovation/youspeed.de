# MobiData BW traffic signs — v1.5 implementation specification

Date: 2026-10-21. Branch: `codex/youspeed-v1.5-mobidata-bw`.
Product request: integrate BW signs with the offline road bundle, show ordinary
secondary-sign encounters within 10 m and DE:310/311 within 30 m, align speed signs with
directed OSM ways, record actual camera confirmation, reset previous speed
references at town boundaries, retain printed numeric restrictions, and add a
sign-based camera capture trigger.

Drive-review clarification from the product owner on 2026-10-21: the geofence
triggers a secondary sign; it does not expire its display. Retain an applicable
secondary until a newer applicable sign replaces or invalidates it. Numeric
speed changes alone do not dismiss an unrelated secondary warning.

The runtime implementation, rebuilt road database, executable test bundle and
current validation results are documented in
[the implementation record](MOBIDATA_BW_V1_5_IMPLEMENTATION.md).
The earlier **experimental data-contract pilot** remains a historical artifact:
its disabled proposals and failed readiness receipt are not the new runtime
bundle. v1.5 is the product branch; the road-bundle format remains v3. Existing
uncommitted inventory/Inspector/model-export work was preserved. New classifier
training and physical driving acceptance remain separate follow-up work.

## 1. Source assessment

The [publisher catalogue](https://mobidata-bw.de/dataset/verkehrszeichen-baden-wurttemberg)
links the [GeoJSON](https://mobidata-bw.de/daten/portal/VZ-Daten/signs.geojson).
A fresh download on 2026-10-21 has the same bytes as the 2026-10-20 import:

| Item | Verified value |
| --- | --- |
| FeatureCollection timestamp | `2026-10-17T22:00:00.013Z` |
| Bytes | 87,275,340 |
| SHA-256 | `cb4c89d3d2b18a06a1d5956b94865310929ff455d7a33005053bccaac66b79c3` |
| Records / literal codes | 163,504 / 53 |
| DE:310 / DE:311 | 13,788 / 9,312 |
| Coordinates | GeoJSON `[longitude, latitude]`, bbox `[7.520601,47.538214,10.444188,49.785871]` |
| Licence | Datenlizenz Deutschland – Namensnennung 2.0; retain publisher, licence URL and transformation notice |

Useful fields are exact sign code, point, group/support UUIDs, group ordering,
group orientation, municipality/ARS, source dates and OpenLR bytes/confidence.
There is no per-sign durable UUID: the existing canonical feature hash identifies
a record **within its snapshot**. A revision changing properties changes that
hash. Group ordering does not uniquely identify individual signs. A cross-revision
identity mapping must be explicit and must not silently merge co-located signs.

OpenLR is a location reference, not an OSM way ID. The catalogue says its initial
reference is the nearest road segment. Decode it against the same road graph,
validate direction and measure ambiguity before accepting an association.
`GruppenAusrichtung` must be validated against known road approaches before
deciding whether it means sign-face bearing or travel bearing; do not guess a
180-degree convention. Source confidence is not camera confidence.

The source contains **no DE:108/110 or DE:262–266 records** and no separate printed
restriction fields. Grade, tonnage and dimension support therefore needs future
source records or separately attributed camera/OCR evidence. Never invent values.
Supplementary plates may be incomplete: absence of a plate in this export does
not prove that a restriction is unconditional. The publisher describes the
inventory as incomplete and potentially outdated or incorrect. Keep that source
quality visible in diagnostics and retain evidence provenance.

Literal exceptions requiring explicit treatment:

- `DE:274-50[WVZ Rombachtunnel]`: preserve the suffix; a variable-message inventory
  record is not evidence of its currently displayed speed.
- `DE:331.2[]`: preserve the empty annotation and flag it for review.
- `DE:278`: no printed ended speed is supplied; do not fabricate one.
- `DE:222`, `DE:117-10`, `DE:142-10`, `DE:350-10`: map only through reviewed exact
  mappings/aliases and record any family-level artwork decision.

Full code counts and asset/model coverage are in
[the mapping audit](MOBIDATA_BW_PICTOGRAM_AUDIT_V1_5.md) and its JSON companion.

## 2. Current implementation and integration points

The existing `traffic_sign_source`, `traffic_sign_inventory` and R-tree tables
preserve raw source data and attribution with `usage_role=inventory_only`.
The Inspector reads the raw records. Both mobile apps now consume the separate,
optional `traffic_sign_capability.version=1` runtime tables. See
[the inventory record](MOBIDATA_BW_INVENTORY_2026-10-20.md).

| Concern | iPhone reference | Android parity target |
| --- | --- | --- |
| Road and settlement queries | `iphone/SpeedConsumerApp/V3SpeedLimitService.swift` | Android map DB/`SettlementContext.kt` |
| Secondary presentation | `TrafficSignPresentation.swift`, fed by `DriveSessionViewModel.swift` | `TrafficSignDisplay.kt`, `ConsumerSessionController.kt` |
| Complete city transition/reset | `DriveSessionViewModel.swift` city-boundary adapter | `ConsumerSessionController.kt` equivalent adapter |
| Camera passage action | `TrafficSignPassageEvaluation.swift` | corresponding passage evaluator |
| Visual sighting persistence | `SignCollectionObserver.swift`, collection store/schema | corresponding observer/store/schema |
| Capture modes/trigger arbitration | drive recording/Panoramax coordinator | equivalent capture coordinator |

The original secondary signs come from accepted camera classes/checkpoints, with
retention rules. Preserve the existing camera
flow and appearance. Inventory candidates use the same presentation surface
through a new explicit source adapter. Do not inject fictitious model classes or
OCR annotations into the existing camera stream. Inventory cards disappear when
their actual-distance gate fails; camera-only card retention remains unchanged.

The protected shared policy already supports `city_entry` / `city_exit`
invalidation. Existing high-confidence settlement controller transitions clear
camera and local/voice overrides. Camera `.cityEntry`/`.cityExit` passage actions
alone can retain zone/pedestrian layers, so they do not satisfy the requested
complete prior-limit reset. Use the full controller boundary path and validate
parity. The data bundle must never supply protected policy bytes or thresholds.
If implementation requires changing those semantics, create a new version and
approval lock under `shared/speed-limit-reference/AGENTS.md`, explicitly naming
the requested boundary behavior in the changelog and validating both controllers.

## 3. Production data contract

Keep independent inventory evidence separate from interpreted driving rules.
Retain the original OSM tags, geometry, existing settlement evidence and raw
source records. Build additional, versioned sign/rule/association tables; advertise
their capability explicitly in the manifest and database. Older clients must
ignore them. Production enablement requires a client version/capability gate;
adding tables cannot make the current apps consume them.

For each sign retain snapshot hash, source record key, group/support IDs, exact
code, normalized family, source annotation, original coordinates/orientation,
typed parameters, applicability conditions, selected artwork key, and review
status. Parameter shape is `{kind, value, unit, raw_text, source, status}`:

| Meaning | Canonical unit | Rule |
| --- | --- | --- |
| Posted maximum speed | `km/h` | Parse exact `DE:274-N`; static and qualified/dynamic records remain distinct |
| Decline / incline | `%` | Separate DE:108 and DE:110 families; retain direction and printed positive magnitude |
| Total / axle mass | `t` | Separate DE:262 and DE:263; decimal source values retained |
| Width / height / length | `m` | Separate DE:264, DE:265 and DE:266 |
| Unknown or missing | null | Preserve source text and an explicit unknown/invalid status |

Do not turn a generic classifier label such as `maxheight` into a specific
number. Restriction values belong beside the sign in the supplementary
presentation area with **inventory** provenance. They are not OCR results.
Use reviewed official artwork for the exact printed variant; until that exists,
show code/value text in diagnostics and keep the pictogram ineligible. Numeric
speed-limit rendering retains the existing schematic exception.

### Directed OSM integration

1. Search candidate ways spatially and project to the actual polyline, retaining
   segment index, local tangent, perpendicular distance and chainage. A way bbox
   or global average heading is insufficient on a bend.
2. Decode OpenLR and resolve direction, one-way/access constraints, junctions,
   lane/road separation and the validated orientation convention. Keep candidate
   evidence and rejection reasons. Nearest distance alone cannot accept a way.
3. Accept a directed link only after confidence/ambiguity validation. Preserve
   unresolved, parallel-road, opposite-face, tunnel and no-geometry cases.
4. Generate directed **applicability intervals** at sign stations. OSM base speed
   and inventory signs feed one resolver with explicit source priority/conflict
   diagnostics, rather than overwriting `ways.maxspeed` for an entire way.
5. A DE:310/311 station ends every speed offer from the previous traversal epoch,
   including camera and local/voice corrections. Mask previous-scoped OSM offers
   after the station even when both sides use the same OSM way ID. A fresh sign
   after the station can establish a new limit. A genuinely co-located fresh
   posted restriction needs deterministic ordering and explicit evidence.

The historical pilot deliberately stops at step 1. It records geometric candidates and
unknown direction; it does not claim OpenLR decoding or accepted associations.
Its `CHECK(enabled=0)` constraints are intentional. Production activation needs
a reviewed schema/capability migration rather than flipping these pilot rows.

## 4. Geofencing, presentation and town boundaries

Inventory ordinary secondary signs can first trigger only at measured distance
**≤10 m**. DE:310 and DE:311 use **≤30 m**. Do not expand the trigger radius by GPS
accuracy. Use a broader internal prefetch/arming window for responsiveness, while
keeping it separate from the encounter/capture gate and the rule's passage station.
After a qualified trigger, retain the secondary card outside the geofence and
through temporary GPS/camera/background gaps. Replace or invalidate it on an
accepted newer sign, applicable typed end/boundary, or a new drive/bundle/country
context. A numeric speed change alone does not invalidate an unrelated secondary.
The same presentation persistence applies to admitted camera secondary signs.

Ordinary secondary signs do not require an invented exact speed-way link.
However, accepted source associations supply a known sign travel heading:
`local_heading_deg + 180°` for direction `-1`, otherwise `local_heading_deg`.
Reject a clearly opposing face (>90° difference) when the actual vehicle heading
and its accuracy (0–35°) are valid. Unknown evidence remains explicitly unknown;
it does not become a verified association. Do not compare a held warning with a
distant later road bend and dismiss it merely because the road turned. Primary
speed/town evidence keeps its existing directed way and heading requirements.
Expose accuracy and fail closed for a stale fix, unresolved directed road link
or an inaccurate fix that cannot establish the correct road/direction.

A qualifying encounter requires the directed matched road, correct approach,
fresh source/fix and a unique association. Proximity alone must not apply a
boundary or restriction from a parallel road or opposite sign face. Evaluate
along-path progress to detect crossing; a 30 m circle can show/arm a town sign
before passage, but the context change takes effect at its accepted station.

DE:310 sets inside-city penalty context; DE:311 sets outside-city context.
Both invalidate all previous speed references through a single controller reset,
advance the traversal epoch, and obtain a fresh legal/default/map offer for the
new context. Town exit is not an unconditional 100 km/h or unlimited-speed
command. Keep the existing vehicle and road context resolver. These sign meanings
are described in [StVO Anlage 3](https://www.gesetze-im-internet.de/stvo_2013/anlage_3.html).

When the camera is off, accepted directional bundle evidence can still provide
geofenced display and boundary/map behavior; log `camera_off`. Camera availability
does not gate ordinary offline map behavior. Camera disagreement is retained
and does not silently rewrite the bundle. In ambiguous or invalid-association
cases, retain the existing fallback and log the unresolved encounter.

Use a deterministic presentation queue when several eligible signs share a
support. Keep actual camera detection, expected inventory sign and confirmation
status distinct. Do not label a registry sign “seen” because it appeared in the UI.
Re-arm only after leaving the encounter and starting a new directed traversal;
avoid GPS-edge flicker, duplicate reset and repeated captures. A U-turn requires
a fresh direction/face decision.

## 5. Camera confirmation and immutable local log

Reuse accepted camera tracks, confidence/temporal gates and existing durable
sighting events. Two distinct frames spanning at least 100 ms are the current
collection baseline. Do not lower those gates to improve registry matches.
An `inventory_sign_approach` event starts a bounded confirmation attempt only
when the camera and traffic-sign processing are already enabled. It schedules
association with processed frames through the existing inference budget; it
does not turn on the camera, change recognition thresholds or imply a sighting.
Match the actual class and printed value, timestamp, camera/GPS position and
accuracy, heading, directed way, sign station and unique candidate. A generic
family detection can establish only family-level evidence, never exact numeric
confirmation. Co-located same-class signs without a unique match remain ambiguous.

Add a versioned local `inventory_sign_encounter`/association log. Existing
collection schemas forbid arbitrary extra fields: link existing sighting IDs
through this new record instead of altering payloads implicitly. Each record has:

- encounter UUID, source ID/snapshot hash/record key, bundle DB hash/version;
- directed way/station/traversal epoch, source and matched coordinates,
  position time/accuracy, heading, entry/passage/exit times and gate reasons;
- expected exact code and typed parameters, observed class/value and parameter
  provenance, model/checkpoint/pack IDs, scores, track and supporting frame IDs;
- outcome, attempt interval, processed/dropped frame counts and diagnostic
  reason; linked durable sighting/capture IDs and capture result.

Outcomes: `camera_confirmed`, `camera_mismatch`, `not_observed`, `camera_off`,
`camera_unavailable`, `unsupported_model_class`, `ambiguous`. `not_observed`
requires a completed bounded analyzed attempt and does not prove physical absence.
An interrupted attempt is recorded as unavailable with its reason. Persist the
sighting and association transactionally or retain a retryable pending relation;
a failed write must not claim durable confirmation. Bundle changes mid-attempt
retain the original snapshot identity; do not relabel old evidence with new rows.

Keep the confirmation local by default. Images and uploads retain the existing
capture, consent, storage and network gates. No geofence-triggered upload or
camera activation is implied. Raw image evidence is optional under those gates;
metadata still records camera-off, unavailable and unsupported cases.

## 6. New capture trigger

Add an explicit selectable **inventory signs** trigger in the existing camera/
Panoramax capture settings on both platforms. It is an additional choice; retain
current defaults and distance/time/recognized-sign settings. Use a distinct
`captureReason=inventory_sign` and encounter UUID so it cannot be confused with
`recognized_sign` visual confirmation.

Make the automatic capture choices mutually exclusive: `cadence`,
`recognized_sign`, `inventory_sign`. Migrate the existing recognized-sign-only
boolean to `recognized_sign` when true and `cadence` when false. Preserve saved
distance/time cadence and thresholds when another choice is selected, and restore
them when returning to cadence. A new install still defaults to cadence/distance.
An already pending capture is committed or cancelled before changing modes;
one frame must not produce duplicate captures during that transition. Visual
confirmation logging remains independent of which capture mode is selected.

The trigger arms during an applicable sign approach and fires inside the 10 m /
30 m encounter under the existing active-camera, recording, movement, privacy,
storage and capture-rate gates. Prefer a usable actual sign frame when available;
a proximity-triggered frame is still only a capture attempt. It does not establish
that the sign was visible. At most one successful capture per sign/traversal;
coalesce multiple same-frame encounters and link all applicable encounter IDs.
Record skipped/throttled/refused/failed reasons. A failed capture or failed durable
commit does not consume the encounter and can retry while eligible. Camera-off
encounters are logged without activating the camera. Test conflict arbitration
with the existing recognized-sign trigger and its 2 s capture gap.

## 7. Artwork and model work

Use only shared `shared/tsr/sign-pictograms/originals/` SVG and `png/` transparent
renditions, with pinned source/licence/hash metadata and identical bytes in both
apps. The audit distinguishes exact artwork, reviewed family aliases, schematic
speed rendering and missing variants. Never generate replacement sign drawings
in platform code or use AI illustrations as official pictograms.

The six formerly missing source-code artworks have been acquired from reviewed
official-work sources, pinned and added to both apps' shared asset set.
Parameterized signs require correct official variants
or reviewed source parameter art; no made-up number in an existing asset. Update
selection/manifest/catalog, offline notices, app packaging and image regression
fixtures together. The historical pilot packages the then-existing mapped bytes and
records missing assets explicitly; it does not pretend that artwork adds model
outputs.

The pinned DE classifier has no town-entry/exit outputs. Numeric speed 90 and
other absent/family-only classes also need explicit treatment. Acquire attributed
real camera imagery for missing classes, DE:310/311, exact numeric restrictions
and challenging views. Keep source image/author/licence, complete reviewed boxes,
class/value/face labels and conservative site/sequence-grouped train/validation/
blind-test splits. Previously viewed/training/lecture examples cannot be called
blind evaluation. Existing town-sign Panoramax proposals are discovery material,
not accepted training labels. Test detector recall separately from classifier
accuracy and OCR value precision. Train/evaluate calibrated Swift/Core ML and
Android/LiteRT packs from the same source; publish no pack until per-class,
parameter, wrong-face and false-confirmation evidence passes review. Generic
classes remain `unsupported_model_class` for exact confirmation in the meantime.

## 8. Work packages and completion gates

| Order | Deliverable | Completion evidence |
| --- | --- | --- |
| A — complete | Source audit, 53-code mapping, full-BW inventory and additive data contract | Counts/hashes, typed parameters, candidate diagnostics, unchanged original road tags |
| B — implemented; field accuracy pending | OpenLR/orientation decoder and directed associations/intervals | Direction/parallel-road/continuation fixtures and contract gate; surveyed face/direction ground truth remains field acceptance |
| C — implemented | iPhone inventory adapter, geofence presentation and boundary integration | Actual simulator test receipt and full-bundle loading in implementation record |
| D — implemented | Android equivalent after iPhone reference inspection | Matching behavior/settings/capture/logs, unit and emulator acceptance receipts |
| E — implemented | Durable encounter log, camera association and new capture trigger | Camera-state, mismatch/ambiguity, frame/model consistency, persistence/capture retry tests |
| F — artwork complete; model work pending | Official missing art, attributed training imagery and evaluated model packs | All 117 shared asset pairs verified; new real imagery, training and measured visual recall remain outstanding |
| G — road rebuild complete; physical acceptance pending | Current road rebuild and attached-device acceptance | Structural and optional runtime gates pass; no live-camera physical drive claim |

Local simulator/emulator acceptance and packaging are part of this implementation.
The user subsequently authorized attached-device installation and drive review;
separate installation and drive-review receipts record those checks. No merge,
upload or release publication is authorized by this specification.

Required shared fixtures and controller tests for B–G:

1. 9.9/10/10.1 m ordinary and 29.9/30/30.1 m town encounters; prefetch cannot
   trigger a new card outside the actual radius. Test retained display after
   leaving, replacement, typed invalidation, context reset and camera parity.
2. Correct/incorrect direction and sign face, parallel roads, intersections,
   duplicate records, multi-sign supports, bends, tunnels, missing geometry,
   GPS jitter/poor accuracy/stale fix, leap across station and route reversal.
3. Static speed, qualified/dynamic speed, missing end-speed number, decimal
   percent/tonnes/metres, malformed values and unavailable supplementary plates.
4. Camera off/denied/unavailable, unsupported class, exact match, wrong number,
   family-only detection, ambiguous association, dropped/out-of-order frames,
   failed durable write, bundle revision during inference and encounter retry.
5. Prior map/camera/voice/posted/zone/pedestrian references at DE:310 and DE:311;
   reset exactly once, correct penalty context, same-way stale-offer suppression,
   and a new post-boundary limit accepted with a fresh epoch.
6. New capture mode setting/default parity, active camera gates, trigger collision,
   2 s rate limit, storage failure/retry, re-entry/U-turn and no camera activation
   or upload when disabled.

## 9. Local test-bundle record

See [the current implementation record](MOBIDATA_BW_V1_5_IMPLEMENTATION.md) for
runtime bundle paths, checksums, counts, artwork and acceptance results.
The road database has been rebuilt from the pinned September 13 OSM extract,
retaining exact source vertices, raw direction/lane tags, detailed road links,
paired corridors and complete settlement coverage. Its structural gate now
passes; this is not a claim of fresh October OSM data or physical driving accuracy.
The [older pilot receipt](MOBIDATA_BW_V1_5_TEST_BUNDLE.md) remains historical.
