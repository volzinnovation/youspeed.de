# Traffic-Sign Recognition Training Round Trip

Date: `2026-09-01`

Status: implementation foundation; no model is approved for release yet

## Outcome

YouSpeed trains traffic-sign recognition as a compositional perception system,
not as one flat class list. One shared camera frame produces:

1. proposals for a `primary_sign` and zero or more
   `supplementary_plate` objects,
2. a primary semantic such as `maximum_speed = 30 km/h`,
3. typed restrictions such as `weather = wet`, `vehicle = truck`, or a time
   window, and
4. an assembly that links every plate to its primary sign.

That same contract is used for live inference, consented diagnostic capture,
human review, training, replay, and mobile evaluation. A reviewed detection
therefore makes a complete round trip instead of becoming an app-specific log
that cannot improve the next model.

## Reproducible source baseline

[`training-sources-v1.json`](../shared/tsr/training-sources-v1.json) is the
machine-readable authority for source revisions, checkpoint hashes, licenses,
and release gates. A training run records the manifest's own SHA-256 and only
uses inputs selected from it.

| Input | Pinned identity | Intended use | License / release posture |
| --- | --- | --- | --- |
| [ZOD Frames](https://zod.zenseact.com/) | dataset `2.0.0`; devkit `0.8.0@601a3ef5cfccad9cc545230362077d299acbf898` | Real European full-frame proposals, hard negatives, and scene robustness | CC BY-SA 4.0; attribution/share-alike review is mandatory. The publisher exposes no stable aggregate archive hash, so a sorted local SHA-256 file inventory is mandatory. |
| [GTSIGN-220](https://huggingface.co/datasets/miriamcarnot/GTSIGN-220) | commit `e235536c26486a42858602b146df40520a75be59` | Real German primary and supplementary crops; semantic teacher | CC BY-SA 4.0; attribution/share-alike review is mandatory. Snapshot only the pinned commit and record a selected-file SHA-256 inventory. |
| [Synset Signset Germany](https://synset.de/datasets/synset-signset-ger/) | DOI `10.35097/dcc1znjxu7apx8rn`; published archive MD5 `373656812a1d57a899f8289c340544b8` | Synthetic primary/plate variation, metadata-driven assemblies, robustness tests | CC BY 4.0; attribution review is mandatory. MD5 identifies the publisher archive but is not collision-resistant, so add an archive SHA-256 and extracted-file inventory locally. |
| GTSIGN-220 ViT teacher | repository commit above; SHA-256 `e84304a7bbb2a1677c9f4ff9e330262969f1d598da456c8dbe290489bb301bad` | Offline teacher, label audit, and distillation reference | CC BY-SA 4.0 lineage review. Its repository-reported evaluation is not a YouSpeed field-validation result and cannot approve a mobile release. |
| [YOLOX Nano](https://github.com/Megvii-BaseDetection/YOLOX) | `0.1.1rc0@e1052df71842031413f6030723c3607b839c80ce`; SHA-256 `cd28f55fbbc1829f99d9ac9b38a16d259a22889739c8728ea877610201feff7b` | Apache-2.0 proposal-detector control before traffic-sign transfer learning | Permissive control, subject to Apache license/NOTICE review and the licenses of its fine-tuning data. |
| [YOLO26n](https://docs.ultralytics.com/models/yolo26/) and YOLO26n-cls | Ultralytics/assets `v8.4.0@dcececebff9fe00420c144baa5cd25a641d10aa6`; SHA-256 `9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef` and `0dd6f8dbc448870ac98a3cbb7156f923f7ce21fed3755d4019169ffffd279e81` | Detection/classification challengers for technical comparison | Release-blocked by default. Use in a shipped derivative only after an explicit AGPL-3.0 compliance decision or confirmation of an applicable [Ultralytics Enterprise license](https://www.ultralytics.com/license). |

ZOD supplies real scene context; Synset and GTSIGN supply German semantic
coverage. None is sufficient by itself. Public checkpoint metrics are triage
signals, not production evidence.

### Bootstrap commands

The bootstrap utility treats checkpoints as opaque bytes. It never imports
pickle, PyTorch, Ultralytics, or another model runtime.

```sh
python3 scripts/tsr/bootstrap_sources.py validate
python3 scripts/tsr/bootstrap_sources.py show yolox-nano-coco-0.1.1rc0
python3 scripts/tsr/bootstrap_sources.py download \
  --root tsr-data/bootstrap \
  yolox-nano-coco-0.1.1rc0
python3 scripts/tsr/bootstrap_sources.py verify \
  --root tsr-data/bootstrap \
  yolox-nano-coco-0.1.1rc0
```

`show`, `download`, and `verify` require exact artifact IDs. There is no
download-all mode. Paths must remain below the selected root, redirects are
restricted to declared HTTPS hosts, byte counts are bounded by the manifest,
and a download is atomically installed only after its hash passes. The
pickle-capable `.pt` and `.pth` files still require an isolated conversion
environment later; verification does not make deserialization safe.

## Capture and review loop

Ordinary TSR inference retains no pixels. Training and test material enters a
separate diagnostic store only after explicit `tsr_diagnostic_dataset`
consent. A bundle carries a retention expiry and a second export approval.
Full frames need verified face/license-plate redaction before export. Raw
Dashcam video and direct device identifiers are never accepted.

For a candidate, uncertainty sample, or hard negative, keep only the bounded
high-resolution source frame/crops needed for review and record synchronized:

- current OSM way ID,
- latitude and longitude,
- heading and forward/reverse travel direction,
- map-context revision and stable map/local source signature,
- active model pack and preprocessing version, and
- detector/classifier predictions before review.

This context explains which transient detection overrode which bundled OSM or
local correction during replay. It is evidence, not permission to persist an
automatic map correction.

Reviewers can accept, correct, reject, or mark a sample negative. For each
positive assembly they correct:

- the primary and plate bounding boxes,
- the primary speed semantic,
- every plate's typed restriction and optional country sign code,
- plate-to-primary relationships, and
- `condition_state` as `none`, `resolved`, or `unresolved`.

A visible but unreadable plate must remain `unresolved`; it must not silently
turn a conditional limit into an unconditional one. Low-confidence proposals,
false confirmations, sign-like advertising, signs on adjacent roads, damaged
signs, night glare, rain, and motion blur are valuable hard negatives.

Validate and materialize only approved bundles:

```sh
python3 scripts/tsr/diagnostic_dataset.py validate --for-export BUNDLE
python3 scripts/tsr/diagnostic_dataset.py build \
  --output tsr-data/generated/roundtrip-v1 \
  --seed youspeed-tsr-split-v1 \
  BUNDLE...
```

## Leakage-safe dataset construction

Assign groups before augmentation, teacher inference, or tuning. Every frame,
crop, burst, and repeat view from one physical encounter stays in one split.
`capture_group_id` should represent at least the drive/import session; the
dataset inventory additionally records route corridor, UTC day, physical sign
cluster, data origin, and a pseudonymous device tier. Near-duplicate hashes are
checked across groups.

The release evaluation set is geographically and temporally held out. It must
include devices, focal lengths, seasons, lighting, weather, construction signs,
and supplementary plates that are absent from threshold fitting. Synthetic
variants may augment training and robustness suites, but never inflate the
reported real-route result. The frozen test set is not recycled for error
mining; corrected field failures enter the next version's training or a new
regression set.

## Transfer-learning recipe

1. **Freeze provenance.** Validate the source manifest, snapshot selected
   dataset files, create SHA-256 inventories, record label mappings, and approve
   the applicable license gates. A run with different bytes gets a new run ID.
2. **Train the two-role proposal detector.** Initialize the permissive control
   from YOLOX Nano, replace COCO classes with `primary_sign` and
   `supplementary_plate`, and train on ZOD plus reviewed YouSpeed full frames.
   Preserve background-only frames. Benchmark a YOLO26n branch only as the
   license-gated challenger.
3. **Train the primary classifier.** Transfer from the pinned GTSIGN teacher or
   distill it into a license-approved mobile student. Combine real GTSIGN crops,
   Synset speed classes, and reviewed high-resolution YouSpeed crops. Keep
   numeric speed, zone, and end semantics distinct.
4. **Train the supplementary classifier.** Use the Synset upper/lower metadata,
   GTSIGN restriction crops, and reviewed device crops. Predict typed semantics
   such as weather, time, vehicle, resident, school, exception, distance,
   direction, extent, text, other, and unknown—not every primary/plate
   combination as a new class.
5. **Link the assembly.** Start with deterministic geometry: compatible plate
   below/near a primary, same temporal track, and one-parent ownership. Train a
   lightweight linker only if reviewed data demonstrates that geometry is not
   sufficient. Keep unresolved plates observable.
6. **Mine failures.** Run the candidate in shadow mode over new consented
   drives. Prioritize uncertain predictions, model disagreement, false temporal
   confirmations, rare speed values/restrictions, and route-held-out errors.
   Review them before they can re-enter training.
7. **Fine-tune and distill.** Unfreeze progressively, use class-balanced
   sampling and realistic small-object/blur/exposure augmentation, and stop on
   the untouched validation groups. Record seeds, framework/container digests,
   optimizer schedule, all input inventories, and the exact parent checkpoint.

## Calibration, export, and parity

Fit calibration only after model selection, using a dedicated calibration
partition. Calibrate primary semantics, plate presence, typed restrictions, and
the temporal confirmation score separately. Thresholds are part of the model
pack, not hard-coded in either app.

Export one frozen training result through a pinned conversion environment:

```text
frozen student -> canonical ONNX -> Core ML
                              \-> LiteRT/TFLite
```

The training run records ONNX opset, converter versions, preprocessing,
quantization/calibration data, input/output tensor contracts, class mapping,
and SHA-256 for every intermediate and mobile artifact. The same
orientation-normalized release corpus is then replayed through desktop ONNX,
iOS Core ML, and Android LiteRT. The signed pack contains the source-manifest
hash, dataset-inventory hashes, training run ID, calibration parameters,
evaluation report hash, parity report, exporter identity, and mobile artifact
hashes.

## Release gates

These are initial safety gates for an internal model-pack candidate. Changing a
numeric threshold requires a versioned evaluation decision, not an informal
field-test adjustment.

| Gate | Pass condition |
| --- | --- |
| Provenance | Source manifest validates; every selected artifact and dataset inventory matches; the complete lineage is recorded. |
| Licensing | Every lineage gate is approved. Any YOLO26 derivative remains blocked absent an explicit AGPL-compliance or Enterprise-license decision. |
| Privacy | Every YouSpeed sample has valid consent/retention metadata; exported full frames have verified redaction; no raw Dashcam video or direct device ID is present. |
| Leakage | Zero capture-group, physical-sign-cluster, or near-duplicate overlap between train, calibration, validation, and test partitions. |
| Primary semantics | On the real route holdout, the lower 95% confidence bound for confirmed numeric-limit precision is at least 99%; dangerous speed substitutions are at most 0.1%. |
| Restrictions | The lower 95% confidence bound for resolved restriction precision is at least 98%; a detected but unresolved plate never becomes an unconditional limit. |
| Temporal behavior | At most one confirmed event per physical assembly; newer detections replace older detections; a stable map/local signature does not clear an override; genuinely new OSM/local source information does. |
| Calibration | Expected calibration error is at most 0.03 on the calibration audit set, with per-class reliability plots and no threshold fitted on the release test set. |
| Cross-runtime parity | Every release-case normalized semantic and assembly state agrees across ONNX/Core ML/LiteRT; matched boxes have IoU at least 0.995 and calibrated confidence differs by at most 0.02. |
| Device performance | On each supported device tier, p95 inference fits its declared adaptive 2–10 FPS interval, only one inference is in flight, memory remains bounded, and serious thermal/low-power state downshifts without affecting recording. |
| Field regression | Required day/night/weather/construction/adjacent-road suites pass, and every previously accepted dangerous failure remains a named regression case. |

Precision gates apply to the full confirmed assembly, not just a cropped sign
classifier. If the available holdout is too small for the confidence bound, the
gate is not met; collecting more independent routes is the remedy.

## Versioned improvement cycle

Each released pack starts a new shadow-data cycle:

```text
on-device candidates
  -> consented bounded capture
  -> redaction and human review
  -> immutable grouped dataset version
  -> transfer learning and calibration
  -> held-out evaluation and mobile parity
  -> signed model pack
  -> shadow rollout, then gated transient override
```

Model, data, calibration, and runtime policy versions remain separate. This
lets YouSpeed revert one component, compare challengers fairly, and explain any
transient speed-limit override from the captured way ID, coordinate, heading,
direction, source signature, and signed model lineage.
