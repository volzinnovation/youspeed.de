# ZOD-only and three-way lane-paint comparison — 2026-10-09

**ZOD-only training fails under this fixed sparse-supervision recipe.** It predicts paint across large background regions: on the reused ZOD evaluation, mean precision is **0.51%**, recall **99.84%**, F1 **1.01%** and IoU **0.51%**. A2D2-only remains best on ZOD F1/IoU in every seed; adding A2D2 improves substantially over ZOD-only, but the mixed arm still loses to A2D2-only in every seed. **Do not promote the ZOD-only or mixed checkpoints.** These results concern this training recipe and small frozen-feature head, not the suitability of the ZOD dataset itself.

All nine heads (three source arms × three seeds) and the combined summary completed successfully from **14:51:49 to 15:24:36 CEST** (12:51:49–13:24:36 UTC), **32.79 minutes** including source validation, feature preparation, training and scoring. The detached series used only GPU 2. The complete primary evidence is hash-verified on volz-db; earlier experiments remain intact. No model export, phone activation, deployment or protected speed-reference change occurred.

**What this control answers.** The [previous two-arm comparison](LANE_ZOD_SCALE_RESULTS_2026-10-09.md) omitted ZOD-only and selected checkpoints on A2D2 validation. This follow-up reruns all three arms and selects **epoch 10 for every arm**, regardless of validation scores. A2D2 validation is recorded only as a diagnostic. ZOD-only uses zero A2D2 optimizer samples. This removes A2D2 checkpoint-selection preference from the comparison; it does not change sparse labels, the loss or the frozen feature extractor.

**Evaluation status.** The same 100 ZOD frames were already scored in the previous experiment. They are **development evidence, not a fresh blind holdout or acceptance test**. The custom cohort has 20 vehicle/day groups, 69 paint-positive frames and 31 no-paint frames. Metrics pool valid-pixel counts within each seed and then take the arithmetic mean across all three fitted seeds. Ranges describe those seeds, not population confidence. All masks, source coverage and the 0.5 threshold stayed fixed.

## ZOD development results

| Arm | Precision, mean [range] | Recall, mean [range] | F1, mean [range] | IoU, mean [range] |
|---|---:|---:|---:|---:|
| A2D2 only | 27.36% [26.11, 29.43] | 24.89% [22.35, 27.81] | 25.94% [25.41, 26.93] | 14.90% [14.55, 15.56] |
| ZOD only | 0.51% [0.44, 0.65] | 99.84% [99.66, 99.94] | 1.01% [0.87, 1.28] | 0.51% [0.44, 0.65] |
| A2D2 + ZOD | 8.44% [6.66, 10.46] | 75.41% [72.98, 77.07] | 15.12% [12.27, 18.30] | 8.19% [6.53, 10.07] |

| Seed | Arm | Precision | Recall | F1 | IoU |
|---|---|---:|---:|---:|---:|
| 20261009 | A2D2 only | 26.11% | 27.81% | 26.93% | 15.56% |
| 20261009 | ZOD only | 0.44% | 99.91% | 0.88% | 0.44% |
| 20261009 | A2D2 + ZOD | 10.46% | 72.98% | 18.30% | 10.07% |
| 20262009 | A2D2 only | 26.54% | 24.50% | 25.48% | 14.60% |
| 20262009 | ZOD only | 0.65% | 99.66% | 1.28% | 0.65% |
| 20262009 | A2D2 + ZOD | 6.66% | 77.07% | 12.27% | 6.53% |
| 20263009 | A2D2 only | 29.43% | 22.35% | 25.41% | 14.55% |
| 20263009 | ZOD only | 0.44% | 99.94% | 0.87% | 0.44% |
| 20263009 | A2D2 + ZOD | 8.18% | 76.19% | 14.78% | 7.98% |

All predeclared paired contrasts are retained, including the improvement of mixed over ZOD-only:

