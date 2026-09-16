# TSR export, model lineage and source obligations

Reviewed 2026-09-16.

This document separates three things that were previously easy to conflate:

1. the Panoramax/Prolix inference environment on the owner-controlled KI
   server;
2. the mobile conversion records observed for the German bootstrap pack; and
3. the export, runtime-parity and release evidence for France, the Netherlands
   and Belgium. Their conversion and offline parity gates are now complete;
   device, legal/action and signing gates remain. The foreign calibration gate
   follows the German operational field-calibration bar.

## What was found on the KI server

The SSH alias `wingki01` points to the owner-controlled KI server. Its observed
inventory includes Ubuntu 24.04, Docker 29.6.1, CUDA 12.6.3, two NVIDIA RTX
A5000 cards and an NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition.
The exact inventory and checkpoint hashes are recorded in
[`export-environment-evidence-v1.json`](../shared/tsr/export-environment-evidence-v1.json).

The available `woladen-prolix:2ad3c2382d` image is an inference image built
from the sister repository's Prolix deployment revision
`2ad3c2382d95801955afc513e9194e01ef8e692e`. Its image digest and observed
packages are recorded, but it is not the German mobile export environment:

- PyTorch `2.6.0+cu126` and Ultralytics `8.4.49` are installed;
- Core ML Tools, ONNX, onnx2tf, TensorFlow and Python AI Edge LiteRT are not
  installed in that image;
- the server contains the Panoramax `.pt` checkpoints and no discovered Core ML
  or LiteRT app artifacts or export reports.

The Blackwell server is therefore ready to accelerate isolated Panoramax
inference, training or calibration work. For the foreign packs, the missing
conversion environments were built as pinned Docker recipes on that server:
the Core ML recipe uses the Torch 2.7/CoreMLTools 9 compatibility pair, while
the LiteRT recipe uses the German-compatible ONNX/onnx2tf/TensorFlow/LiteRT
chain. Core ML compilation and packaging still use the existing Mac/Xcode side
of the pipeline.

## What can be proven about the German artifacts

The iPhone export record is present in this Mac's ignored Xcode-derived output
at:

`iphone/.derived/SpeedConsumerBuild/Build/Products/Debug-iphoneos/SpeedConsumer.app/TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack/provenance/export-run.json`

It records a published-checkpoint conversion using:

- Ultralytics `8.4.56`;
- Core ML Tools `9.0`; and
- PyTorch `2.13.0`.

The Android export report is tracked at:

`android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/provenance/android-export-report.json`

It records Ultralytics `8.4.56`, ONNX `1.17.0`, onnx2tf `1.28.8`, TensorFlow
`2.19.0`, Python `ai_edge_litert` `1.3.0`, and app runtime LiteRT `1.4.2`.

The German classifier report found in the local derived output is more limited
than its filename suggests. It benchmarks the Panoramax German validation
archive at dataset revision
`b4856947ed7cb6312587258acc90e8cf88a4aa13`, `val.zip`, SHA-256
`13ca882129a4e024fc865fc4a3187514a4554f8e323f612e338144fd1ff189ea`, with
6,944 samples and 134 classes. The report itself says
`informational-benchmark-only`, leaves runtime output as `raw_score`, and does
not claim per-device calibration. It is therefore reusable as a German
baseline/procedure reference, not as foreign calibration or acceptance data.

No separate German holdout archive was found. The Panoramax revision exposes
`train.zip` and `val.zip` only; the repository's holdout names are schema and
test-fixture terminology. The optional country validation-source locations and
hashes are pinned in
[`panoramax-calibration-sources-v1.json`](../shared/tsr/panoramax-calibration-sources-v1.json).

Neither record contains a generating-host identifier. The evidence supports
the statement that the Core ML output was observed in this Mac's derived
Xcode output and that the Android export report is part of the repository. It
does not support attributing the German artifacts to the KI server. That
uncertainty is intentionally retained in the machine-readable evidence rather
than being guessed.

## Foreign model transformation target

Each foreign country must use the same production contract as Germany:

1. a shared Panoramax detector proposes sign candidates;
2. the country classifier scores the detector crop;
3. Core ML serves iPhone and LiteRT serves Android through CameraX;
4. reference, Core ML and LiteRT preprocessing and outputs are compared;
5. candidate bursts are associated over time; and
6. only a validated physical-sign passage can change the active speed context.

The foreign `.pt` checkpoints are conversion inputs, not app assets. The
required version set is pinned in the evidence file and the source/model
lineage is pinned in [`training-sources-v1.json`](../shared/tsr/training-sources-v1.json).
The current readiness manifest keeps FR, NL and BE packs disabled in the
country registry, but evaluation packs are now staged in both app trees. Their
classifier calibration gates are accepted as operational benchmarks, with
native raw scores, just as in the German field reference; this does not claim
per-device calibration or make a frame score change the active speed context.

