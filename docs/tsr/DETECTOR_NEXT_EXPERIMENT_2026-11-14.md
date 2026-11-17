# Detector follow-up: error audit, phone geometry and expanded training

User authorized KI execution and private HF publication on 2026-11-14.
Status on 2026-11-15: KI is reachable. The saved-error visual audit, d4/d5
development replay and 150-epoch reviewed-data control are complete and published.
Full-source teacher mining and both latest-runtime d7 tiling arms are complete.
The audited expanded dataset is published and d8 full-data training completed
all 150 epochs on KI GPU 0. The user explicitly approved teacher pseudo-labels
for expansion and subsequently approved private HF audit-reference publication.
The separate 24-image geographic audit was reviewed blind to d4/d8 outputs:
18 admitted frames, 13 sign faces, six exclusions. References and the final
evaluation definition were published before the once-only student comparison,
which is now complete. This audit is consumed and must not guide retuning.

[The immutable epoch-7 progress snapshot](https://huggingface.co/loffenauer/streetshots/blob/303e3b9b41bc03bba84a3987879a337a3fc22534/detector/d8/progress/epoch-0007/README.md)
publishes completed epoch metrics, losses and improvement deltas. At that snapshot,
epoch 7 AP50–95 was 0.18630 and epoch zero remained best at 0.20827. This is an
historical incomplete snapshot, not the final candidate result. The final
training report supersedes it without modifying its immutable bytes.

## Completed full-data result

[All 150 epoch logs, improvement deltas and selected weights](https://huggingface.co/loffenauer/streetshots/blob/8f21612d3c5a2db310896f168bc6f6cedb84d12c/detector/d8/results/README.md)
are published. Epoch 54 was selected at whole-frame development AP50–95 0.23675,
versus initialization 0.2082714853; epoch 150 fell to 0.18326. Selected checkpoint
SHA-256: `f29f69a68e552d7151f2c9182417c134cd1eac39cada976cd5cb60d0893b52b5`.
[The completed native-input development comparison](https://huggingface.co/datasets/loffenauer/streetshots/blob/c2c0f95590ef647f7977debff9070002ae3a2b92/reviews/detector-expanded-2026-11-15/d8-results/README.md)
records d8 phone TP/FP/FN 6/0/27 at 0.840783 and 14/3/19 at its development-only
threshold 0.43, versus d4 12/3/21 and 21/36/12 at its selected threshold 0.51.
The final d5 replay records 12/3/21 at the fixed phone threshold; the earlier
runtime snapshot recorded four rather than three FP. Preserve both reports and
their runtime provenance; do not rewrite the historical counts.

[The published geographic comparison and visual error report](https://huggingface.co/datasets/loffenauer/streetshots/blob/2628788a1d6cf89680262c2f9d7e0450518e8c09/reviews/detector-expanded-2026-11-15/geographic-audit-v1/results/README.md)
contains 18 groups and 13 reference signs:

| Setting | d4 TP/FP/FN | d8 TP/FP/FN |
|---|---|---|
| Current phone threshold 0.840783 | 4/6/9 | 0/0/13 |
| Development-only thresholds, d4 0.51 / d8 0.43 | 8/43/5 | 8/0/5 |

Seven detected references overlap; d8 gains the small speed-30 face and loses an
oblique red-border face. The candidate reduces proposal workload at recalibrated
thresholds, but it is not a drop-in replacement and has no demonstrated recall
gain. Its five misses occupy roughly 5–22 pixels per side in the actual phone
inputs. The full error audit inspected all 13 references and 43 unique unmatched
d4 proposals; one distant roadside panel remains taxonomically unresolved. The
frozen labels and thresholds were retained, with an explicit hypothetical
sensitivity calculation in the report. No model or threshold was deployed.

[The model-side geographic summary](https://huggingface.co/loffenauer/streetshots/blob/b6b6221e4b24e3625720fc982bc978800e3b5191/detector/d8/geographic-audit/README.md)
links the immutable visual report and distinguishes the archival whole-frame
sweep threshold 0.02 from the phone calibration 0.43. All six final reference,
definition, training, development and geographic publications were verified;
the KI completion record is `d8-final-completion-v1.json` under the job root.

## Completed and published

- [Visual audit and development replay](https://huggingface.co/datasets/loffenauer/streetshots/blob/537eb4c2d8c85f96886a41823979ae3136517f2a/reviews/detector-followup-2026-11-14/README.md)
  includes all 58 inspected saved error instances. d5 had 26 false positives,
  versus 18 for d4, and both missed the same seven references. Vegetation, truck
  rear lamps and roof texture dominate the false positives; two direction-board
  false positives occur in both models. These are assistant assessments.
- On 17 development images with 33 references, at the phone threshold 0.840783,
  d4 whole-frame produced TP/FP/FN = 8/2/25, and d4 phone windows = 13/3/20.
  d5 whole-frame produced 8/2/25, and d5 phone windows = 12/4/21.
- [d6 150-epoch control](https://huggingface.co/loffenauer/streetshots/blob/8ea7b48daad06d851e122e67b2785cf1da26558c/detector/d6/README.md)
  used the original 48 training images. Epoch 133 was selected at development
  AP50–95 0.23122; epoch 150 reached 0.21983. d5 reached 0.2118. No new holdout
  inference was performed, so the development gain is not a generalization claim.
- [Actual Swift/Core Image input comparison](https://huggingface.co/datasets/loffenauer/streetshots/blob/96b40cba67a739e1b62ed1a71a87f2cd735e276d/reviews/detector-expanded-2026-11-15/native-baselines/README.md)
  subsequently rendered 50 inputs with the unchanged iPhone helper on macOS and
  ran inference on KI. At 0.840783, d4 phone windows produced 12/3/21 and d5
  12/4/21. **d6 admitted no proposals at this threshold** in either input mode.
  Its AP gain therefore does not establish a drop-in improvement. Exploratory
  phone-window development F2 peaks are d4 at 0.51 (21/36/12), d5 at 0.52
  (21/33/12), and d6 at the export floor 0.25 (15/12/18). No threshold is validated
  on a fresh holdout. The average absolute per-channel difference between the
  Core Image and Pillow inputs was 3.09 on the 8-bit scale. Actual Swift rendering
  removes one approximation but still does not establish iOS/Core ML parity.

## Expanded run

All 35,147 source images were inventoried: 29,409 in Baden-Württemberg and 5,738
outside scope. None has source metadata certifying exhaustive sign annotation;
22,218 of 22,339 existing sign boxes are model-generated. After protecting prior
development/test identities, sequences and 500 m buffers, 23,858 candidates
remain. An initial sequence reserve and its geographic buffer leave 10,345
training candidates. All 10,345 actual JPEG hashes were verified on KI.

The frozen offline teacher uses YOLO11l Panoramax at full-image 2048 resolution
and overlapping 1536-pixel tiles. The c5 DE classifier filters proposal scope;
uncertain proposals exclude the frame. Class-blind Mapillary proximity can block
a pseudo-negative but cannot supply a box or certify visibility. Pseudo-negatives
are teacher judgements, not verified absence. Direction boards and supplementary
plates are excluded; traffic lights remain acceptable extras, not positive labels.

A metadata-only ancestry audit found most initially reserved sequences had d4
exposure. An additive reserve now protects 93 images in 67 sequences clear of
recovered d4 exposure and previously opened pilot frames. Its identity/sequence/
500 m rules exclude another 286 training candidates. A frozen metadata-only
selection chooses one frame per geographic component for a 24-image blinded
audit. Upstream pretraining and classifier exposure are unknown.

An early assistant spot-check inspected 48 positive proposal crops and found a
tile-boundary fragment. A tested conservative admission guard excludes the entire
frame if an accepted box may terminate at an internal tile boundary. The raw
mining output is preserved. The spot-check is not an exhaustive quality guarantee.
Twenty-two geometry, scope, provenance and admission checks pass. Synthetic KI
smoke runs verified batch-16 AMP training with the native offline AMP check; their
artificial-image metrics are not detector performance measurements.

The latest user instruction adopts Ultralytics 8.4.213 and tests native tiling.
[d7's definition](https://huggingface.co/loffenauer/streetshots/blob/f62b099caeb48be9207dc1075480944439218960/detector/d7/definition.json)
is frozen and published before training: two 40-epoch arms on the 48 reviewed
images, one whole-image and one `tile=True`, both d4-initialized, batch16, AMP,
1024 input, AdamW0.0002, seed14. Whole-image FP32 development AP selects each
checkpoint; actual Swift-rendered phone inputs compare the selected arms.
Equal source-image epochs imply different tile sample and optimizer budgets,
which are logged explicitly. This is a feature test, not full-data training.
The full eligible-data d8 build has its own frozen definition and
published dataset membership. Its practical mode choice is whole-image training
for 150 epochs: this is an explicit post-hoc engineering decision based on the
user's recall priority, not the nominal F2 ranking described below. No phone
model or threshold deployment is part of this work.

## Completed latest-version tiling experiment

[d7 results and epoch logs](https://huggingface.co/loffenauer/streetshots/blob/9a8c2d9c42713d996eac3b4431b5a9ff11d978d1/detector/d7/results/README.md)
are published. Both arms completed 40 epochs under Ultralytics 8.4.213, starting
from d4. Whole-image training used 48 samples/epoch and 31 total optimizer-step
calls; native tiling expanded the same sources to 830 samples/epoch and 544
optimizer-step calls. Equal epochs are not a controlled equal-compute comparison.

| Arm | Selected epoch | Whole-frame dev AP50–95 | Phone TP/FP/FN at 0.840783 | Exploratory phone threshold | TP/FP/FN there | F2 |
|---|---:|---:|---|---:|---|---:|
| Whole | 1 | 0.21161 | 12/3/21 | 0.53 | 21/37/12 | 0.55263 |
| Tile | 36 | 0.21701 | 1/0/32 | 0.28 | 17/3/16 | 0.55921 |

The prespecified F2 ranking marginally prefers tile. The post-hoc engineering
recommendation for full-data training is whole: it retains more signs for the
later classifier and avoids the much larger regression at the existing phone
threshold. Neither result establishes a fresh-holdout improvement. The separate
offline `tile=True` inference experiment also failed to improve these native
phone-window baseline counts; it is not interchangeable with the phone pipeline.

[The native tile-balance addendum](https://huggingface.co/loffenauer/streetshots/blob/1d99aa19a8324bf70280bc8a9948a10b4e3c86b3/detector/d7/tile-balance-addendum/README.md)
counts 97 positive and 733 empty tiles, versus 37 positive originals out of 48.
The 159 clipped/overlapping label instances are not distinct physical signs.
This is a plausible contributor to changed confidence, not a causal experiment.
A later controlled experiment should mix whole images or exact phone crops with
balanced positive tiles and compare matched optimizer-step budgets.

## Blinded geographic references

The frozen 24-group selection yielded 18 admitted images with 13 sign faces in
eight positive scenes, plus ten negative scenes. The assistant added three signs
missed by the independent teacher: bus stop, parking and motorway-gore hazard.
One indoor/nonroad scene was excluded after its overview, and five road scenes
were excluded for unresolved blurred/overlapping/overexposed objects. These
exclusions bias the audit toward interpretable scenes and must accompany results.
This is assistant review, not independent human certification.

Manifest SHA-256: `3c88d89a34212d88dd97e3291269480e0d555f0e8e1d390dc94c83ba94d3a9cb`.
KI references: `geographic-audit-v1/references/manifest.json` under the job root.
The unchanged Swift helper rendered 50 inputs for the 18 admitted images;
native input manifest SHA-256:
`fede3d99168203406e4509ea1cac5bd38749be2d47e0d88f03fc07e363d5ae79`.
Five meaningful regression tests cover raster coverage gaps, invalid boxes,
unresolved/blinding failures, light FP accounting and paired bootstrap behavior.

The user explicitly approved the 54-file reference payload (about 7 MB), now
[published and verified](https://huggingface.co/datasets/loffenauer/streetshots/blob/70dfe9e66eaa3582ef7e1727a5f2e5a0b85afb7c/reviews/detector-expanded-2026-11-15/geographic-audit-v1/references/README.md).
`freeze_geographic_evaluation.py` verified the reference-publication receipt, all
150 completed epochs, selected weights and development-only thresholds. The
[evaluation definition](https://huggingface.co/datasets/loffenauer/streetshots/blob/49dc93bcca5ae5a73942c55df3ee05c80e5dc7dc/reviews/detector-expanded-2026-11-15/geographic-audit-v1/evaluation-definition/definition.json)
was published before student inference. Its SHA-256 is
`2c3ed8c23da90ec587d555adc5d3db64a5da5dc6d5d4e879299a7930a04f4084`.

## Final expanded dataset admission

The first assembled dataset had 5,349 training images. A 24-crop additions sample
exposed a supplementary plate classified as a town sign, a partial continuous
multi-chevron board, and a primary sign combined with a lower plate. A focused
assistant audit inspected 112 proposals in the implicated rectangular categories.
The frozen exclusion list removes 61 whole frames, without converting their
remaining unlabeled signs into background examples. All raw mining records and
both pre/post-admission galleries are retained.

Final membership: **5,288 training images**, including 17 model-assisted reviewed
frames and 5,271 teacher-pseudo frames; **4,410 sign boxes** across 2,508 positive
images, and 2,780 negative-label images (mostly weak teacher judgements).
Development remains 17 images/33 boxes. The consumed test is retained as bytes
only, without another evaluation. Training shares no sequences and stays at least
501.41 m from development, 505.42 m from consumed test, and 501.27 m from the
93-image metadata-qualified reserve.

After admission, 1,572 teacher boxes on 1,127 frames have IoU below 0.5 with every valid
existing source sign box; 935 of those frames have class-blind Mapillary
candidates. This measures additional proposals, not verified new physical signs,
causal Mapillary discovery, or complete annotation. The labels remain weak.
Manifest SHA-256: `818457fffae759e6366fbc4946a40bf1386f51c0a5e326143904247a1488c71e`.

- [Frozen expanded dataset](https://huggingface.co/datasets/loffenauer/streetshots/blob/5e51cd9333ec07a88d212de479d1d2139f007495/reviews/detector-expanded-2026-11-15/README.md)
- [d8 training definition](https://huggingface.co/loffenauer/streetshots/blob/144ddf04c6771cad25b1a6c8770e214ab35b0e1e/detector/d8/definition.json)
- [d7 native-input visual report](https://huggingface.co/datasets/loffenauer/streetshots/blob/25ea039c183810095cac6c2a14c60e5fc14be054/reviews/detector-expanded-2026-11-15/latest-tiling/gallery.md)
- [Blinded geographic audit protocol](https://huggingface.co/datasets/loffenauer/streetshots/blob/4281ed055df1cd25873bfa0cbc974721cbc018e7/reviews/detector-expanded-2026-11-15/geographic-audit-v1/protocol/definition.json)


## Built-in YOLO tiling question

The earlier mining runtime is frozen at Ultralytics 8.4.56; direct inspection of
its configuration and source found no `tile` argument. New experiments use
Ultralytics 8.4.213, verified from the official PyPI release and wheel SHA-256. Teacher mining uses explicit
1536-pixel windows with 1152-pixel stride (25% overlap), plus a 2048 full-image
pass. The completed expanded d8 student run used whole frames.

Ultralytics [8.4.204](https://github.com/ultralytics/ultralytics/releases/tag/v8.4.204)
introduced built-in tiling for training, validation and prediction. The current
[official guide](https://docs.ultralytics.com/guides/high-resolution-tiling)
documents `tile=True` as windows matching `imgsz`, or an integer for a separate
window size, with 20% overlap. The current guide also describes suppression of
edge-clipped boxes when a retained complete prediction covers them; an exact
runtime revision must be inspected before relying on that implementation.

The separately pinned d7 comparison tests this behavior with the same phone
input windows, since fixed native-resolution tiles differ from the phone's
full-height edge windows. Synthetic whole/tiled AMP training passed, including
actual expansion of large synthetic images. All d4/d5/d6 checkpoints load, and
the initial latest-runtime probe matched the old-runtime Core Image baseline
counts. The later final d5 replay differs by one FP, as recorded above. A
synthetic seam test and visual inspection of the known
partial-sign case verified complete-box retention in that case; this does not
prove universal seam correctness. Tiling is Python-side orchestration;
it is not baked into exported model graphs and does not automatically change the
phone's crop/merge code. Preserve the existing runtime and comparison artifacts.

## Locked references

- Source HF dataset: `loffenauer/streetshots` at `d2c5cc44716166e2604655d7fd8cad93a8dd9468`.
- Reviewed overlay: `e428e4cff9b179934ffa5bb7609973178c8c18e8`.
- Published d5 result: `8b3b546b508b1b778ddaca07a98a49cb45509368`.
- KI job: `/home/raphael/streetshots-d5-20261114`.
- Preserve original experiments and publication bytes. New artifacts require a
  separate run directory and an additive publication prefix.

## Audit and development replay

`audit_saved_predictions.py` renders the stored holdout predictions, including
native-resolution contextual crops for each false positive and missed reference.
The initial report is an unadjudicated review queue, not a completed audit. Inspect
every error and record small/blurred/occluded, localization, annotation dispute,
excluded direction/supplement, tolerated light, or other clutter with evidence.
Do not alter the published reference labels; any corrections get a new revision.

`mobile_replay.py` processes only the manifest's validation split. It compares
d4/d5 under whole-frame and phone-window geometry. Reference iPhone behavior:
1024 input; gray114 padding; square full-height left/right windows; portrait
whole-frame fallback; extra whole-frame pass when width exceeds twice height;
score threshold0.840783; at most12 proposals per pass; source-coordinate NMS0.45
without a global cap. The exported detector uses per-pass NMS0.45/confidence0.25.
Development sweeps are restricted to thresholds at or above that export floor.

CPU Pillow interpolation and CUDA FP32 do not establish native Core Image/Core ML
FP16 parity. Archive the exact Swift/Kotlin source hashes with the run. Native
rendered inputs and exported-model comparison remain necessary for an exact
numerical phone-equivalence claim. Report GPU timing separately from phone latency.

## Longer and full-data training

1. Run a separate150-epoch d4-initialized control with the existing48 training
   images and unchanged17 development images to isolate the epoch-count effect.
   Keep epoch0 eligible and save every epoch's metrics. Do not reuse the consumed
   holdout for checkpoint or hyperparameter selection.
2. Expand selection across all29,409 in-Baden-Württemberg source images, excluding
   development/holdout sequences, duplicate images and their geographic buffers.
   The5,738 out-of-region frames remain out of scope.
3. Materialize labels from existing annotations plus tiled offline teacher
   proposals and class-blind Mapillary cues. Apply the frozen sign scope, excluding
   direction boards and separate supplementary plates. Traffic lights are not a
   training class. Explicitly distinguish reviewed labels from pseudo-labels.
4. Missing source annotations are unknown, not certified negatives. Resolve
   incomplete scenes or exclude them from ordinary fully supervised background
   loss; do not silently mark all unlabelled images negative. Preserve source IDs,
   image/label hashes, teacher confidence and label provenance.
5. Freeze an expanded training manifest, independent development geography and a
   fresh geographic holdout before starting the full-data150-epoch experiment.
   Save all per-epoch logs. Use development recall/workload curves for selection;
   assess the fresh holdout only after the candidate and thresholds are frozen.

Publication must include the adjudicated visual audit, raw replay predictions,
fixed-phone-threshold counts, development threshold curves, candidate workload,
the exact data membership and scope exclusions, training logs and model hashes.
Do not present the48-image control as full-data training.