| Contrast | Metric | Mean paired change, pp | Seed range, pp | Conditional 95% day-group interval, pp |
|---|---|---:|---:|---:|
| ZOD − A2D2 | Precision | -26.85 | [-28.99, -25.67] | [-35.60, -18.12] |
| ZOD − A2D2 | Recall | +74.95 | [+72.10, +77.59] | [+67.75, +81.68] |
| ZOD − A2D2 | F1 | -24.93 | [-26.05, -24.20] | [-30.04, -17.75] |
| ZOD − A2D2 | IOU | -14.40 | [-15.12, -13.95] | [-17.89, -9.84] |
| Mixed − A2D2 | Precision | -18.92 | [-21.25, -15.65] | [-26.09, -12.62] |
| Mixed − A2D2 | Recall | +50.52 | [+45.17, +53.84] | [+43.84, +57.74] |
| Mixed − A2D2 | F1 | -10.82 | [-13.21, -8.64] | [-16.10, -5.40] |
| Mixed − A2D2 | IOU | -6.71 | [-8.07, -5.49] | [-10.13, -3.31] |
| Mixed − ZOD | Precision | +7.93 | [+6.02, +10.02] | [+4.96, +11.01] |
| Mixed − ZOD | Recall | -24.43 | [-26.93, -22.59] | [-31.92, -18.48] |
| Mixed − ZOD | F1 | +14.10 | [+10.98, +17.41] | [+9.17, +18.83] |
| Mixed − ZOD | IOU | +7.69 | [+5.89, +9.63] | [+4.85, +10.56] |

Intervals use **2,000 paired resamples of complete vehicle/day groups**, pooling counts within each seed and averaging the three paired differences. Every contrast uses the same group draws. They are conditional, descriptive intervals, **not adjusted for multiple contrasts**. They omit finite-seed population uncertainty, cross-day geographic correlation, label errors, coverage filtering and deployment uncertainty. Reuse of already scored evaluation data further prevents a fresh confirmatory claim. No result was used to select a seed, checkpoint, threshold, label or replacement source frame.

## False paint on no-paint and paint-positive scenes

Negative scenes are defined by zero ground-truth positive pixels after the unchanged input transform. Their background denominator is **7,161,127 valid pixels**; the 69 positive scenes contain **15,842,524 valid background pixels**. Ground-truth/frame/group identities match across all arms and seeds.

| Seed | Arm | No-paint frames with any FP / 31 | No-paint FP pixels | No-paint pixel FPR | FP pixels on 69 paint-positive frames |
|---|---|---:|---:|---:|---:|
| 20261009 | A2D2 only | 21 | 9,781 | 0.1366% | 40,154 |
| 20261009 | ZOD only | 31 | 4,049,337 | 56.5461% | 10,162,285 |
| 20261009 | A2D2 + ZOD | 31 | 111,704 | 1.5599% | 284,689 |
| 20262009 | A2D2 only | 24 | 8,738 | 0.1220% | 34,297 |
| 20262009 | ZOD only | 31 | 2,990,309 | 41.7575% | 6,738,807 |
| 20262009 | A2D2 + ZOD | 31 | 212,937 | 2.9735% | 471,862 |
| 20263009 | A2D2 only | 21 | 6,305 | 0.0880% | 27,693 |
| 20263009 | ZOD only | 31 | 4,046,060 | 56.5003% | 10,413,761 |
| 20263009 | A2D2 + ZOD | 31 | 165,531 | 2.3115% | 376,688 |

| Arm | No-paint pixel FPR, mean [range] | No-paint FP pixels, mean [range] | Positive-scene pixel FPR, mean [range] |
|---|---:|---:|---:|
| A2D2 only | 0.1155% [0.0880, 0.1366] | 8,274.67 [6,305, 9,781] | 0.2149% [0.1748, 0.2535] |
| ZOD only | 51.6013% [41.7575, 56.5461] | 3,695,235.33 [2,990,309, 4,049,337] | 57.4716% [42.5362, 65.7330] |
| A2D2 + ZOD | 2.2816% [1.5599, 2.9735] | 163,390.67 [111,704, 212,937] | 2.3844% [1.7970, 2.9785] |

