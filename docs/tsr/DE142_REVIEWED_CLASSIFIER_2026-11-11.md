# Reviewed DE142 classifier for the November 11 device trial

The classifier preserves all 142 output indices and uses checkpoint
`e10f4a7f8a2d2c3554dc0ef2d0e1f96e98948c7648432ed13098ef05ff6c3299`.
It was fine-tuned from the previous DE142 v3 checkpoint on KI GPU 0. Epoch 6
was selected on development data after 10 epochs, with 14,001 training crops.
Training includes 73 additional crops from manual annotations, reviewed
Panoramax corrections, rejected proposals labelled `bad`, and historical replay.
The six corrected town exits received 16 training exposures per epoch.
The latest human correction supersedes one conflicting older training label.
One source code, `DE:282-50`, requires a class mapping before inclusion.

The classifier test contains 84 crops from held-out routes, including 18 town
entries and 13 town exits. Fifty-three other reviewed crops provide negatives
for the two town classes. Connected picture, collection, crossing and pixel
identities are kept together, with a 250 m geographic buffer. The smallest
known training/test crop distance is 450 m. Some historical HF crops have no
recoverable route metadata. Classifier test crops include scenes previously
reviewed for detector work. The six emphasized training exits are excluded.

At the existing 0.45 classifier score gate, the measured crop results are:

| Class | Current precision / recall / F1 | Reviewed precision / recall / F1 |
| --- | --- | --- |
| DE:310 | 0.6818 / 0.8333 / 0.7500 | 1.0000 / 0.8889 / 0.9412 |
| DE:311 | 1.0000 / 0.2308 / 0.3750 | 0.8667 / 1.0000 / 0.9286 |

Historical diagnostic macro F1 changes from 0.9763 to 0.9836. These town-class
measurements do not provide independent fresh F1 for every classifier output.
All raw scores remain uncalibrated.

Both native artifacts were measured on 96 identical canonical RGB inputs,
including all six corrected exits and all six appended classifier classes.
All 96 top predictions agree with the frozen CUDA checkpoint on both phones.

* Android uses float32 LiteRT weights and float32 GPU arithmetic. The model
  SHA-256 is `d33963edc6413b158f60bacae87e7ea6c552d0e9784f2de0bafa364bfd258bf6`.
  Maximum probability error is 0.000002325. Moto g86 median classifier forward
  time is 78.6 ms. Reduced-precision arithmetic measured about 45 ms, with
  maximum probability error above the existing 0.02 tolerance.
* iPhone uses float16 Core ML weights with `.all` compute units, allowing the
  Neural Engine. Runtime tree SHA-256 is
  `9c198e7a9f9e50b686b058a0c74cb93c3db18151bbd0290afa47bf1ec55d3fe2`.
  Maximum probability error is 0.004930. iPhone 14 Pro median classifier
  forward time is 1.30 ms across three rounds.

These are isolated classifier measurements. The new town YOLO26n detector
retains threshold 0.840783 and its SGBlur fallback. A separate two-window
experiment evaluates source-height squares at both horizontal edges, maps
proposals back to the upright source and merges overlap before classification.
On 61 complete reviewed scenes, right-window versus two-window town-entry
recall is 10/15 versus 11/15, and town-exit recall is 2/7 versus 5/7. KI median
detector GPU time is 5.8 ms versus 11.6 ms. These timings describe KI execution.

Aggregate training, evaluation, native export and device-parity records are
bundled under `provenance/reviewed142-*.json`. Private images, decisions and
per-image predictions remain in the ignored collection-evidence directory and
the private KI experiment directory. `package_reviewed_de142.py` verifies
checkpoint-bound parity and class order before packaging both platforms.


## Device trial deployment

YouSpeed version 1.5 build 10093 uses the reviewed classifier and the verified
YOLO26n trial detector at 0.840783. The requested left/right trial is enabled
only when that detector is active. Landscape source-height squares overlap;
source-coordinate NMS at IoU 0.45 runs before classification. Portrait/square
frames use one pass. Ultrawide frames add a whole-frame pass for center coverage.
The bundled SGBlur detector remains the safe fallback.

The attached phones passed physical-device checks for coordinate mapping and
inference. Five measured iterations after three warmups on a public reference
letterboxed into 1920×1080 gave these medians:

| Device | Single total / detector | Two-window total / detector |
| --- | --- | --- |
| Moto g86 5G, LiteRT GPU | 232.07 / 126.26 ms | 382.98 / 253.43 ms |
| iPhone 14 Pro, Core ML | 25.38 / 19.89 ms | 38.24 / 31.21 ms |

Each run classified one merged proposal; Android classifier time was about
84 ms and iPhone about 2.5 ms including Vision crop handling. This probe is
neither a drive replay nor a sustained thermal, battery or worst-case benchmark.
More retained proposals add classifier cost. Android camera analysis remains
serial and drops stale camera frames rather than queuing this work.

The iPhone detector configuration permits CPU and Neural Engine, and the
classifier uses `.all`. Core ML logged an ANE compiler failure with fallback
while detector inference completed. These timings cannot establish that all
detector operations executed on the Neural Engine. The previous Metal failure
still excludes GPU from the town detector's configuration.

The device check also exposed an iOS `/var` versus `/private/var` alias mismatch
in detector checksumming. Relative filesystem enumeration now preserves exact
artifact verification across those aliases, without accepting a different model
or allowing symlink substitution. Physical iPhone geometry and latency tests
then passed (two tests, no skips or failures).

Street Shots Map consumes the same classifier through opensign-core. Its Moto
stable app and separate town-trial app use build 10; the stable app retains
SGBlur and the debug trial loads verified YOLO26n. Both were updated in place.
Maps' GPU fixture passed separately with the town detector active and the new
classifier. The iPhone Maps host is build 10 of its initial development port;
it has camera alignment, local observations/OCR and JSON sharing, with the
remaining feature limitations documented in its repository. This does not
establish full iOS/Android Maps parity. No production survey was created by the
fixture checks, and no Panoramax database was modified.
