# DE142 model integration, 10 November 2026

The DE pack now uses the final v3 142-class classifier in YouSpeed and the
Street Shots Map / OpenSignMap shared core. The first 136 output indices are
preserved. The appended classes are `bus:stop` (DE:224),
`supplementary:plate`, `maxspeed:90`, `DE:156-10`, `DE:325.1` and `DE:325.2`.
DE:625-20 is an exact inventory/catalog reference with official artwork; the
broader `arrow:red` classifier does not infer its direction or exact subtype.
Generic supplementary plates retain unknown content and restriction semantics.

The detector, confidence/confirmation thresholds and speed-limit state-machine
policy are unchanged. Scores remain uncalibrated. Both native exports have the
same class order, mapping and checkpoint-bound presentation catalog. The Apple
pack uses Core ML; Android uses TensorFlow Lite FP16 weights and a GPU delegate.

## Identity and provenance

- Pack: `de-youspeed-expanded142-v3`.
- Native checkpoint: `c057107156d7bd4d535ece48f88b492e9c754ba59e951302ebdf77bfd75a2dda`.
- Android classifier: `f179b03a59aff8ceb8c0127077c595d0f1629d9b30d0cf487cfa11bf24f4b15a`.
- Apple compiled tree, runtime hash convention: `c697dd469ba4aa4e15ce7ff73459b5fa02d5ced7ea95d1dbe56d970aae902e9b`.
- Training: 13,731 unique crops; fixed 10-epoch CUDA run, epoch 2 selected by the
  frozen development criterion. New silver-labelled intake was TRAIN-only.

Each runtime pack contains `provenance/expanded142-*` export, training,
evaluation, parity and attribution records. Older provenance files describe the
bootstrap detector/predecessor. The immutable 134-class source fixture under
`shared/tsr/baselines/` keeps the expansion builder reproducible after promotion.
`scripts/tsr/package_de142_mobile.py` verifies exact exports and measured parity
before assembling both packs; `scripts/tsr/mapping_review.py --write` regenerates
the shared mapping ledger.

Private crops, image-level predictions and annotation progress remain in the
ignored `docs/collection-evidence/2026-11-09-de-expanded-classifier/` evidence
folder. They are not included in the source commit.
Aggregate counts for all 142 classes, sorted by descending unique training
count, are in `DE142_TRAINING_CLASS_COUNTS_2026-11-10.json`. Scheduled repeated
training exposures are reported separately from unique crops.

## Numerical checks and performance

The attached Moto g86 5G ran 96 crops, 20 warmups and three paired rounds of the
136- and 142-class models. All 546 operations were delegated to the GPU. The
142-class classifier measured 44.73 ms median / 45.45 ms p95 for canonical
forward inference, and 45.38 / 46.03 ms including native crop preprocessing.
These are isolated classifier measurements, not end-to-end camera latency.

All 96 canonical top predictions agreed with the frozen CUDA reference; maximum
absolute probability difference was 0.0180673, below the existing 0.02 tolerance.
Core ML also matched all 96 top predictions on the Mac with `.all` compute units
(Neural Engine allowed), with maximum difference 0.0129335. The Mac check is
export parity, not an iPhone latency measurement or proof of per-operation ANE
placement. Final 142-class iPhone device timing remains pending.

## Accuracy boundary

Historical compatible-report macro F1 is 0.978105, versus 0.981753 for the
136-class predecessor. Legacy catch-all label conflicts limit interpretation.
The six appended classes have no independent held-out F1 yet. Fresh,
route-separated Panoramax/app F1 remains pending the user's prediction-blind
label review; device agreement and training fit do not establish accuracy.

## Device update

YouSpeed 1.5-debug build 10088 was installed in place on the Moto g86 5G. The
existing `de.youspeed.android.debug` identity, signer and original installation
date were preserved; there was no uninstall or application-data clearing. The
installed APK matches SHA-256
`a0550675d2b332a37fd80b1f59c658dd63762ea2ed5340c065a2f5ea0b2a8f30`.
The app was relaunched after its on-device packaged-model test passed: 142
classes, GPU execution with no fallback, and the pinned 70 km/h sign correctly
recognized through the full detector/classifier pipeline.

Validation also passed 214 new Python regression tests (nine optional tests
skipped), 60 focused catalog/mapping/artwork checks, 13 Android JVM tests and
six isolated iPhone simulator tests with zero skips. Five catalog tests were
additionally run against the selectively staged source. Unrelated existing
working-tree changes were preserved outside this commit; the local device APK
includes those existing app edits. Map Log/core commits and device verification
are recorded in their respective repositories.
