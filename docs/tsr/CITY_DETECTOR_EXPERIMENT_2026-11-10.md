# City-entry and city-exit detector experiment — 10 November 2026

The first GPU fine-tuning pilot did not improve known-box recall on the three
reserved detector images. Its candidate is quarantined as a research artifact,
and the installed detector, 142-class classifier and mobile runtime policy are
unchanged. A later provenance audit also found an outdated classifier holdout
exclusion; the correction and limits are recorded below.

## Sources and geometry

A read-only refreshed Panoramax snapshot contains 108 active town-sign
annotations on 107 pictures: 72 entries and 36 exits. Source history links 103
rectangles to manual creation; five city labels were added to machine-generated
rectangles and are retained separately. Manual source authorship is distinct
from an independent quality review. Current public visibility, lifecycle,
source image SHA, attribution, rectangle and registered dimensions are checked.

Using the initial protected-input snapshot, transitive picture, pixel, route,
sequence and nearby-location exclusions produced 32 manual-source boxes on 32
full images in 12 connected components. The provisional 92-image intake was
reduced before training when additional protected route links were resolved.
This v1 split is preserved for reproducibility, but is superseded for broader
cross-model holdout protection by the later provenance correction. Five
manually corrected machine boxes are review-only.

| Partition | Full images / boxes | DE:310 entry | DE:311 exit | Components |
| --- | ---: | ---: | ---: | ---: |
| Training | 25 | 15 | 10 | 7 |
| Development | 4 | 2 | 2 | 2 |
| Reserved test | 3 | 2 | 1 | 3 |

All 32 source rasters passed independent SHA-256, dimension, EXIF and decoded
pixel checks; there are no duplicate RGB hashes. The materialized manifest SHA
is `b6e06ecb1bc83d8d22b5e84d0ff468f1f2ee500d98dd87c983ef13ffdabb932b`.
Full images and source provenance remain in ignored collection evidence and
the isolated KI workspace, not in public source control.