The staged packs use the same acceleration contract as Germany: iPhone asks
Core ML for `MLComputeUnits.all`; Android attempts the LiteRT GPU delegate and
falls back to CPU only if delegate creation or invocation fails. The foreign
Core ML and ONNX/LiteRT probes were run against the same normalized RGB
`uint8 / 255` contract used by the mobile encoders.

The completed offline export/parity evidence is:

| Country | Core ML artifact | LiteRT artifact | Runtime-linked classes / classifier classes | Mobile parity |
| --- | --- | --- | ---: | --- |
| FR | `d560e84f…2568` | `a4652db0…00ea` | 105 / 256 | passed |
| NL | `f46367c6…6f5a` | `7fa821da…2193` | 82 / 160 | passed |
| BE | `73b0d7bc…5f71` | `b8911e91…e312` | 90 / 143 | passed |

National artwork coverage remains FR 114, NL 111 and BE 115. The lower
runtime-linked counts are deliberate: an artwork entry is not linked to a
classifier class unless the reviewed national mapping has an exact or
unambiguous model-vocabulary match. The remaining unmapped classes require
country mapping review or a retrained/updated Panoramax checkpoint; they are
not silently treated as recognized signs.

## Panoramax datasets and archives

The current app does not need Panoramax dataset archives. The checked-in source
records retain the latest Panoramax revisions as model/data lineage and for
future retraining or calibration acquisition. Runtime bundles need only the
approved converted model, its calibration and mapping records, manifests,
notices and hashes.

The latest recorded dataset revisions are:

| Country | Dataset revision | Dataset treatment |
| --- | --- | --- |
| DE | `b4856947ed7cb6312587258acc90e8cf88a4aa13` | CC BY-SA 4.0; attribution/share-alike record retained |
| FR | `ea75988e381f16e4677c5f42aa5fedea005f23d6` | Etalab Open Licence 2.0; attribution record retained |
| NL | `68c7c1bac103f7ed42440af71536827dcada519c` | CC BY-SA 4.0; attribution/share-alike record retained |
| BE | `6479ab5a2a47629dc6e3a242a177c2537d9cf378` | CC BY-SA 4.0; attribution/share-alike record retained |

Each of those revisions also currently exposes a `val.zip`: FR
`0b8e4b73…`, NL `b0f9ef49…`, and BE `f6bc5250…`. The archives were acquired on
the KI server, hashed, and scored with the reproducible
[`panoramax_classifier_benchmark.py`](../scripts/tsr/panoramax_classifier_benchmark.py)
runner. They are accepted as operational classifier-calibration evidence,
not relabelled as independent holdouts. The absence of a separate upstream
Panoramax holdout is therefore no longer a foreign release-gate blocker; a
route-held-out evaluation remains a follow-up quality improvement.

The current benchmark records are:

| Country | Samples / classes | Top-1 | ECE | Accuracy at raw-score floor 0.70 |
| --- | ---: | ---: | ---: | ---: |
| FR | 13,884 / 258 | 91.69% | 0.0393 | 94.94% |
| NL | 6,197 / 166 | 92.54% | 0.0467 | 94.78% |
| BE | 3,614 / 143 | 90.40% | 0.0525 | 93.63% |

The signed evidence paths and hashes are in
[`foreign-runtime-readiness-v1.json`](../shared/tsr/foreign-runtime-readiness-v1.json)
and the full reports are in `shared/tsr/foreign-calibration/`. FR has 25
validation samples in two labels absent from the published FR checkpoint;
NL has 56 samples in six absent labels. Those coverage details remain visible
in the reports and must be resolved during the pending national mapping/action
review before a runtime pack is enabled.

The owner-approved commercial-use decisions are reflected in the source
manifest. They do not waive attribution, share-alike, source, model-lineage
or national-rule obligations. This is an engineering record, not a legal
determination.

## Ultralytics source and notice obligations

The repository root is already AGPL-3.0. The app-visible source catalog and
offline notices now also record Ultralytics `8.4.56`, its AGPL-3.0-only source,
the source revision, the build-time role, the corresponding-source location,
the fact that the Python package is not embedded, and the no-endorsement
boundary. The reusable notice is
[`ULTRALYTICS_SOURCE_NOTICE.txt`](../shared/attributions/licenses/ULTRALYTICS_SOURCE_NOTICE.txt).

The attribution generator places that notice in the shared catalog consumed by
both apps. The German model-pack notices retain the complete AGPL text; future
foreign packs must carry the same notice set and their country-specific
Panoramax model/dataset records.

## Remaining owner inputs

No new Panoramax archive is needed merely to build or run the app. The remaining
inputs that cannot be inferred safely are:

- an attached iPhone and Android device run for each foreign pack; and
- the country legal/action mapping review and release decision; and
- signing/registry approval after those gates pass.

No additional country calibration archive is needed for the formal foreign
calibration gate at this point. Everything else in this record—the server
inventory, checkpoint hashes, calibration reports, mobile exports, parity
reports, acceleration contract, source obligations and app notice wiring—has
been recorded in the repository.
