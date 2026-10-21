# SGBlur YOLO26s dashcam replay — 20 October 2026

**Keep YOLO11n in both apps for now.** At the current 1024 input size, the compatible YOLO26s head finds 14/48 reviewed sign instances versus 17/48 for YOLO11n and takes about 1.9× the Mac CPU prediction time. It produces 0 scored nuisance proposals versus 1, but this small assistant-labeled review does not establish app false-alert rates. The separate default end-to-end head check finds 13/48 and does not improve on YOLO11n's hit count in this review. The earlier still-image recall gain alone is insufficient reason to replace the bundled model.

## Archive contents and restored sources

The private [HF dataset](https://huggingface.co/datasets/loffenauer/youspeed.de/tree/bd12056313e00acc790d25ebe5486aac11f4cf79)
contains the original copied dashcam evidence. Both restore manifests downloaded
from revision `bd12056313e00acc790d25ebe5486aac11f4cf79` are byte-identical to the
retained local records. There are 679 logical source records, 567 remote object
paths and 566 distinct content hashes: one object is duplicated across batches.
Of these, 60 distinct content objects are MOV/MP4 files, totaling 28,614,539,682
bytes. This is an inventory of video objects, including short review clips and
test recordings, not 60 distinct complete drives.

The inspected dataset HEAD, `b8fedbbbc3676e9a580178143cde30fd8f17c539`, lists 678
files, including 69 movie files. The nine movie paths outside the backup prefixes
are lane-mapping inputs/results under `experiments/lingbot-map/`, not nine new
original drives. The evaluation uses the pinned verified backup revision.

Three complete recordings were selected before inference:

| Cohort | Duration | Upright source | Decoder orientation metadata | Requested 2 Hz samples |
| --- | ---: | ---: | ---: | ---: |
| iPhone daytime | 9:22.24 | 3840 × 2160 | 180° | 1,124 |
| Android dawn | 13:06.18 | 1280 × 720 | 0° | 1,572 |
| Android sunset | 9:19.03 | 1280 × 720 | 0° | 1,118 |
| Total | 31:47.44 | | | 3,814 |

The footage includes wet roads, motion blur, headlamp-lit forest curves, village
streets and motorway approaches. Dawn is not a complete nighttime test. One
known interrupted Android recording with a missing `moov` atom was excluded
using the existing [recording audit](LANE_ANDROID_LOG_AUDIT_2026-10-01.md).

The three selected remote objects' LFS SHA-256 and sizes match their manifest
records. Local full-file SHA-256 values were checked before decoding. Two
existing verified restores from the 8 October lane corpus were reused; only
the sunset movie was freshly downloaded. All restored movies and the persistent
replay output remain outside the repository, under
`/Users/raphaelvolz/YouSpeedDeviceBackups/`. Object paths, hashes, sizes and
manifest hashes are in the [portable evidence](sgblur-yolo26-dashcam-2026-10-20.evidence.json).

## Fixed comparison and blind review

Both models receive identical upright pixels. OpenCV applies rotation metadata
once, resizes proportionally to height 1024 and retains the rightmost 1024
columns, with RGB-114 left padding for narrow inputs. This approximates the
current mobile geometry; it does not establish bit-exact native rendering parity.
Inference uses the pinned original checkpoints, `imgsz=1024`, `rect=false`,
confidence 0.25, NMS IoU 0.7, `max_det=300`, the one-to-many head
(`end2end=false`) and four Mac CPU threads. The model execution order alternates
per frame after three synthetic warmups. No thresholds or country classifiers
were tuned to the videos.

The 0.25 threshold matches the current packs' unknown threshold. This is a
PyTorch detector comparison, not a replay of either app's complete pipeline:
Android uses sign-score decoding, NMS IoU 0.45 and at most 12 proposals, and
iPhone uses its Core ML/Vision pipeline. Classification, OCR, tracking,
calibration and the speed-reference state machine are not exercised here.

Source-only frames were extracted every ten seconds. The fixed scoring subset
starts at zero and samples every 30 seconds: **65 frames, 48 eligible sign
instances**. These are repeated sightings, not necessarily 48 distinct physical
signs. All 65 frames were visually reviewed before opening detector outputs.
The assistant's labels were frozen at 20:33:38 UTC with SHA-256:

```text
bc85cbb5a16867bdaf37696aa80d7d1bad0543e68c7ef210f0a27411a80a0821
```

[The frozen labels](sgblur-yolo26-dashcam-2026-10-20.labels.json) define the scope:
recognizable front faces with a shorter box edge of at least 20 pixels, including
direction, parking, bus-stop, supplementary and hazard panels. Separate physical
panels count separately. Backs, clipped faces, ambiguous and tiny signs have
explicit ignore regions. Commercial graphics, road lights, delineator posts and
vehicle decals are background. Matching is confidence-sorted, one-to-one at IoU
0.5. After matching, proposals below 20 pixels or overlapping an explicit ignore
region by at least half their area are outside scoring. IoU 0.3 is reported as
an annotation/localization sensitivity check without changing model thresholds.

These are assistant annotations, not independently reviewed human ground truth.
The scorer verifies the frozen annotation hash, image hashes, identical
prediction-window hashes, the exact scoring-frame set and complete sample grid.
Only these 65 frames support the precision/recall figures below. Raw proposal
counts across all 3,814 frames do not measure accuracy or app false alerts.

## Results on the fixed 65 frames

| Detector / head | Found / 48 | Missed | Scored false proposals | Precision¹ | Recall¹ | F1¹ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| YOLO11n one-to-many | 17 | 31 | 1 | 94.4% | 35.4% | 0.515 |
| YOLO26s compatible one-to-many | 14 | 34 | 0 | 100.0% | 29.2% | 0.452 |
| YOLO26s default end-to-end² | 13 | 35 | 0 | 100.0% | 27.1% | 0.426 |

¹ Scoped to eligible faces and the frozen ignore rules above; not mAP, independent human validation or a phone/application metric.
² Same 65 image pixels and labels, executed separately after the full replay. No additional annotation or threshold tuning.

| Cohort | Labeled instances | YOLO11n found | YOLO26s compatible found | YOLO26s default found |
| --- | ---: | ---: | ---: | ---: |
| iphone_day | 11 | 7 | 6 | 6 |
| android_dawn | 26 | 5 | 3 | 3 |
| android_sunset | 11 | 5 | 5 | 4 |

The compatible candidate retains 13 baseline hits, gains 1 and loses 4; both miss 30 labeled instances. This review deliberately includes rectangular direction and supplementary faces, not just speed-limit circles. The shared label name `sign` does not prove identical upstream training taxonomy or data coverage.

Lowering matching IoU to 0.3 leaves all three hit and false-proposal counts unchanged. The default end-to-end head loses the parking/car face at sunset 180 s that the compatible head finds, and adds no hit on this fixed review.

### Disagreements and nearby-frame checks

Compatible-head disagreements at matching IoU 0.5:

- `iphone_day-0510000`: wet-road supplementary panel; YOLO11n only.
- `android_dawn-0150000`: left curve chevron; YOLO11n only.
- `android_dawn-0300000`: priority-road diamond; YOLO26s only.
- `android_dawn-0390000`: 30 speed limit; YOLO11n only.
- `android_dawn-0780000`: priority-road diamond; YOLO11n only.

The iPhone wet-road supplementary face at 510 s and the dawn chevron at 150 s were visually checked against both outputs. These are real fixed-frame misses at the chosen threshold, rather than slightly mismatched box boundaries. However, post-hoc neighboring frames show YOLO26s detecting the wet-road panel at 506 s (score about 0.45) and a chevron at 150.5 s (about 0.48), plus a clipped chevron at 149.5 s (about 0.35). They must not be described as fully missed sign encounters. These selected neighboring frames are qualitative evidence outside the frozen headline metrics.

The scored baseline-only nuisance proposal on iPhone frame 420 s surrounds part of a bridge structure at the left edge. Tiny signs, excluded backs and clipped targets are not silently counted as false proposals. Both models miss the large Loffenau town-entry face in the dawn 270 s keyframe. The sample is too small and correlated to establish an error rate for town signs or numeric speed signs.

### Prediction time and complete replay

| Model | Prediction median | Prediction p95 | Timed frames |
| --- | ---: | ---: | ---: |
| yolo11n compatible head | 68.02 ms | 102.21 ms | 3,814 |
| yolo26s compatible head | 128.49 ms | 172.23 ms | 3,814 |

These are wall times around Python `predict`, including its preprocessing and postprocessing, excluding decoder seek/decode, crop/resize, file writing and app classification/OCR. The shared Mac’s background load was not controlled. They are not inference-only, phone, thermal or RAM measurements. The default end-to-end head was checked in a separate 65-frame quality run and has no comparable full-replay latency measurement.

All 3,814 planned samples completed; the scorer rejects missing or duplicate sample IDs. Decoder-reported timing checks:

- `iphone_day`: 1124 samples, 1124 distinct decoded frames, maximum requested/decoded PTS difference 0.0167 s.
- `android_dawn`: 1572 samples, 1572 distinct decoded frames, maximum requested/decoded PTS difference 0.5659 s.
- `android_sunset`: 1118 samples, 1118 distinct decoded frames, maximum requested/decoded PTS difference 0.7886 s.

The Android recordings have variable frame rates. OpenCV seeks deviate from the requested grid by up to 0.566/0.789 s; one sunset pair is 0.100 s out of chronological order. All sampled decoder frame indices are distinct. This affects temporal spacing, not the paired comparison or frozen keyframe labels, which use the exact same saved pixels. Frame IDs and nearby-episode times in this report refer to requested positions, with actual PTS retained in NDJSON. A requested 2 Hz grid does not assess every encoded frame or prove continuous detection during every approach. Captured UTC/GPS and device logs were not used as sign ground truth. This is one route set, not an independently human-labeled holdout with established separation from upstream training data. Face/plate detection, downstream class correctness, OCR, state transitions and phone performance remain unmeasured.

### Application and lecture decision

All ten current iPhone/Android country-pack manifests still match their pre-comparison hashes. No model pack, classifier, app threshold, speed-reference policy, device install, deployment or publication was changed. The separate default end-to-end head check finds 13/48 and does not improve on YOLO11n's hit count in this review.

The compatible YOLO26s export explicitly selects the one-to-many head, preserving `[1,7,21504]` before NMS. Its default end-to-end `[1,300,6]` output needs a distinct integration in both clients. A replacement still needs independently reviewed signs/encounters and full native detector/classifier tests on both phones, including sustained latency, memory and thermal behavior.

Slide 11 presents this published-checkpoint video comparison within the 28-slide/45-minute lecture. Fine-tuning and model evaluation remain student work; no lecture training outcomes are included. The earlier 13-image comparison and local candidate export checks are documented separately.


## Reproduce and inspect

The persistent private run is
`/Users/raphaelvolz/YouSpeedDeviceBackups/2026-10-20-yolo26/`, with `plan.json`,
`evaluation/blind-frames.json`, frozen labels/receipt, 192 lossless context frames,
three prediction NDJSON files, decoder summaries and separate end-to-end head
results. The portable JSON retains the scoring-frame results and all source and
prediction hashes, without private video pixels or GPS traces.

Restore only required `remote_path` objects from the portable evidence with:

```sh
hf download loffenauer/youspeed.de REMOTE_PATH --type dataset \
  --revision bd12056313e00acc790d25ebe5486aac11f4cf79 \
  --local-dir RESTORE_DIRECTORY
```

Verify each full SHA-256. The retained private plan supplies the verified local
paths. Use Python 3.12, Torch 2.7.0, Ultralytics 8.4.56 and OpenCV 5.0.0 in an
isolated environment. The bundled OpenCV FFmpeg backend was used because the
system Homebrew FFmpeg installation has an unavailable dylib. With the pinned
checkpoints and retained plan:

```sh
python scripts/tsr/replay_sgblur_dashcam.py extract --plan PLAN --output RUN
# Review source-only frames and freeze labels before inspecting predictions.
python scripts/tsr/replay_sgblur_dashcam.py infer --plan PLAN --output RUN \
  --baseline VERIFIED_YOLO11N.pt --candidate VERIFIED_YOLO26S.pt
python scripts/tsr/evaluate_sgblur_dashcam.py \
  --labels FROZEN_LABELS --freeze-receipt FREEZE_RECEIPT --plan PLAN \
  --replay RUN --output SCORES.json
python scripts/tsr/compare_sgblur_dashcam_heads.py \
  --candidate VERIFIED_YOLO26S.pt --labels FROZEN_LABELS \
  --freeze-receipt FREEZE_RECEIPT --plan PLAN --replay RUN --output HEADS.json
```

For exact rescoring, retain the original `blind-frames.json`, PNG files and
receipt. A fresh extraction to another path changes the reference JSON's byte
hash; verify each image/pixel identity and produce a separate documented review
receipt rather than editing the frozen evidence. `--allow-partial` is diagnostic
only and marks its output incomplete; the final evidence uses strict completion.

The scorer was checked against a hand-specified case containing a duplicate,
a missed target, an explicit ignore, a tiny proposal, another object class and
a below-threshold score. It also rejected incomplete replay output and changed
frozen labels. The earlier [checkpoint/export review](SGBLUR_YOLO26_CANDIDATE_2026-10-20.md)
retains the original still-image results and Core ML/LiteRT compatibility checks.