ZOD-only marks **51.60%** of valid background pixels in no-paint frames as paint on average (41.76–56.55%), versus **0.1155%** for A2D2-only and **2.2816%** for mixed. Both ZOD-containing arms have at least one false-positive pixel in all **31/31** no-paint frames in every seed. A2D2-only does so in **21/31, 24/31 and 21/31**. ZOD-only also has **57.47%** background-pixel FPR on paint-positive scenes; the failure is not confined to blank scenes.

These are descriptive subset breakdowns with **no bootstrap interval claim**. Any-pixel incidence is sensitive to one pixel and is not a lane-level false-alarm rate. Pixel FPR is pooled FP/(FP+TN) within the named subset. No FP-size cutoff, new mask threshold or average blank-scene F1 was introduced.

## A2D2 development results

The 32 previously exposed A2D2 test images form one capture-date group; no group-bootstrap interval is available. Unlike the earlier A2D2-validation-selected experiment, the new final-epoch mixed result is close to baseline on average and its F1/IoU direction varies across seeds. ZOD-only remains far worse in all seeds.

| Arm | Precision, mean [range] | Recall, mean [range] | F1, mean [range] | IoU, mean [range] |
|---|---:|---:|---:|---:|
| A2D2 only | 70.10% [67.46, 72.55] | 58.03% [51.94, 61.58] | 63.33% [60.54, 65.07] | 46.37% [43.41, 48.22] |
| ZOD only | 1.63% [1.56, 1.78] | 99.99% [99.99, 100.00] | 3.21% [3.06, 3.49] | 1.63% [1.56, 1.78] |
| A2D2 + ZOD | 66.59% [62.97, 69.78] | 60.24% [57.38, 63.13] | 63.15% [62.98, 63.43] | 46.15% [45.96, 46.45] |

| Seed | Arm | Precision | Recall | F1 | IoU |
|---|---|---:|---:|---:|---:|
| 20261009 | A2D2 only | 67.46% | 61.58% | 64.39% | 47.48% |
| 20261009 | ZOD only | 1.57% | 100.00% | 3.08% | 1.57% |
| 20261009 | A2D2 + ZOD | 69.78% | 57.38% | 62.98% | 45.96% |
| 20262009 | A2D2 only | 70.28% | 60.58% | 65.07% | 48.22% |
| 20262009 | ZOD only | 1.78% | 99.99% | 3.49% | 1.78% |
| 20262009 | A2D2 + ZOD | 62.97% | 63.13% | 63.05% | 46.04% |
| 20263009 | A2D2 only | 72.55% | 51.94% | 60.54% | 43.41% |
| 20263009 | ZOD only | 1.56% | 100.00% | 3.06% | 1.56% |
| 20263009 | A2D2 + ZOD | 67.02% | 60.21% | 63.43% | 46.45% |

| Contrast | Metric | Mean paired change, pp | Seed range, pp | Conditional 95% day-group interval, pp |
|---|---|---:|---:|---:|
| ZOD − A2D2 | Precision | -68.46 | [-70.99, -65.90] | Unavailable: one group |
| ZOD − A2D2 | Recall | +41.96 | [+38.41, +48.06] | Unavailable: one group |
| ZOD − A2D2 | F1 | -60.12 | [-61.58, -57.48] | Unavailable: one group |
| ZOD − A2D2 | IOU | -44.74 | [-46.44, -41.86] | Unavailable: one group |
| Mixed − A2D2 | Precision | -3.51 | [-7.31, +2.31] | Unavailable: one group |
| Mixed − A2D2 | Recall | +2.20 | [-4.20, +8.26] | Unavailable: one group |
| Mixed − A2D2 | F1 | -0.18 | [-2.02, +2.89] | Unavailable: one group |
| Mixed − A2D2 | IOU | -0.22 | [-2.19, +3.04] | Unavailable: one group |
| Mixed − ZOD | Precision | +64.96 | [+61.19, +68.21] | Unavailable: one group |
| Mixed − ZOD | Recall | -39.76 | [-42.61, -36.86] | Unavailable: one group |
| Mixed − ZOD | F1 | +59.94 | [+59.56, +60.37] | Unavailable: one group |
| Mixed − ZOD | IOU | +44.51 | [+44.26, +44.89] | Unavailable: one group |

