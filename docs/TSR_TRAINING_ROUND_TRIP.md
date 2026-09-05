# Traffic-Sign Recognition Training Round Trip

Date: `2026-09-05`

Status: implementation foundation; no model is approved for release yet

## Outcome

YouSpeed's live mobile lane trains traffic-sign recognition for primary traffic
signs. One shared camera frame produces:

1. one or more `primary_sign` proposals,
2. a primary semantic such as `maximum_speed = 30 km/h`,
3. temporal evidence for a physical-sign track, and
4. a normalized primary action for the live passage state machine.

That same contract is used for live inference, consented diagnostic capture,
human review, training, replay, and mobile evaluation. Supplementary signs are
explicitly outside this live contract: the app does not detect, group, OCR, or
interpret them. They will use a separate offline-first workflow over
Panoramax-linkable full-scene evidence, manual annotation, and optionally a
vision-language model. Shared schemas may retain supplementary fields for
backward compatibility, but live events leave them empty.

## Reproducible source baseline

[`training-sources-v1.json`](../shared/tsr/training-sources-v1.json) is the
machine-readable authority for source revisions, checkpoint hashes, licenses,
and release gates. A training run records the manifest's own SHA-256 and only
uses inputs selected from it.

| Input | Pinned identity | Intended use | License / release posture |
| --- | --- | --- | --- |
| [ZOD Frames](https://zod.zenseact.com/) | requested dataset `2.0.0` (confirm after provider access); devkit `0.8.0@601a3ef5cfccad9cc545230362077d299acbf898` | Real European full-frame proposals, hard negatives, and scene robustness; use only frames whose Traffic Signs annotation task is present and complete | CC BY-SA 4.0; attribution/share-alike review is mandatory. The publisher exposes no stable aggregate archive hash, so a sorted local SHA-256 file inventory is mandatory. |
| [GTSIGN-220](https://huggingface.co/datasets/miriamcarnot/GTSIGN-220) | commit `e235536c26486a42858602b146df40520a75be59` | Real German primary and supplementary crops; semantic teacher | CC BY-SA 4.0; attribution/share-alike review is mandatory. Snapshot only the pinned commit and record a selected-file SHA-256 inventory. |
| [Panoramax classified German road signs](https://huggingface.co/datasets/Panoramax/classified_de_road_signs) | commit `b4856947ed7cb6312587258acc90e8cf88a4aa13`; pinned `train.zip` and `val.zip` hashes in the manifest | Crop-classification bootstrap data and reproduction of the published comparison | CC BY-SA 4.0. The published split is not an acceptance set: the legacy filename audit reports 1,297 overlapping source IDs and byte hashing finds 522 validation images in training. Rebuild grouped splits. |
| [Synset Signset Germany](https://synset.de/datasets/synset-signset-ger/) | DOI `10.35097/dcc1znjxu7apx8rn`; RADAR version-1 TAR size `17,149,598,208` bytes; published archive MD5 `373656812a1d57a899f8289c340544b8` | Synthetic primary/plate variation, metadata-driven assemblies, robustness tests | CC BY 4.0; attribution review is mandatory. MD5 identifies the publisher archive but is not collision-resistant, so add an archive SHA-256 and extracted-file inventory locally. |
| GTSIGN-220 ViT teacher | repository commit above; SHA-256 `e84304a7bbb2a1677c9f4ff9e330262969f1d598da456c8dbe290489bb301bad` | Offline teacher, label audit, and distillation reference | CC BY-SA 4.0 lineage review. Its repository-reported evaluation is not a YouSpeed field-validation result and cannot approve a mobile release. |
| [Panoramax German classifier](https://huggingface.co/Panoramax/classify_de_road_signs) | commit `5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790`; SHA-256 `f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7` | Required third-party crop-classifier baseline | The model card says Etalab-2.0 and declares YOLO26 plus the Panoramax crop dataset. Release is blocked until both dataset CC BY-SA treatment and Ultralytics AGPL/Enterprise obligations are approved. Its self-reported 98.6% is unverified and comes from the leaky split, so it is not acceptance evidence. |
| [timm MobileNetV3 Large](https://huggingface.co/timm/mobilenetv3_large_100.ra_in1k) / [Small](https://huggingface.co/timm/mobilenetv3_small_100.lamb_in1k) | commits `96f46a1c52932f27492dff66c72378eb99b443a7` / `1824797e7887cbec1990e4adbd6675960a36c589`; exact safetensors hashes in the manifest | Preferred classifier-student initializations for owned training | Official cards declare Apache-2.0 and ImageNet-1k. They remain initialization-only pending pretrained-weight, ImageNet lineage, and NOTICE review. |
| [YOLOX Nano](https://github.com/Megvii-BaseDetection/YOLOX) | `0.1.1rc0@e1052df71842031413f6030723c3607b839c80ce`; SHA-256 `cd28f55fbbc1829f99d9ac9b38a16d259a22889739c8728ea877610201feff7b` | Proposal-detector control before traffic-sign transfer learning | The repository code is Apache-2.0, but release of the COCO-pretrained weight remains blocked until the weight license, COCO lineage, license/NOTICE obligations, and fine-tuning inputs are explicitly reviewed. |
| [YOLO26n](https://docs.ultralytics.com/models/yolo26/) and YOLO26n-cls | Ultralytics/assets `v8.4.0@dcececebff9fe00420c144baa5cd25a641d10aa6`; SHA-256 `9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef` and `0dd6f8dbc448870ac98a3cbb7156f923f7ce21fed3755d4019169ffffd279e81` | Detection/classification challengers for technical comparison | Release-blocked by default. Use in a shipped derivative only after an explicit AGPL-3.0 compliance decision or confirmation of an applicable [Ultralytics Enterprise license](https://www.ultralytics.com/license). |

ZOD supplies real scene context; Synset and GTSIGN supply German semantic
coverage. None is sufficient by itself. Public checkpoint metrics are triage
signals, not production evidence.

## Model-selection decision

[`model-selection-v1.json`](../shared/tsr/model-selection-v1.json) records the
architecture decision without pretending that a trained model has passed. The
target candidate architecture is a YOLOX-Nano-derived `640x640` primary-sign
proposal detector followed by a MobileNetV3-Large `224x224` primary-label
classifier and temporal primary-sign tracking.
MobileNetV3-Small is the latency challenger. A direct semantic YOLOX-Nano
detector is the active iPhone field-test baseline while the two-component
primary-only runtime is evaluated.

This is an architecture target, not a claim that the detector training corpus
is ready. ZOD's traffic-sign taxonomy still needs an audited primary-sign label
mapping. Reviewed YouSpeed primary annotations and hard negatives must be
frozen before proposal training. Crop datasets alone cannot establish
full-scene primary-sign proposal coverage or recall.

RF-DETR Nano and D-FINE-N remain conversion challengers, not selected models;
their exact checkpoints and Core ML/LiteRT parity are not pinned. The pinned
Panoramax YOLO26 classifier is an external ground-truth-crop benchmark only.
It cannot establish proposal recall, assembly quality, full-scene precision,
or mobile runtime readiness. The pinned GTSIGN-220 ViT is the second actual
third-party crop-classification benchmark and optional teacher required by
issue #2; it remains offline-only until its taxonomy adapter and leakage-safe
comparison report exist.

```sh
python3 scripts/tsr/model_selection.py status
python3 scripts/tsr/model_selection.py evaluate EVALUATION.json
```

`EVALUATION.json` is the root of a local evidence bundle. Every scored JSON
section, training/holdout manifest, model/runtime artifact, and device
attestation uses a safe bundle-relative path and declared SHA-256. The evaluator
rejects traversal and symlinks, recomputes hashes without deserializing model
bytes, and requires scored JSON fields to equal their referenced payloads.
Those bundle-declared hashes establish integrity, not trust. Holdout and parity
corpora must also match independently approved hashes in the model-selection
registry. Those pins are currently unset, so their gates remain blocked even
when a self-consistent evidence bundle is supplied.

Training and calibration dataset bundles also bind their source IDs and any
applicable source-manifest artifact references. The evaluator derives the
license posture from the union of the candidate's model lineage and the
datasets actually used by that run; approving only the model initialization
cannot hide a CC-BY or CC-BY-SA training-data obligation.

Every trained component also attests its checkpoint, ONNX, Core ML, and LiteRT
formats. Those canonical artifact roles must use globally distinct evidence
paths and SHA-256 values, so one opaque file cannot impersonate every runtime
format. Device evidence remains pending until a registry revision pins exact
tier/platform/hardware-model/OS-build/app-build-SHA profiles; device
attestations additionally bind the benchmark run and device instance.

The evaluator then computes an internal engineering scorecard from those bound
counts and measurements, never from a self-reported summary metric. It is
read-only and never
changes `selected_candidate_id`; the registry intentionally keeps that field
null until a separate human product process selects an eligible artifact. Even
a fully passing model scorecard would not approve a
production release: privacy verification, legal approval, signed distribution,
app-level override lifecycle, and product safety acceptance remain separate.
Duplicate-confirmation and wrong-way-confirmation thresholds are intentionally
pending; field data, not an invented number, must establish them.

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

# Pinned Panoramax comparison data/model and MobileNetV3 student initializations.
python3 scripts/tsr/bootstrap_sources.py show \
  panoramax-de-train-b485694 \
  panoramax-de-validation-b485694 \
  panoramax-de-yolo26-classifier-5360aa6 \
  mobilenetv3-large-ra-in1k-96f46a1 \
  mobilenetv3-small-lamb-in1k-1824797
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

# Reproduce the known published-split leakage against the exact pinned bytes.
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

`show`, `download`, and `verify` require exact artifact IDs. There is no
download-all mode. Paths must remain below the selected root, redirects are
restricted to declared HTTPS hosts, byte counts are bounded by the manifest,
and a download is atomically installed only after its hash passes. The
pickle-capable `.pt` and `.pth` files still require an isolated conversion
environment later; verification does not make deserialization safe.

The `1,297` check deliberately reproduces the historical audit convention:
remove a leading `DE_` from each filename stem and remove the final character
as the crop discriminator. It is retained so issue #2 remains reproducible;
it is not a general UUID parser. The `522` check independently streams and
SHA-256-hashes every image member without extracting or decoding the archive.
Both results demonstrate that the published validation split is unsuitable
for selection or acceptance.

## Capture and review loop

Ordinary TSR inference retains no pixels. Training and test material enters a
separate diagnostic store only after explicit `tsr_diagnostic_dataset`
consent. A bundle carries a retention expiry and a second export approval.
Expired bundles are rejected. Raw Dashcam video and direct device identifiers
are never accepted. The live TSR lane does not run face or vehicle-number-plate
detection. Any separate public-image privacy workflow belongs to the image
publisher, not the TSR model.

For a candidate, uncertainty sample, or hard negative, keep only the bounded
high-resolution source frame/primary crops needed for review and record
synchronized:

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
positive live-training sample they correct the primary bounding box and primary
semantic. Low-confidence proposals, false confirmations, sign-like advertising,
signs on adjacent roads, damaged signs, night glare, rain, and motion blur are
valuable hard negatives.

Supplementary-sign review is a separate offline dataset and ticket. It starts
from the Panoramax image/link and full-scene evidence, then uses manual
annotation or an optional vision-language model. Its output cannot alter the
live TSR decision in this implementation phase.

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
For GTSIGN-220, ignore the supplied split for YouSpeed release evaluation and
first group crops by the Mapillary source-image identifier encoded before the
first underscore in each filename. For YouSpeed captures,
`capture_group_id` represents at least the drive/import session.

The current materializer deterministically keeps one `capture_group_id` in one
split. It does not yet discover the same physical sign across different drives
or compute near-duplicate image clusters. Before any release build, a separate
pre-split grouping audit must merge those encounters using route corridor, UTC
day, physical-sign cluster, data origin, and pseudonymous device tier, then
prove there is no physical-sign or near-duplicate overlap. Until that audit is
implemented and passes, the leakage release gate remains blocked.

The release evaluation set is geographically and temporally held out. It must
include devices, focal lengths, seasons, lighting, weather, construction signs,
and difficult primary-sign backgrounds that are absent from threshold fitting. Synthetic
variants may augment training and robustness suites, but never inflate the
reported real-route result. The frozen test set is not recycled for error
mining; corrected field failures enter the next version's training or a new
regression set.

## Transfer-learning recipe

1. **Freeze provenance.** Validate the source manifest, snapshot selected
   dataset files, create SHA-256 inventories, record label mappings, and approve
   the applicable license gates. A run with different bytes gets a new run ID.
2. **Train the primary-sign proposal detector.** Initialize the license-gated
   control from YOLOX Nano, replace COCO classes with `primary_sign`, and train
   on ZOD plus reviewed YouSpeed full frames. First audit and freeze the ZOD
   primary-sign label mapping. Bind reviewed full-scene YouSpeed primary boxes
   and hard-negative inventories to the run.
   Preserve background-only frames only from ZOD frames for which the Traffic
   Signs annotation task is present and complete; an unannotated frame is not a
   negative. Benchmark a YOLO26n branch only as the license-gated challenger.
3. **Train the primary-label classifier.** Initialize the owned
   MobileNetV3 Large or Small student from its pinned safetensors checkpoint,
   optionally distill from the pinned GTSIGN teacher, and compare primary-crop
   results against the pinned Panoramax classifier. Train primary semantics from
   leakage-regrouped Panoramax/GTSIGN crops, Synset speed classes, and reviewed
   YouSpeed crops. Keep numeric speed, zone, and end semantics distinct.
4. **Track physical primary signs.** Start a fresh tracker namespace with each
   recording/camera-processing session. Reuse one physical-track UUID for
   semantically compatible sightings across the frame instead of requiring
   consecutive bounding-box IoU.
5. **Mine failures.** Run the candidate over new consented drives. Prioritize
   uncertain predictions, model disagreement, false temporal
   confirmations, rare primary speed values, and route-held-out errors.
   Review them before they can re-enter training.
6. **Fine-tune and distill.** Unfreeze progressively, use class-balanced
   sampling and realistic small-object/blur/exposure augmentation, and stop on
   the untouched validation groups. Record seeds, framework/container digests,
   optimizer schedule, all input inventories, and the exact parent checkpoint.

## Calibration, export, and parity

Fit release calibration after model selection, using a dedicated calibration
partition. Calibrate primary semantics and temporal confirmation separately.
Thresholds belong in the model pack. During physical-device field testing,
missing device-local calibration metadata is recorded but does not disable an
otherwise compatible primary-sign pack.

Export each frozen component checkpoint through a pinned conversion
environment. The mobile formats are siblings of the reference export, not
descendants that must pass through ONNX:

```text
frozen detector checkpoint   -> reference ONNX
                            \ -> Core ML detector
                             \-> LiteRT detector

frozen classifier checkpoint -> reference ONNX
                            \ -> Core ML classifier
                             \-> LiteRT classifier
```

The training run records ONNX opset, converter versions, preprocessing,
quantization/calibration data, input/output tensor contracts, class mapping,
and SHA-256 for every intermediate and mobile artifact. The same
orientation-normalized release corpus is then replayed through desktop ONNX,
iOS Core ML, and Android LiteRT. The signed pack contains the source-manifest
hash, dataset-inventory hashes, training run ID, calibration parameters,
evaluation report hash, parity report, exporter identity, and mobile artifact
hashes.

## Internal model-scorecard gates

These are engineering comparison gates for an internal model-pack candidate.
Changing a numeric threshold requires a versioned evaluation decision, not an
informal field-test adjustment. The evaluator can check evidence bindings and
declared gate status; it cannot grant legal approval or approve a production
release.

| Gate | Pass condition |
| --- | --- |
| Provenance | Source manifest validates; every selected artifact and dataset inventory matches; the complete lineage is recorded. |
| License posture | Every required model and actual training/calibration dataset lineage gate is explicitly asserted to the evaluator by the review process. This is an engineering blocker only, not a legal determination or proof embedded in the model evidence bundle. The YOLOX and MobileNetV3 initializations remain blocked until their pretrained-weight/data lineage and NOTICE obligations are documented; the Panoramax classifier additionally requires both CC BY-SA dataset treatment and an explicit Ultralytics AGPL-compliance or Enterprise-license decision. |
| Leakage | The materializer's capture-group split passes, and a separate pre-split audit demonstrates zero physical-sign-cluster or near-duplicate overlap between train, calibration, validation, and test partitions. |
| Primary semantics | On the real route holdout, the lower 95% confidence bound is at least 99% for confirmed numeric-limit precision and 90% for recall; dangerous speed substitutions are at most 0.1%. |
| Supplementary boundary | Live output contains no supplementary detections, restrictions, OCR results, or grouped members. Offline supplementary evaluation is tracked separately and cannot gate live activation. |
| Temporal evidence | Replay produces at most one confirmed event per physical assembly and satisfies versioned duplicate-confirmation and wrong-way-confirmation thresholds. Those thresholds are currently pending, so this gate remains blocked. |
| Calibration | Expected calibration error is at most 0.03 on the calibration audit set, with per-class reliability plots and no threshold fitted on the held-out test set. |
| Cross-runtime parity | Every scorecard-case normalized semantic and assembly state agrees across ONNX/Core ML/LiteRT; matched boxes have IoU at least 0.995 and calibrated confidence differs by at most 0.02. |
| Device performance | Exact approved tier profiles must be registry-pinned; they are currently unset, so this gate is pending. Each pinned tier records at least 3,600 coherent detector/end-to-end inferences over at least 30 minutes: the shared camera continues delivering at least 15 frames/s while TSR samples it at a sustained adaptive 2–10 Hz. Detector/end-to-end p95 stay under 250 ms, peak TSR memory under 256 MB, dropped frames at most 1%, backpressure events at most 0.1%, exactly one inference is in flight, and thermal downshift does not affect recording. |
| Field regression | Required day/night/weather/construction/adjacent-road suites pass, and every previously accepted dangerous failure remains a named regression case. |

Precision gates apply to the confirmed primary-sign passage, not just a cropped
classifier. If the available holdout is too small for the confidence bound, the
gate is not met; collecting more independent routes is the remedy.

Separate production approvals remain mandatory and are deliberately outside
this scorecard: consent/retention and image-redaction verification; legal review
of all lineage; signed pack distribution; app-level precedence and override
invalidation; Dashcam/TSR/Panoramax failure isolation; and final product-safety
acceptance on supported devices.

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
