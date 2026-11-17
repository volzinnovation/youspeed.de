# Balanced detector experiment and Mapillary automatic benchmark

15 November 2026. Work authorized: review pseudo-negative misses, compare balanced small-sign tiles mixed with the phone crops, train on KI, publish results/epoch logs, then start pretrained Panoramax fine-tuning. The user subsequently requested benchmarking the existing Panoramax and d4–d9 models against Mapillary automatic detections.

## Frozen training inputs

All 145 classifier-rejected proposals in 137 pseudo-negative images were visually reviewed. Sixteen fixed-hash teacher-empty image overviews were screened and two targeted native regions inspected. This is **not exhaustive scene annotation**. Thirteen sign regions were added across 11 images:10 bus-stop faces, 1 yield,1 no-stopping and1 bend-hazard board. Twelve of these regions had been proposed by the teacher and rejected by the scope classifier. Twenty-four ambiguous/poor-visibility images were excluded. Remaining labels are predominantly weak.

The corrected pool contains 5,264 source images and 4,423 boxes. One positive source has no usable phone crop without clipping a known sign; the frozen schedule covers all 5,263 usable parents. Both arms see identical parent schedules and 75% positive /25% pseudo-negative draws. Half the mixed arm uses enlarged small-sign tiles; the corresponding control draws use positive phone crops. Known clipped boxes reject an entire view. Training uses the phone geometry with Pillow bilinear rendering; evaluation uses unchanged SwiftMac-rendered inputs. Native `tile=True` is off because this experiment explicitly prepares and balances views.

Both nano arms start from d4 and run 40 epochs of 1,024 draws, batch 16, nominal batch 16, AdamW 2e-4, AMP, Ultralytics 8.4.213, on KI GPU 0 only. Each epoch is a **sampling epoch**, not a full-source pass. Checkpoint/threshold selection uses the existing 17 development images / 33 faces: maximize recall with mean proposals/image<=4, then precision,higher threshold and earlier epoch. Epoch 0 is eligible. The consumed geographic audit and original test are not used for this experiment.

