# YouSpeed traffic-sign recognition contracts

This directory defines the portable boundary between the YouSpeed training and
release pipeline and the iOS/Android runtimes. Model binaries do not belong in
the normal source tree. A released country pack is a directory containing a
`manifest.json` plus the explicitly listed artifacts.

The runtime rules are deliberately strict:

- National model labels are mapped to `tsr-semantic-v1`; app logic never
  switches on a German training class ID.
- Every mobile artifact identifies the pinned source checkpoint, exporter,
  preprocessing and output contracts, calibration input, parity result, and
  SHA-256.
- The committed `recognition-event-v1` contract covers the direct
  single-component shadow lane. Live frames, rear-camera stills, and imported
  diagnostic fixtures must normalize to the same semantic evidence contract,
  while `recognition-event-v2.schema.json` covers the two-component
  proposal/classification shadow target and binds detector and classifier
  artifact, preprocessing, and calibration identities independently.
- Every live per-frame event carries its capture-time road context and TSR
  generation as immutable evidence. A visible or armed sign never changes the
  main speed. Only a generation-current `traffic-sign-passage-event-v1`,
  finalized after qualified visual loss, may reach the runtime resolver or
  observation store.
- A finalized applicable passage has precedence
  `TSR > local correction > bundled OSM`. It survives repeated fixes on its
  original way and continuous way-ID changes only within the narrowing
  intersection of original `route_relation_connected` groups. It is held
  through a bounded no-match gap and cleared on an unrelated way, reversal,
  bundle switch, drive stop, or TSR disable. Refreshing the local store after
  persisting that same camera event is not new road evidence and must not clear
  the active camera assertion.
- Primary signs and white supplementary plates are separate objects linked by
  an assembly ID. `resolving`/`unresolved` plate state must not be collapsed
  into an unconditional permanent speed correction.
- Bounding boxes use the fully orientation-normalized image, top-left origin,
  and normalized `[0, 1]` coordinates.
- `raw_score` is never presented as probability. `calibrated_confidence` is
  present only when the pack declares a passing calibration.
- Ordinary inference events contain no pixels or image path. Diagnostic image
  retention is a separate consented feature and storage root.
- Downloaded packs require a trusted signature in addition to per-artifact
  hashes. Bundled/developer packs may be admitted by a separate explicit trust
  policy, but are still hash checked.
- The current iOS integration therefore rejects Application Support packs in
  production. An unsigned integrity-checked pack is admitted only from the
  explicit `YOUSPEED_TSR_MODEL_PACK_DIR` environment override in a DEBUG build;
  Android remains unavailable until its verified-pack boundary is implemented.

`fixtures/de-direct-pack-v1.json` and `fixtures/recognition-events-v1.json` are
contract fixtures, not release manifests or benchmark ground truth. Their hash
values are intentionally synthetic and no model artifact is implied.

## Finalized passage and structural-action contracts

The passage layer is additive. The frozen per-frame `taxonomy-v2.json` and
`recognition-event-v2.schema.json` remain unchanged and shadow-only:

- `structural-action-taxonomy-v1.json` versions the Germany-first actions used
  after physical-sign assembly: numeric and zone limits, city and pedestrian
  zone boundaries, distinct maximum-speed/all-restriction ends, motorway and
  motorroad exits, and temporary limits. German city entry resolves to 50
  km/h. Non-speed restriction ends are explicit hard negatives and cannot emit
  a speed passage.
- `traffic-sign-passage-event-v1.schema.json` is the only shared contract that
  can describe an actionable camera passage. It requires a live,
  override-eligible, calibrated pack; a stable finalized-event id and TSR
  generation; separate raw, calibrated, frame-fused, and accumulated track
  evidence; qualified analyzed-missing frames; and immutable first-missing
  boundary data separate from a later bounded same-scope activation/rematch.
  It also carries the original relation groups and source relation IDs needed
  to prevent transitive relation hopping.
- Structural action, resolved presentation, normalized OSM operation,
  persisted-row runtime applicability, and export eligibility are separate
  fields. A resolved permanent observation may participate in the local
  runtime layer immediately as `local_only`, but it is never export-approved at
  commit. An unresolved, conditional, temporary, or unsafe observation starts
  `needs_review` with `runtime_applicable = false`. An unresolved end masks the
  stale live camera value, presents `unknown`, stores review evidence, and has
  no OSC operation.
- `fixtures/traffic-sign-passage-events-v1.json` and
  `fixtures/passage-reducer-scenarios-v1.json` are golden cross-platform replay
  data. They cover repeated sightings followed by the first qualified miss,
  dropout/reappearance without a commit, German city entry, and resolved plus
  unresolved speed-limit ends. The scenario fixture pins the supplied
  Panoramax picture, annotation, sequence, and URL provenance; its model and
  bundle hashes are synthetic contract values, not release artifacts.