## Fixed population, supervision and compute

The retained ZOD population is unchanged: **812 training frames across 270 vehicle/day groups on 217 UTC dates**, and 100 evaluation frames across 20 groups/dates. Training comprises **796 positive-only frames and 16 assistant-reviewed complete-coverage frames**. Unknown pixels stay ignored. Original qualification excluded 212 training and 28 evaluation candidates without refill; full details and original QA history remain in the previous report. A2D2 retains 128 train / 32 validation / 32 test frames. No ZOD validation partition exists in this experiment.

Source-only assistant coverage QA is not independent human adjudication or proof of pixel-perfect labels. The original split purges evaluation days and all training days with any source frame within 250 m, using all 100,000 metadata rows. It does not apply multi-hop spatial closure; adjacent evaluation days may remain geographically correlated. This is a custom qualified subset, not the complete official benchmark or an unseen-region claim.

| Arm | Optimizer updates | A2D2 frame exposures | ZOD frame exposures | Mean exposures per training frame |
|---|---:|---:|---:|---|
| A2D2 only | 2,560 | 20,480 | 0 | A2D2: 160 |
| ZOD only | 2,560 | 0 | 20,480 | ZOD: 25.2217 |
| A2D2 + ZOD | 2,560 | 10,240 | 10,240 | A2D2: 80; ZOD: 12.6108 |

All use identically initialized heads within each seed, the same **3,457 trainable parameters**, frozen original detector features, 640 input, ten epochs × 256 updates × batch eight, AdamW learning rate 0.001 / weight decay 0.0001, positive-weight-20 BCE plus soft Dice, no augmentation and threshold 0.5. Selection is fixed at epoch 10 for all nine checkpoints. Seeds are 20261009, 20262009 and 20263009. Private video and retrospective labels never enter training or selection.

At the 640-pixel loss input, the 796 positive-only rows contribute **686,486 positive pixels and zero supervised negatives**. The 16 complete-coverage rows contribute **17,235 positives and 3,672,494 negatives**. A2D2 training contains **270,855 positives and 32,742,805 negatives**. These are unique cached-pixel counts before repeated sampling. Uniform frame sampling and pooled valid-pixel BCE/Dice do not give equal source or positive/negative gradient contributions. The head learns only on frozen early detector features; this is not an independently fine-tuned segmentation backbone.

## Interpretation and next priorities

The measured ZOD-only behavior is near-total paint recall with extensive background prediction. Sparse positive supervision and the current pooled/positively weighted loss are plausible contributors; only 16/812 ZOD training frames supply known negatives. The mixed arm recovers much of the precision lost by ZOD-only, while still regressing on ZOD against the A2D2 control. This is consistent with a supervision/loss imbalance but **does not isolate its cause** from source exposure, domains or frozen representation. The failure does not justify treating unknown ZOD pixels as background, discarding the dataset, or changing held-out thresholds.

1. **P1, #22:** qualify more complete-coverage ZOD training and validation scenes, including no-paint backgrounds, then predeclare controls for negative supervision and loss/source sampling balance. Keep unqualified pixels ignored. First test these changes with the same head to isolate the training recipe; a backbone fine-tune is a separate later comparison.
2. **P1, #10/#21:** reserve untouched acceptance data separately from this reused development set, and retain independent sequence truth for causal versus future-frame teacher qualification. Use development/validation data for model selection or calibration. A manual drawing tool is not required by this result; targeted independent coverage/correctness QA remains necessary.
3. **Conditional, #23/#24:** only a useful qualified candidate proceeds to archived-video soft-guidance replay and both-phone qualification. Preserve the existing frame/candidate lane recognizer and fallback. Still-image paint scores do not establish temporal lane geometry, retained paint support, false guidance, phone latency or user-visible recognition gains.