- [Reviewed training evidence](https://huggingface.co/datasets/loffenauer/streetshots/blob/402d9714cec7b2f4600c4ee8a0aeb29a46e46614/reviews/detector-balanced-2026-11-15/README.md)
- [Frozen d9 definition](https://huggingface.co/loffenauer/streetshots/blob/5bc78ecfe8051deabdcf4b2a6a00b8ce71f0fc28/detector/d9/definition/README.md)
- [Frozen Panoramax follow-up](https://huggingface.co/loffenauer/streetshots/blob/c324853a7446fe5c2920113da4b870c6b2932c78/detector/d10/definition/README.md)

## Mapillary automatic-reference sample

The live API probe successfully retrieved an image and 88 detections using the existing account. Generic sign masks and classified detections can duplicate one physical face. A previously reviewed probe image also showed two town-exit signs, one labeled as a direction sign. It is excluded from the benchmark. Pixel polygons require `y_coord_down=True` with the vector-tile decoder; the initial default decode was vertically mirrored and was corrected before sample construction. The coordinate transform has a synthetic regression test.

A metadata-first query plan selected 29 images from 29 distinct sequences across 11 BW location blocks. Queries requested up to 100 images within 50 m of each of 16 predefined city anchors; filters required non-panorama images, dimensions>=768px, a known sequence, at least 500 m from current fine-tuning/development images, and at least 25 m between selected cameras. Up to 4 images per anchor were chosen in fixed SHA256 order before querying detections. The intended maximum 64 was not filled; no replacement was selected based on signs or detector output. The sample is a bounded convenience sample, not a representative random sample.

Sample manifest SHA256: `022f5420b45e2a83178deac332fa6a5cff687398913a30cf689f8a8a9824c172`. Its 29 images generated 87 SwiftMac inputs (whole plus the phone’s two crops). Raw automatic proposals include 23 classified primary candidates and 63 generic-front masks before deduplication. Sign backs and direction/supplementary categories are excluded from the primary reference tier. A broader, separately reported tier adds generic front masks whose scope is unknown. Generic masks may include supplementary/direction panels. IoU>=0.8 duplicates are collapsed, retaining classified boxes first.

The benchmark evaluates d4,d5,d6,d7-whole,d7-tile,d8,d9-phone,d9-mixed, the two fixed final-epoch 40 d9 checkpoints, and the original Panoramax detector. Every operating threshold is calibrated only on the existing 17 development images, before inference on the Mapillary sample. The current phone threshold 0.840783 is reported separately. All use actual SwiftMac phone crops at 1024 px, KI FP32 inference, sign class 0, per-pass cap 12 and NMS 0.45. Neither numerical iPhone CoreML parity nor on-device latency is measured.

**Scores are agreement with incomplete automatic references.** Coverage is the fraction of available reference boxes matched at IoU>=0.5. Unmatched predictions are not verified false positives. Images with no automatic references are not certified negatives. “All available references matched” does not establish that all visible signs were detected. Upstream pretraining exposure is unknown. The sample is excluded from training and checkpoint/threshold tuning. Raw Mapillary images/annotations remain local/KI; the planned HF publication contains numeric results, source links and hashes.

For a future fully annotated benchmark, use a reviewed independent Mapillary sample or an accessible fully annotated MTSD subset. The [MTSD paper](https://arxiv.org/abs/1909.04422) distinguishes fully and partially annotated images. The dataset portal required login during this check, so access and current terms were not established. The ordinary [Mapillary image-detection API](https://mapillary.github.io/mapillary-python-sdk/docs/mapillary.config.api/mapillary.config.api.entities/) is operational; its model outputs alone do not certify completeness.

## Panoramax follow-up

The follow-up starts from the published YOLO11l Panoramax checkpoint, source SHA256 `a3205e4a92b3acdaa883c02e09dba439c48f6c5bc8c89aff44da7c2e79f140e7`, retaining pretrained sign/regression weights and removing face/plate outputs. A CPU numerical check verified unchanged sign outputs before training. The reduced model has 25,311,251 parameters. The planned run is 20 sampling epochs,1,024 draws/epoch, batch 4, nominal batch 16,1024px AMP, AdamW 1e-4. It is a larger offline teacher experiment, not a phone deployment. Launch is gated on verified publication of the d9 comparison/epoch logs and completion of the Mapillary benchmark on GPU 0.

Runtime state and raw evidence are under `/home/raphael/streetshots-d5-20261114/balanced-v1` and `/home/raphael/streetshots-d5-20261114/mapillary-auto-v2` on KI. Credentials remain on the Mac. No app model or shared runtime policy has been deployed or changed.

## Completed comparison

Both d9 arms completed all 40 sampling epochs with 2,560 optimizer calls and 2,552 actual AMP updates each. Both retained epoch 0 (d4): 21/33 development references at threshold 0.51, with 36 unmatched predictions. At the fixed phone threshold, this is 12/33 and 3 unmatched. The final trained phone-only epoch matched 16/33 at threshold 0.33; the final mixed epoch matched 14/33 at threshold 0.31. The balanced tile mixture did not improve the frozen development selection outcome.

The automatic Mapillary benchmark completed for 11 checkpoints. Its 23 classified reference boxes occur in 10 images; the broader 68-box tier occurs in 14 images. The other images remain unverified, not clean negatives. The observed minimum separation from current fine-tuning/development images is 10,817 metres.

| Checkpoint | Threshold from development | Classified reference matches | Broad-front matches | Unmatched predictions/image (classified tier) |
|---|---:|---:|---:|---:|
| d4 | 0.51 | 21/23 | 27/68 | 4.28 |
| d5 | 0.52 | 21/23 | 26/68 | 4.86 |
| d6 | 0.25 | 15/23 | 21/68 | 1.14 |
| d7 whole | 0.53 | 21/23 | 27/68 | 4.48 |
| d7 tile | 0.28 | 17/23 | 19/68 | 0.79 |
| d8 | 0.43 | 17/23 | 21/68 | 0.83 |
| d9 phone / mixed selected (both epoch 0) | 0.51 | 21/23 | 27/68 | 4.28 |
| d9 phone final epoch 40 | 0.33 | 20/23 | 24/68 | 0.83 |
| d9 mixed final epoch 40 | 0.31 | 18/23 | 22/68 | 1.03 |
| Panoramax original | 0.33 | 17/23 | 19/68 | 0.41 |

The phone-only final checkpoint has fewer unmatched proposals with one fewer classified reference match than d4 on this sample. That is a diagnostic tradeoff, not verified precision improvement: many unmatched predictions may be real signs absent from Mapillary references. The models and thresholds were not selected using these results. The d10 recipe remains the one frozen before this benchmark.

[Published development visual report](https://huggingface.co/datasets/loffenauer/streetshots/blob/e8db5f51d679e2e66f20386f4159714ec947624d/reviews/detector-balanced-2026-11-15/results/README.md)


- [All d9 epoch logs, curves and checkpoints](https://huggingface.co/loffenauer/streetshots/blob/ba7ac947881d3254d22deb4c5474bf3eb4fd995f/detector/d9/results/README.md)
- [Completed 11-checkpoint Mapillary automatic-reference comparison](https://huggingface.co/loffenauer/streetshots/blob/5889cbbf0a0c0a83c203bc38be05effcf64d82d6/detector/d9/mapillary-automatic-benchmark/README.md)

Publication receipts verify all bytes against HF LFS SHA256 or Git blob SHA1 plus size, on the existing private repositories. The training-review publication was explicitly approved after automatic approval review requested separate authorization for its 187-file/40 MB payload.

The d10 Panoramax run was launched on GPU 0 only after d9 result/visual publications were verified and the Mapillary benchmark completed. Its process/launch records are `balanced-v1/panoramax-process.json` and `balanced-v1/panoramax-launch.json` on KI. This is a started experiment, not a completed or promoted model.

The [initial d10 epoch snapshot](https://huggingface.co/loffenauer/streetshots/blob/a09dc42c96c2f3416d9f8d32b34c04e919ff12a4/detector/d10/start-epoch-003/README.md) contains baseline plus three completed epochs; all 12 files were verified after publication. At the final status check, four of 20 planned epochs had completed, the training process remained alive, and no completion seal existed. These are interim logs, not final performance claims.

## Completed d10 and final Mapillary replay

The subsequent completion check confirmed all 20 epochs finished, with 20,480 balanced draws, 1,401 optimizer calls and 1,392 actual AMP updates. Development selection retained epoch 10 at threshold 0.28: 13/33 matched, one unmatched prediction, 20 missed, compared with 8/33 matched at initialization. The final epoch also matched 13/33 but had three unmatched predictions. These development results are used for selection, not independent test evidence.

The selected checkpoint SHA256 is `a517f550b06408e6e5876d19cb93c62545f6af48a2a03369fb9e24f796b9a5c9`. Its frozen threshold and checkpoint were replayed through the same 58 SwiftMac crops of the same 29 Mapillary images, with unchanged phone proposal logic, pinned Ultralytics 8.4.213 and KI FP32 inference. The d4 and original Panoramax baseline metrics exactly reproduced every previously recorded metric, including per-image and size-bin results. No Mapillary tuning was performed.

| Model | Development threshold | Classified reference matches | Unmatched predictions (29 images) | Matches at fixed phone threshold 0.840783 |
|---|---:|---:|---:|---:|
| d4 | 0.51 | 21/23 | 124 | 17/23 |
| Original Panoramax | 0.33 | 17/23 | 12 | 0/23 |
| d10 Panoramax epoch 10 | 0.28 | 20/23 | 20 | 10/23 |

Fine-tuning improved automatic-reference agreement over original Panoramax. Compared with d4, the selected d10 checkpoint matched one fewer classified reference and produced fewer unmatched proposals. Incomplete automatic annotations prevent interpreting those unmatched predictions as verified false positives. d10 is not a drop-in replacement at the current phone threshold; CoreML numerical parity and iPhone latency remain unmeasured. No model was deployed.

The [final results and all epoch logs](https://huggingface.co/loffenauer/streetshots/blob/79b679013cd183965520926e06fff3d2a45f2d3f/detector/d10/results/README.md) and [detailed Mapillary comparison](https://huggingface.co/loffenauer/streetshots/blob/79b679013cd183965520926e06fff3d2a45f2d3f/detector/d10/results/mapillary/README.md) are published on the existing private HF model repository. All 55 files (2,879,815 bytes) were verified against remote content hashes and sizes. The publication includes baseline plus 20 epoch prediction/sweep files, history, raw logs, losses, learning rates, update counts, per-epoch changes, learning curves, benchmark predictions, CSV comparisons, source links and recipe code. Weights remain on KI; raw Mapillary media and annotation payloads were not republished.

The final receipt is `publication-receipts/d10-panoramax-final-results.json` on KI. The training seal's `holdout_evaluated: false` is preserved as training-time provenance; the later replay has its own completion record at `balanced-v1/panoramax-final-benchmark/complete.json`.