Skipped, throttled, invalid, failed, interrupted, disabled, stopped, and
thermal-paused frames are not visual negatives. Reappearance before calibrated
loss debounce completes returns a track to `armed` without emitting or
persisting anything. Current shadow or uncalibrated packs cannot satisfy the
passage schema and therefore cannot override a speed limit.

## M0 two-stage shadow contracts

The additive v2 contracts preserve every v1 consumer:

- `model-pack-v2.schema.json` requires a YOLOX-style proposal stage and a
  role-aware classifier stage with independent preprocessing and calibration.
  Each stage carries distinct checkpoint, ONNX, Core ML, and LiteRT sibling
  identities. The v2 M0 policy is hard-coded to shadow mode and is not eligible
  for a speed override.
- `recognition-event-v2.schema.json` emits QA evidence without pixels. An
  unreadable supplementary plate may retain raw classifier scores for mining,
  while Apple Vision OCR/rectangle helpers are identified separately as
  auxiliary evidence and never attributed to either model stage. Candidate OCR
  text/restrictions stay auxiliary until calibrated model evidence establishes
  readability; the modeled plate cannot carry a class or restriction. A later calibrated readable
  observation may upgrade the same physical-sign track without rewriting the
  earlier event. `evidence_origin` separates real runtime inference from
  reviewed expectations; expectation fixtures have uninvoked stages and null
  scores, so ground truth cannot masquerade as a successful model run.
- `taxonomy-v2.json` freezes the two proposal roles, numeric speed semantics,
  typed white-plate restrictions, per-frame unreadable semantics, and the
  offline-only GTSIGN teacher and Panoramax crop-benchmark roles.
- `full-scene-annotation-v2.schema.json` requires separate primary and
  supplementary pixel boxes, assembly links, drive identity, and physical-sign
  identity. `group-split-v2.schema.json` assigns connected components over
  drive, physical sign, and supplied near-duplicate clusters to exactly one of
  train, calibration, or holdout.

The published Panoramax classifier validation split is explicitly prohibited
from all three partitions. `zod-supplementary-plate-audit-v1.json` records that
the pinned ZOD devkit has no auditable supplementary-plate class or assembly
link; ZOD is therefore usable only for reviewed primary scenes and complete-task
hard negatives. Proposal training remains blocked until reviewed YouSpeed or
reviewed synthetic full-scene plate boxes are frozen.

`fixtures/panoramax-m0-round-trip-v2.json` binds the two public full-resolution
field-test frames, their hashes, reviewed boxes, road context, and temporal
acceptance rule. The earlier frame contains a readable 70 sign and a visible but
unreadable white plate, so its restriction is null. Only the later readable
frame establishes an `extent` of 2,000 metres for the same physical sign. The
reviewed labels are fixture truth, not a claim that a trained model produced
those outputs. `fixtures/panoramax-m0-full-scene-annotations-v2.json` is the
schema-valid frozen annotation view, while `fixtures/recognition-events-v2.json`
is the corresponding reviewed expectation view for replay and inspector QA.
`fixtures/de-yolox-mnv3-shadow-pack-v2.json` likewise contains synthetic hashes
and one-byte sizes solely to exercise the pack contract.

`diagnostic-bundle.schema.json` defines the separate, consented image round
trip. Ordinary inference never writes frames into that storage root. The
dataset builder verifies unexpired consent, redaction state, asset hashes, road
context, assembly links, and deterministic capture-group
train/validation/test splitting before materializing anything for training. A
separate release audit must still merge repeated physical-sign encounters and
reject near-duplicate leakage across capture groups.

## Pinned classifier bootstrap baseline

`training-sources-v1.json` pins the official Panoramax German crop dataset at
`b4856947ed7cb6312587258acc90e8cf88a4aa13`, its YOLO26 classifier at
`5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790`, and the official timm MobileNetV3
Large/Small safetensors initializations. The Panoramax model is a required
third-party crop-level comparison, not the YouSpeed mobile model. Its reported
98.6% is unverified and uses a split with known source-ID and byte-identical
leakage, so it cannot satisfy an acceptance gate. Release of that checkpoint or
a derivative remains blocked by the combined dataset CC-BY-SA and Ultralytics
AGPL/Enterprise review; the MobileNet initializations remain blocked pending
pretrained-weight/ImageNet lineage and NOTICE review.

Fetch only explicitly selected, pinned artifacts and verify their bytes:

```sh
python3 scripts/tsr/bootstrap_sources.py validate
python3 scripts/tsr/bootstrap_sources.py download \
  --root tsr-data/bootstrap \
  panoramax-de-train-b485694 \
  panoramax-de-validation-b485694 \
  panoramax-de-yolo26-classifier-5360aa6 \
  mobilenetv3-large-ra-in1k-96f46a1 \
  mobilenetv3-small-lamb-in1k-1824797
python3 scripts/tsr/bootstrap_sources.py verify \
  --root tsr-data/bootstrap \
  panoramax-de-train-b485694 \
  panoramax-de-validation-b485694 \
  panoramax-de-yolo26-classifier-5360aa6 \
  mobilenetv3-large-ra-in1k-96f46a1 \
  mobilenetv3-small-lamb-in1k-1824797
```

The bootstrapper treats `.pt` as opaque, pickle-capable bytes and never loads
it. Any later conversion must run in an isolated, reproducible environment.

Reproduce the published-split leakage only after the two pinned archives have
passed bootstrap verification:

```sh
python3 scripts/tsr/audit_panoramax_split.py \
  --train tsr-data/bootstrap/datasets/panoramax/classified-de-road-signs/b485694/train.zip \
  --val tsr-data/bootstrap/datasets/panoramax/classified-de-road-signs/b485694/val.zip \
  --expect-train-bytes 59887779 \
  --expect-val-bytes 29740678 \
  --expect-train-sha256 0a7cc5895afd76a4dc98e70efc9421ae82a6f580e6d60da3904911155e424853 \
  --expect-val-sha256 13ca882129a4e024fc865fc4a3187514a4554f8e323f612e338144fd1ff189ea \
  --expect-train-images 13287 \
  --expect-val-images 6944 \
  --expect-source-overlap 1297 \
  --expect-exact-val-in-train 522
```

The source-overlap assertion preserves the historical filename convention
(remove `DE_`, then the final crop-discriminator character); it is not a
general source UUID parser. Exact-image overlap is independently computed from
streamed member SHA-256 values. The tool validates the ZIP layout and never
extracts or decodes its members.

## Model selection

`model-selection-v1.json` records the current target—YOLOX-Nano two-role
proposals plus MobileNetV3-Large crop semantics—alongside the direct iPhone
shadow lane, MobileNetV3-Small latency challenger, unpinned detector
challengers, and the Panoramax plus GTSIGN-220 ViT external crop benchmarks.
It intentionally contains no selected candidate while required evidence and
runtimes are blocked. The pinned ZOD audit found no auditable separate
supplementary-plate boxes, so ZOD cannot satisfy that detector-label
requirement. The target and controlled MobileNetV3-Small challenger remain
blocked until a reviewed YouSpeed or reviewed synthetic full-scene plate-box
inventory is frozen; crop datasets cannot satisfy proposal coverage.

```sh
python3 scripts/tsr/model_selection.py status
python3 scripts/tsr/model_selection.py evaluate EVALUATION.json
```

`model-evaluation.schema.json` describes a local evidence bundle rooted beside
the evaluation JSON. Training and holdout manifests, scored JSON reports,
model/runtime artifacts, and device attestations use safe relative paths and
SHA-256. The selector rejects traversal/symlinks, recomputes every referenced
hash, requires scored fields to match their referenced JSON payloads, and never
deserializes model checkpoints. It then derives confidence bounds, calibration
error, parity, size, latency, runtime-safety, and leakage gates without mutating
the registry. Bundle-declared hashes prove internal integrity only. Holdout and
parity corpora must additionally match independently approved hashes in the
registry; those pins are intentionally unset, so replacing and rehashing a
corpus cannot make either gate pass. Duplicate- and wrong-way-confirmation acceptance rates remain
versioned-policy blockers until field evidence supports thresholds.
Training and calibration bundles enumerate their dataset `source_ids` and
applicable `artifact_refs`; the evaluator derives license gates from those
actual run inputs as well as from the candidate's model components. A run
cannot pass by approving only the YOLOX/MobileNet code and weight gates while
omitting its CC-licensed training data.
Each trained component attests the checkpoint, ONNX, Core ML, and LiteRT
formats, and those canonical artifact slots must be globally distinct by path
and SHA-256. Approved device-tier profiles are likewise unset by default; a
later registry revision must pin exact platform, hardware model, OS build, and
app-build SHA-256 values before device evidence can pass. Thermal/recording
attestations also bind the benchmark run and physical device identity.
Its result is an internal engineering model scorecard only. It cannot approve
privacy handling, legal obligations, signed distribution, app-level override
lifecycle, or production release; those remain independent fail-closed reviews.