A2D2-only remains a development control; no arm is qualified for production by this experiment. No further fitting, threshold adjustment or device activation is part of this completed experiment. The earlier A2D2-validation-selected results are preserved with their own protocol and must not be pooled with these final-epoch results.

## Verification and retained evidence

Independent recomputation passes **702 numeric checks**, reproducing all per-seed and arm metrics, every contrast, all 24 ZOD interval endpoints, and the ground-truth-defined false-positive breakdown. The maximum arithmetic difference is **1.11 × 10⁻¹⁶** (rounding). The audit uses independent scalar count calculations and percentile arithmetic; it does not call the production summary calculations.

All **nine checkpoints** independently deserialize with `weights_only=True`. Each contains exactly eight finite float32 tensors / 3,457 parameters. Embedded source/config/proof identities, epoch-10 provenance and that epoch’s validation values, update/exposure budgets and source isolation match the saved artifacts. All 108 manifest-listed payload files were rehashed. Recorded initialization hashes agree within each seed and differ across seeds; all nine saved heads differ. Initial tensors were not regenerated, and training, detector inference and the detector probe were not rerun in this final audit.

The saved detector file and tensor hashes remain identical, all parameters are frozen and modules in eval, and the recorded same-input output probe has maximum absolute difference zero for every seed. This is backend-specific preservation evidence, not proof of arbitrary exported/mobile outputs. The host feature cache contains 1,104 frames and 14,470,348,800 tensor bytes. CUDA seeded mode records its reproducibility limits; no cross-stack bitwise guarantee is claimed.

Training code is pinned to **`764d6cd49d5ea3a3c283689e975ca0f4787ff0dd`**. Before launch, **256 repository tests passed with three existing local media-dependency skips**, plus 24 execution-guard and 14 preservation tests. Android, DCO and protected speed-reference CI pass; iOS retains the existing `SpeedPenaltyRules.swift:590` compiler type-check timeout and dependent applicability checks are skipped. The final report changes documentation only.

The primary archive contains **108 artifacts plus the preservation manifest**, **16,270,108 extracted bytes** including the manifest, and a **16,455,680-byte tar**. It contains all nine checkpoints, three seed reports, combined summary, logs, immutable plan, protocol, tested execution/preservation helpers and source provenance. Every file was hash-checked during canonical installation and independently verified afterward. Original archives, QA and masks remain in their already verified source storage. The code archive is hash-verified separately and referenced by the result manifest.

| Identity | SHA-256 |
|---|---|
| Frozen protocol | `03fb33c8adc1ddc905cfd5741619f333b4cdb54525f6d90fa6ba9d06b610d741` |
| Operational plan | `6ef204d0230d5b7945d641c91bf0cd7a382e41864500d579ef193fc9c5341f29` |
| Qualified ZOD manifest | `b103decad1fc5fa461153f7f304f8ff9d667cb82f58733460b283f55c65f2bb0` |
| Frozen detector | `698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a` |
| Training source archive | `6cd1e64934da8414439c96d871ca5bc0afd865ba6506caf076d68ba572451828` |
| Combined summary | `c7f8fff150e86094ffe4beea02f8fe6ff35463d58b3f3ad15252c06f63594de3` |
| Canonical primary tar | `52251f9855256268575ae0215c0edd92917e647006d0a7ea3147bdd8c821f018` |
| Canonical primary manifest | `8518d4ba1765f65b4de10c5e67b1ad5299756eb4b804739326080563a466e9be` |

Independent audits and this report are retained separately alongside the immutable primary evidence. No private imagery, access URL or weights are committed to Git. See [CORPUS.md](../scripts/lanes/CORPUS.md) for reproduction and [PR #25](https://github.com/volzinnovation/youspeed.de/pull/25) / issues #6, #10 and #22 for tracked decisions.
