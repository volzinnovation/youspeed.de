# Offline lane corpus and baseline

This workflow supports GitHub #10 and #21. It preserves the current phone lane
pipeline and prepares training inputs for an optional semantic-guidance model.
The optional A2D2 experiment below trains an offline marking head. It does not
export, integrate or deploy a phone model.

## Three separate evidence layers

1. **Source exposures:** hash-verified videos and aspect-preserving decoded frames,
   grouped by source/drive before splitting. Encoded PTS is not an inferred UTC,
   GPS or sensor timestamp.
2. **Weak training labels:** positive marking points supported by aligned future
   observations. Zero in a teacher PNG means **unknown**, not background. These
   labels do not establish ego-lane identity or road area. They cannot train a
   discriminative segmenter alone; use separately justified background/negative
   supervision as well.
3. **Evaluation annotations:** independently sourced semantic labels or reviewed
   paint intervals, kept distinct from predictions. Old Codex-reviewed images are
   developmental approximate annotations, not independent human acceptance truth.

Temporal agreement can reinforce stable signposts, gutters and road seams. The
2026-10-08 pilot demonstrated this directly. The unguarded bootstrap output is
quarantined for diagnosis. Optional reviewed-anchor propagation gives a smaller
set of semantically seeded weak labels; scoring against those same anchors is
circular and cannot establish accuracy. No annotation editor is required to run
this workflow. Static contact sheets support targeted QA.

## Restore and extract

Restore selected HF archive objects using the pinned revision and SHA-256 rules
in `AGENTS.md` and `docs/DEVICE_EVIDENCE_BACKUP_2026-10-01.md`. Keep all videos,
frames, public dataset originals and generated labels outside the repository.

`prime_video_corpus.py` accepts this configuration shape:

```json
{
  "sources": {
    "drive-a": {
      "path": "/absolute/path/verified-video.mov",
      "sha256": "64-character-source-sha256",
      "driveGroup": "verified-drive-or-conservative-route-group",
      "split": "development",
      "provenance": {"dataset": "loffenauer/youspeed.de", "revision": "pinned-revision", "remotePath": "manifest-object-path"}
    }
  },
  "clips": [{"id": "drive-a-01", "source": "drive-a", "start": 10, "end": 20, "tags": ["unreviewed"]}]
}
```

```sh
python3 scripts/lanes/prime_video_corpus.py \
  --config "$LANE_CORPUS_ROOT/prime-config.json" \
  --output-dir "$LANE_CORPUS_ROOT/primed" --fps 10
```

Requires Python 3.9+, NumPy, OpenCV and a working ffprobe. Source hashes are
checked before decoding. The extractor validates actual PTS and orientation,
rejects overlapping aliases and cross-split source/content/drive groups, and
reports skipped sampling targets on variable-frame-rate recordings. It preserves
every selected RGB frame by default, raw gray replay inputs, transforms, hashes
and original metadata. Output directories must be new; a failed extraction has
`failure.json` and no successful `manifest.json`. Unknown geography is not an
independent holdout merely because clip IDs differ.

Default `--pts-mode packets` inventories original packet timestamps in presentation
order and verifies the selected decoded images against them. It does not claim a
full-video decode integrity scan. `--pts-mode decoded` performs that more expensive
scan when needed. Neither mode fabricates frames to fill recording gaps.

## Freeze the native baseline and teacher-seed experiment

```sh
python3 scripts/lanes/replay_recorded_pipeline.py \
  --manifest "$LANE_CORPUS_ROOT/primed/manifest.json" \
  --output-dir "$LANE_CORPUS_ROOT/baseline" --preview-mode --variant baseline

python3 scripts/lanes/replay_recorded_pipeline.py \
  --manifest "$LANE_CORPUS_ROOT/primed/manifest.json" \
  --output-dir "$LANE_CORPUS_ROOT/teacher-seeds" \
  --reuse-build-dir "$LANE_CORPUS_ROOT/baseline" \
  --preview-mode --group-fragments --variant teacher-observed-fragments
```

The baseline leaves all experimental options off. The second replay is a
separate offline source of explicit observed paint segments. It never enables
fragment grouping in either phone app. Native `rawBoundaries` are **pre-presentation,
post-temporal** hypotheses, not every detector ridge candidate. The ordinary
baseline emits no explicit `observedSegments`; fitted whole curves must not be
silently substituted for observed paint when building labels.

