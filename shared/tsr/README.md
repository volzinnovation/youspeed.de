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
  but the two-component proposal/classification target requires a v2 event
  that binds detector and classifier lineage independently.
- Every live provisional/confirmed event carries the way ID, coordinate,
  heading, travel direction, and OSM/local source signature captured with the
  frame. An asynchronous result is rejected for runtime override if that
  signature is no longer current.
- A confirmed unconditional numeric result is a transient source with
  precedence `TSR > local correction > bundled OSM`. It never mutates the
  lower layers, survives repeated fixes with the same source signature, and is
  cleared by a newer detection or genuinely new OSM/local information. Until
  an applicability evaluator exists, a newer conditional/unresolved assembly
  clears the old camera override but does not create a new active limit.
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
runtimes are blocked. The target's detector data is also blocked until the ZOD
taxonomy is audited for separate supplementary-plate boxes or an alternative
reviewed full-scene plate-box inventory is frozen; crop datasets cannot satisfy
that proposal-coverage requirement.

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