Detector targets use the original annotation rectangle. Classifier crops have
additional downward context and cannot be substituted for the detector box.
The Panoramax API defines annotation shapes in source pixel coordinates with a
top-left origin; its geometry is distinct from mutable semantic tags.
[Panoramax semantics documentation](https://panoramax.gitlab.io/gitlab-profile/backend/install/deep_dive/semantics/).

All current source frames are partial annotations. An ordinary YOLO label file
lists the objects in an image; missing objects must not silently become trusted
background in this intake. The default full-label exporter therefore requires
an explicit complete review for sign, plate and face.
[Ultralytics detection dataset format](https://docs.ultralytics.com/datasets/detect/).

## Frozen experimental contract

- Baseline: deployed YOLO11n SGBlur checkpoint
  `698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a`.
- Ontology remains `0:sign, 1:plate, 2:face`; no classifier class expansion is
  needed for the generic sign detector.
- Separate entire connected route/sequence/physical-sign components before
  training. Exclude existing protected evaluation identities, pixels and nearby
  sites transitively. Never tune on held-out test predictions.
- CUDA inference and training on KI GPU 0 (RTX A5000), in a pinned isolated
  container under the existing account, without sudo or production changes.
- Compare the current full-height right-side 1024-square window with a diagnostic
  whole-image 1024 letterbox. Report outside/clipped targets independently of
  visible-target misses. No app crop change is made by the experiment.
- Android-equivalent decoding: sign channel, admission 0.25, sign-only NMS IoU
  0.45, maximum 12 proposals. Also report known-box recall at detector score
  0.7, the existing combined-score confirmation floor. Native rendering is
  approximated by a specified bilinear transform, not claimed pixel-identical.
  Apple has separate embedded NMS and needs its own export/device qualification.
- Inspect best raw-anchor IoU to distinguish weak sign scores from missing box
  geometry. A score-only adjustment cannot repair frozen box regression.
- Conservative adaptation: 195 trainable scalars, only the final sign-output
  row at each scale. Backbone, regression, plate/face rows and BatchNorm are
  frozen. Known manual anchors receive a positive target; remaining sign
  anchors retain soft baseline predictions, not hard negative labels.
- Fixed 20 epochs, AdamW learning rate 0.001, batch 2, seed 20261110, no pixel
  augmentation. Select by development known-box recall at score 0.7, then 0.25,
  then best IoU, then least sign-score drift. Baseline epoch 0 remains eligible.
  Frozen-state and raw non-sign-output equality checks must pass.

The bounded method reuses the independently reviewed October partial-label
loss. That earlier experiment is historical evidence, not a new result; its
held-out images remain protected from this training intake.

## Interpretation and deployment gates

This is a manual-annotation challenge set, potentially enriched for previous
misses, not a random sample of traffic signs. The three-box test supports an
exploratory check only. Four training exit signs and the sole test exit sign
are entirely outside the current mobile window. Report those capture-window
failures explicitly; do not re-split the data to remove them from evaluation.

Partial annotations support recall of known boxes, not precision, mAP or F1.
Additional proposals are not automatically false positives or true signs.
A complete independent scene review is required before claiming a net detector
quality improvement. All four development images and all three test images
were previously used for classifier training, so detector-only holdout results
are not fresh end-to-end F1. Seventeen of the 25 detector training images also
have classifier-training exposure. These counts come from the authoritative
DE142 v3 manifest, not the earlier incomplete historical exposure flag.

Before any candidate replaces the installed detector, verify other-sign
recall, complete-scene false positives, proposal/classifier workload, exact
Core ML and TensorFlow Lite parity, Android GPU timing and iPhone Core ML timing
with Neural Engine allowed. Keep all speed-limit policy semantics unchanged.

## Reproduction and results

### Baseline before training

Measured on the 25 training and four development images only, using the
unchanged deployed detector. Reserved test pixels were not opened for this
baseline or checkpoint selection. Matches require IoU at least 0.5.

| Mobile-window partition | Known boxes fully inside | Matched at score 0.25 | Matched at score 0.7 | Outside window |
| --- | ---: | ---: | ---: | ---: |
| Training | 21 | 1 | 0 | 4 |
| Development | 4 | 1 | 0 | 0 |

The whole-image letterbox diagnostic finds 1 of 29 known boxes at score 0.25
and none at 0.7. All four development targets have a raw anchor with IoU at
least 0.5, but their best compatible sign scores are approximately 0.00000462,
0.444916, 0.059255 and 0.004362. Six of 21 visible training targets lack a raw
anchor at IoU 0.5; frozen regression cannot repair those geometry misses.
Twenty-one of the 25 visible train/development targets have a shorter edge
below 32 pixels at detector input; the other four are between 32 and 63 pixels.

Median CUDA model-forward latency was about 5.02 ms on the RTX A5000. This is
neither a phone benchmark nor end-to-end pipeline latency.

### Selected candidate and reserved-route result

The fixed 20-epoch run completed on the RTX A5000. Twenty-one visible training
boxes were optimized (15 entries, six exits); four outside-window exit boxes
were excluded from the loss. The development criterion selected epoch 20.
Candidate SHA-256:
`9b5bdd493d54a4e03910096118b2af852a436781547297d3056fbddd37af6a58`.
The checkpoint was frozen before reserved test inference.

| Mobile-window partition | Baseline at 0.25 | Candidate at 0.25 | Baseline at 0.7 | Candidate at 0.7 |
| --- | ---: | ---: | ---: | ---: |
| Training diagnostic | 1 / 21 | 8 / 21 | 0 / 21 | 6 / 21 |
| Development selection | 1 / 4 | 3 / 4 | 0 / 4 | 3 / 4 |
| Reserved detector test | 0 / 2 | 0 / 2 | 0 / 2 | 0 / 2 |

The sole test exit sign is outside the mobile window and therefore remains a
miss when counting all three known test targets. Whole-image letterboxing also
gives 0/3 for both models. The two visible test entries are only 17.94 and 10.67
pixels on their shorter edges. Their compatible raw boxes reach IoU 0.573 and
0.625, but candidate scores remain about 0.001313 and 0.000149. The whole-image
test exit is 9.45 pixels on its shorter edge, with maximum raw IoU 0.4927.
This shows that simply exposing the whole image at the same 1024 resolution
does not resolve these misses.

At admission score 0.25, mobile proposals increased from 18 to 152 across the
29 training/development images and from 1 to 16 across the three test images.
Twelve test proposals exceeded 0.7, without matching a known target. Partial
labels do not establish that these are false positives, but the extra proposals
could increase classifier workload. The candidate has no demonstrated reserved
route benefit and must not be promoted.

Independent checkpoint verification found exactly 195 permitted sign-output
scalars changed; all other state is bitwise identical. Repeated baseline input
tensors and raw outputs were identical across all 58 training/development
image/geometry evaluations. These checks do not establish unchanged other-sign
precision or unchanged face/plate behavior after native post-processing.

### Provenance correction and next experiment

The initial protected input used an older classifier split. The authoritative
DE142 v3 manifest had subsequently moved four of the detector training pictures
to classifier development. All four were assigned and loaded by this experiment;
two were outside the detection window and excluded before training forward
passes or optimization, while two entered training. All four remained in the
diagnostic evaluations. Internal detector train/development/
test route separation still holds, but the broader promise to protect all
classifier evaluation images was not met. The v1 candidate and results are
explicitly marked `quarantined_research_only` locally and on KI.

The correction protects all development/test/reserved identities from the
authoritative classifier manifest and their entire connected route/location
components. Preserve v1 artifacts; do not silently rewrite the experiment or
relabel its opened test images as fresh. Any corrected split of these already
predicted images is exploratory, not a new independent holdout.

The corrected v3 metadata plan uses 9,511 protection records and leaves 16
images in six components. Its provisional partition is 12 training images
(eight entries, four exits), two development images (one of each), and two test
images (one of each). All 16 were already in v1 training: these partition names
do **not** establish a new holdout. All seven opened v1 development/test images
are excluded. This is a planning artifact only, with training launch disabled;
no corrected-model training or additional inference was run. Its manifest SHA
is `173cbf9e17fc8d4c843588ac2062ed090e7b350ceda9220516f21f98358df347`.

The next useful data work is additional route-separated full-frame annotations
of small DE:310/DE:311 signs, together with complete-scene labels and negative
examples to measure precision and proposal cost. A larger feature/regression
adaptation needs loss masking or complete labels so unannotated signs, plates
and faces are not treated as background. Multi-scale or tiled coverage should
be a separate experiment with a fixed input-pixel budget and GPU/device timing;
changing the mobile camera window is a product/runtime change, not a weight-only
fix. Freeze a genuinely new test set before comparing those approaches.

### Reproduction and validation

Source tools are `scripts/tsr/prepare_city_detector_dataset.py`,
`evaluate_city_detector.py` and `train_city_detector.py`. Audit, checksums,
frozen split manifests and measured results are retained under
`docs/collection-evidence/2026-11-10-city-detector/`. The isolated server workspace
is `/home/raphael/youspeed-city-detector-20261110/` on KI. Run configuration,
per-epoch development results, selected checkpoint proof and independent test
audit are retained. The pinned CUDA image is
`sha256:886be2a4e18d52e587acf3ebfeaa7cbf2da92c1c26d2355e83b94217c474faca`.
Docker is rootless: container UID 0 maps to the ordinary `raphael` host account;
no sudo or host-root privileges were used. Two pre-training path/permission
launch errors were corrected without changing data or hyperparameters.

All 55 dataset-builder, evaluator and trainer unit tests pass. The existing
Android city diagnostic was updated for the installed 142-class classifier and
compiled successfully. The Moto was no longer connected, so no new device
benchmark ran. This unsuccessful candidate was not exported to Core ML/TFLite,
committed as a model asset, or deployed. Both installed apps retain their prior
models; speed-limit state-machine policy is unchanged.