## Generate and audit retrospective labels

```sh
python3 scripts/lanes/retrospective_teacher.py \
  --replay-dir "$LANE_CORPUS_ROOT/teacher-seeds" \
  --baseline-replay-dir "$LANE_CORPUS_ROOT/baseline" \
  --bootstrap-from-baseline \
  --output-dir "$LANE_CORPUS_ROOT/teacher-candidates"
```

The default horizon is 0.5 seconds. Each positive requires current target-image
ridge evidence, explicit fresh/fused source paint, forward/backward and
photometric flow checks, and at least two distinct future exposures. Correlated
exposures are not statistically independent votes. Sequence, split, source,
orientation and excessive timestamp gaps stop propagation. No target detector
hypothesis is required. Dash gaps and unsupported pixels stay unknown.

- Add `--mode causal` for the same/past-only comparison.
- Add `--reviewed-anchor-labels labels.json` to require a nearby flow-verified
  reviewed painted anchor as well. This guard does not increase temporal votes.
- Use `--seed-labels labels.json` instead of bootstrap for reviewed-only seeding;
  sparse review frames can legitimately yield no labels under the two-future-
  exposure requirement.
- Reviewed records require `id`, `sequenceId`, `time`, `split` and `inputSha256`,
  plus explicit `paintedYIntervals`. Bind old labels using verified frame identity;
  never infer their identity from a reused filename.

Outputs include positive/unknown masks, per-point contributing frame and segment
IDs, offsets, residuals, guard provenance, code/config/input hashes and coverage
summaries. `student-inputs.json` contains target-only inputs. Future/support
metadata belongs to label generation, never the deployable student's input.

```sh
python3 scripts/lanes/audit_teacher_labels.py \
  --teacher-dir "$LANE_CORPUS_ROOT/teacher-candidates" \
  --labels "$LANE_CORPUS_ROOT/reviewed-development-labels.json" \
  --negative-intervals "$LANE_CORPUS_ROOT/reviewed-development-negative-labels.json" \
  --output-dir "$LANE_CORPUS_ROOT/teacher-audit"
```

The audit verifies artifact bytes and bindings, reports sparse reviewed-border
support and dense negative duration separately, and writes static QA sheets.
Point totals are correlated pixels, not independent observations or confidence
interval denominators. Inspect high-consensus errors as well as uncertain cases.

## Public semantic baseline

`a2d2_baseline.py prepare` consumes a pinned source manifest with `pairs[]`
(`sequence`, `rgb`, `label`) and `objects[]` (`key`, `local_path`, `sha256`).
The pilot uses original, aligned distorted A2D2 RGB/label pairs. Solid and dashed
line classes are distinct from driving instructions and zebra crossings.
Full images retain aspect ratio; thin class occupancy is preserved by any-area
pooling, with that approximation explicitly recorded.

```sh
python3 scripts/lanes/a2d2_baseline.py prepare \
  --source-manifest "$LANE_CORPUS_ROOT/public-a2d2/manifest.json" \
  --output-dir "$LANE_CORPUS_ROOT/a2d2-prepared"
# Run replay_recorded_pipeline.py on a2d2-prepared/manifest.json as above.
python3 scripts/lanes/a2d2_baseline.py score \
  --targets "$LANE_CORPUS_ROOT/a2d2-prepared/targets.json" \
  --replay "$LANE_CORPUS_ROOT/baseline-a2d2/frames.ndjson" \
  --output "$LANE_CORPUS_ROOT/baseline-a2d2/paint-support.json"
```

Each annotated still resets temporal state. Scoring uses pre-presentation paint
geometry and reports centerline support/paint coverage in a fixed ROI with an
explicit tolerance. It is not official lane F1, ego-lane recall, an unbiased
benchmark, or future-teacher validation. Empty-target samples remain included.

Official sources: [A2D2](https://a2d2-dataset.github.io/),
[public mirror](https://registry.opendata.aws/aev-a2d2/),
[class map](https://audi-autonomous-driving-dataset.s3.eu-central-1.amazonaws.com/camera_lidar_semantic/class_list.json),
[dataset license](https://audi-autonomous-driving-dataset.s3.eu-central-1.amazonaws.com/LICENSE).
Preserve source license and attribution with downloaded originals. The pilot's
derived dataset artifacts are local and are not redistributed.

## A2D2-only auxiliary marking experiment

`fetch_a2d2_subset.py` first plans an exact bounded download, then restores original
public objects. The default pilot selects 128 training, 32 validation and 32 test
front-center images, with complete recording dates assigned to one split and at
least 10 seconds between selected timestamps. Previously inspected smoke dates
belong to training. Date separation does not prove route independence. Source
ETags, available MD5 checks, SHA-256 hashes, paired geometry and license files are
preserved. Outputs must remain outside this repository.

```sh
python3 scripts/lanes/fetch_a2d2_subset.py plan --output "$LANE_CORPUS_ROOT/a2d2-plan.json"
python3 scripts/lanes/fetch_a2d2_subset.py fetch \
  --plan "$LANE_CORPUS_ROOT/a2d2-plan.json" \
  --output-dir "$LANE_CORPUS_ROOT/a2d2-originals"
```

`train_a2d2_auxiliary.py` uses the pinned source checkpoint behind the deployed
sign/plate/face **box detector**, not the country sign classifier. The entire
detector and its batch-normalization state are frozen. A new 3,457-parameter head
uses P2/P3 image features to predict one foreground class: solid or dashed marking.
Known other classes provide background; unknown colors, blurred/rain/ego regions
and letterbox padding are ignored. No private footage or retrospective labels
enter training or checkpoint selection. The downstream supervised data is A2D2
only; the original pretrained detector retains its earlier training history.

Use an isolated Python environment with PyTorch, OpenCV, NumPy and
`ultralytics==8.4.56`. The pilot used PyTorch 2.8.0 on Mac MPS. Download the
[pinned original detector](https://raw.githubusercontent.com/cquest/sgblur/169451970702aca0dde9ff3106dba0f67e0b88a8/models/yolo11n_panoramax.pt)
outside the repository; the trainer enforces SHA-256
`698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a`.

```sh
python3 scripts/lanes/train_a2d2_auxiliary.py \
  --manifest "$LANE_CORPUS_ROOT/a2d2-originals/manifest.json" \
  --detector "$LANE_CORPUS_ROOT/yolo11n_panoramax.pt" \
  --output-dir "$LANE_CORPUS_ROOT/auxiliary-run" --device mps --epochs 15
```

Full images are letterboxed to 640 square with exact aligned label transforms.
The loss combines train-only class-weighted BCE and Dice. A fixed 0.5 threshold
and validation marking IoU select the checkpoint; the test split is scored after
selection. Metrics are micro-averaged pixels at the resized input resolution,
not lane-instance metrics. Frozen detector tensor hashes and an identical-input
output probe must match before and after. This does not replace exported-model
or end-to-end TSR regression tests.

`evaluate_auxiliary_video.py` applies the selected head independently to each
hash-bound RGB exposure. It reverses letterboxing, saves scores/masks, checks
chronological prefix invariance, and reports sparse reviewed-paint support and
dense known-negative ROI errors separately. Sparse approximate border reviews
cannot measure dense paint IoU or precision. Scores have not been calibrated.

```sh
python3 scripts/lanes/evaluate_auxiliary_video.py \
  --manifest "$LANE_CORPUS_ROOT/reviewed-rgb/manifest.json" \
  --checkpoint "$LANE_CORPUS_ROOT/auxiliary-run/auxiliary-marking.pt" \
  --detector "$LANE_CORPUS_ROOT/yolo11n_panoramax.pt" \
  --labels "$LANE_CORPUS_ROOT/reviewed-development-labels.json" \
  --negative-labels "$LANE_CORPUS_ROOT/reviewed-development-negative-labels.json" \
  --output-dir "$LANE_CORPUS_ROOT/auxiliary-video" --device mps
```

A2D2's labeled images are non-sequential: this learns paint appearance, not video
tracking. P2/P3 features and this tiny head also have limited semantic context.
The existing geometric and temporal lane recognizer remains responsible for
lane selection. Actual sharing needs a full-scene input contract while preserving
the shipped 1280-pixel detector's sign detail and calibrated crop behavior.
Core ML/LiteRT export, paired phone measurements, hint fusion and uncertainty
handling remain separate steps. No speed-reference semantics are changed.

## ZOD import and matched source comparison

`prepare_zod_lane_corpus.py` adds a bounded ZOD Frames importer. Use original
blurred RGB, official train/val information, lane JSON and capture metadata from
the same release. Preserve the producer license and download checksums outside
Git. Its official info loader still needs an end-to-end check on an acquired
official archive; the annotation parser has been checked on actual legacy JSON.
The public resized mirror is currently useful for schema fixtures only: its
image transform and grouped split provenance have not been established.

The source receipt is JSON with `schemaVersion: 1`, `dataset: "ZOD"`,
`license: "CC BY-SA 4.0"`, `source_revision`, `source_url`,
`geometry: "original-pixel-polygons"`, `annotation_coverage`, and
`coverage_evidence`. Set coverage to `unknown` until verified; only
`complete_lane_markings` permits background supervision. Record the verified
archive revision/hash and supporting producer documentation, not placeholders.

```sh
python3 scripts/lanes/prepare_zod_lane_corpus.py \
  --dataset-root "$LANE_CORPUS_ROOT/zod/originals" \
  --trainval "$LANE_CORPUS_ROOT/zod/originals/trainval-frames-mini.json" \
  --source-receipt "$LANE_CORPUS_ROOT/zod/source-receipt.json" \
  --output-dir "$LANE_CORPUS_ROOT/zod/prepared"
```

Solid/dashed polygons become paint; separate dashes are never joined. Other road
paint, raised markers, shaded merges and uncertain annotations are ignored.
Rasterize in original coordinates before the trainer's aligned letterbox.
Missing annotations, unknown classes or malformed polygons never imply negative
paint. Strict import stops on malformed annotations; optional
`--quarantine-invalid-annotations` excludes entire affected frames with hashes
and reasons. Report resulting scores as corpus-filtered.

Official ZOD validation remains a final holdout, named `test` in the local
manifest. Frames sharing a collection vehicle/day or locations within 250m form
connected groups. Training components touching the official holdout are excluded.
These safeguards do not prove complete route independence. A mini can have too
few remaining groups for training; do not split a drive to manufacture a holdout.

```sh
python3 scripts/lanes/train_mixed_auxiliary.py \
  --a2d2-manifest "$LANE_CORPUS_ROOT/public-a2d2-pilot-192/manifest.json" \
  --zod-manifest "$LANE_CORPUS_ROOT/zod/prepared/manifest.json" \
  --detector "$LANE_CORPUS_ROOT/a2d2-training/yolo11n_panoramax.pt" \
  --output-dir "$LANE_CORPUS_ROOT/zod/comparison-001" --device mps
```

The two arms start with identical random heads, the same frozen detector, and
15 epochs ×16 updates ×8 frames. Baseline batches contain eight A2D2 frames;
mixed batches contain four from each source, cycling seeded permutations.
Both use fixed BCE weight20, threshold0.5, and earliest-best **A2D2 validation**
IoU to choose a checkpoint. ZOD holdouts are scored only afterward. This tests
source composition under equal compute; the mixture halves A2D2 exposure.
Report source-specific metrics, unique frames and repeated exposures separately.
Private videos stay inference-only. All prior A2D2 test exposure remains disclosed.

The protocol is saved before optimization. Loadable checkpoints are written only
after detector tensor/file hashes and an identical-input output probe pass; the
proof is embedded in each checkpoint. No mobile model is exported. Cached
features/targets take roughly13.1MB per640-pixel frame; the default512-frame
per-source cap is a memory guard, not a dataset selection rule.

## Tests and next decision

Run the corpus tests with NumPy, OpenCV and pytest installed:

```sh
python3 -m pytest -q tests/test_prime_video_corpus.py \
  tests/test_lane_a2d2_baseline.py tests/lanes/test_retrospective_teacher.py \
  tests/lanes/test_audit_teacher_labels.py tests/lanes/test_fetch_a2d2_subset.py \
  tests/lanes/test_evaluate_auxiliary_video.py
```

Run the training checks in the isolated training environment:

```sh
python3 -m unittest discover -s tests/lanes -p test_train_a2d2_auxiliary.py -v
python3 -m unittest discover -s tests/lanes -p test_prepare_zod_lane_corpus.py -v
python3 -m unittest discover -s tests/lanes -p test_train_mixed_auxiliary.py -v
```

The next gate is independent teacher quality and selection-opportunity evidence,
not simply more stable output. Keep #10 open for independently adjudicated
sequence truth, route/drive separation and the existing sign-applicability
requirements. Phone export, guidance integration, performance and adoption remain
later work in #22–#24; an offline trained head does not complete those gates.
