# Scaled ZOD lane-paint comparison — 2026-10-09

The fixed A2D2 + ZOD recipe regressed paint precision, F1 and IoU in **all three seeds on both evaluated corpora**. It increased recall but predicted substantially more false paint. **Do not promote these mixed checkpoints.** The data/import/training workflow is operational; this result does not qualify useful lane-recognition guidance or establish that ZOD itself is unsuitable.

All three comparisons and the combined summary completed with exit code 0, from 08:28:41 to 09:06:30 UTC (37.81 minutes including validation, feature preparation and scoring). They ran sequentially on KI GPU 2 with detached supervision, fixed deadlines and a pinned container. The complete result archive is verified on volz-db. No phone model, runtime setting or protected speed-reference policy was changed.

**Primary ZOD results.** The retained holdout contains 100 still frames across 20 vehicle/day groups on 20 UTC dates. There are 69 frames with visible labeled paint and 31 with no visible labeled paint. These are valid-pixel pooled metrics within each seed, then arithmetic means across all three seeds. Ranges describe fitted-seed variation; pp means percentage points.

| Metric | A2D2 only, mean [seed range] | A2D2 + ZOD, mean [seed range] | Paired change, pp [conditional 95% interval] |
|---|---:|---:|---:|
| Precision | 26.85% [26.40, 27.61] | 9.37% [8.51, 10.25] | -17.48 [-23.96, -11.83] |
| Recall | 28.90% [24.50, 33.69] | 73.69% [72.31, 75.99] | +44.79 [+39.07, +50.79] |
| F1 | 27.75% [25.48, 30.35] | 16.61% [15.30, 17.97] | -11.13 [-15.99, -6.14] |
| IoU | 16.12% [14.60, 17.89] | 9.06% [8.29, 9.87] | -7.06 [-10.27, -3.86] |

Every fitted seed is included:

| Seed | Arm | Precision | Recall | F1 | IoU |
|---|---|---:|---:|---:|---:|
| 20261009 | A2D2 only | 26.40% | 28.49% | 27.40% | 15.88% |
| 20261009 | A2D2 + ZOD | 8.51% | 75.99% | 15.30% | 8.29% |
| 20262009 | A2D2 only | 26.54% | 24.50% | 25.48% | 14.60% |
| 20262009 | A2D2 + ZOD | 9.35% | 72.31% | 16.56% | 9.03% |
| 20263009 | A2D2 only | 27.61% | 33.69% | 30.35% | 17.89% |
| 20263009 | A2D2 + ZOD | 10.25% | 72.77% | 17.97% | 9.87% |

The 95% intervals use 2,000 paired resamples of the 20 whole vehicle/day groups. Each draw uses the same sampled groups for both arms and all three fitted seeds, pools counts within each seed, and averages the three paired differences. These are **conditional, descriptive intervals**. They omit cross-day geographic correlation, seed-population uncertainty, label errors, assistant-QA filtering and deployment uncertainty. They do not constitute a preapproved release gate or a multiple-metric significance claim. An independent calculation reproduced every reported metric and every bootstrap interval with zero arithmetic difference.

**False paint on negative scenes.** The same source-bound frame identities and ground-truth/validity pixel counts match across all six evaluations. Negative scenes are defined solely by zero ground-truth positive pixels; no new prediction threshold or FP-size cutoff was introduced.

| Seed | Arm | No-paint frames with any FP / 31 | FP pixels on no-paint frames | No-paint pixel FPR | FP pixels on 69 paint-positive frames |
|---|---|---:|---:|---:|---:|
| 20261009 | A2D2 only | 22 | 9,846 | 0.1375% | 40,565 |
| 20261009 | A2D2 + ZOD | 31 | 158,553 | 2.2141% | 359,951 |
| 20262009 | A2D2 only | 24 | 8,738 | 0.1220% | 34,297 |
| 20262009 | A2D2 + ZOD | 31 | 131,098 | 1.8307% | 313,744 |
| 20263009 | A2D2 only | 25 | 10,630 | 0.1484% | 45,399 |
| 20263009 | A2D2 + ZOD | 31 | 117,941 | 1.6470% | 286,142 |

Across seeds, negative-scene pixel FPR rises from **0.1360%** (0.1220–0.1484%) to **1.8972%** (1.6470–2.2141%): mean paired increase **1.7613 pp**, range 1.4985–2.0766 pp. Negative-scene FP pixels average **9,738 → 135,864**. FP pixels on the 69 positive scenes also rise, **40,087 → 319,945.67** on average (paired increase 279,858.67), so the failure is not confined to the no-paint subset.

The mixed arm produces at least one FP pixel in **31/31** no-paint frames in every seed, versus **22/31, 24/31 and 25/31** for baseline. Any-pixel incidence is sensitive to one predicted pixel; it is not a lane-level false-alarm rate or unsupported-display duration. Pixel FPR is pooled FP / (FP + TN) over valid background pixels in the named subset. The negative-scene breakdown is descriptive and is **not covered by the primary metric bootstrap intervals**.

**Secondary A2D2 results.** The 32 A2D2 test images were exposed in earlier development and belong to one heldout group. They are descriptive; no day-group interval is available.

| Metric | A2D2 only, mean [seed range] | A2D2 + ZOD, mean [seed range] | Paired change, pp |
|---|---:|---:|---:|
| Precision | 68.24% [66.99, 70.28] | 60.67% [59.21, 62.04] | -7.57 |
| Recall | 62.06% [60.58, 63.36] | 64.65% [63.05, 66.91] | +2.59 |
| F1 | 64.98% [64.74, 65.13] | 62.58% [61.07, 63.68] | -2.39 |
| IoU | 48.13% [47.87, 48.29] | 45.55% [43.96, 46.71] | -2.57 |

The scaled baseline and mixed runs use different budgets and cohorts from the earlier 8-train/2-test ZOD mini smoke. The mini's apparent gain is not directly comparable and does not override this larger result.

**Frozen population and training procedure.** Metadata-only selection fixed 1,024 ZOD train candidates and 128 official-validation candidates before image QA or model scores. Source-only coverage, parser and input-geometry checks retained **812 train frames across 270 vehicle/day groups on 217 UTC dates**, plus the 100-frame holdout. Training has **796 positive-only frames and 16 assistant-reviewed complete-coverage frames**. Excluded train candidates comprise 5 review exclusions, 63 invalid annotations and 144 without eligible positive supervision; 28 heldout candidates were excluded. There was no refill or metric-driven exclusion. All 160 fixed QA candidates have decisions: 147 rendered original/overlay panels were inspected, and 13 reviewed candidates failed parsing. This is assistant coverage QA, not independent human adjudication or pixel-perfect truth.

The split graph uses all 100,000 source records. Training excludes heldout vehicle/UTC-day groups and every day group with any source frame within 250 m of a heldout day's frames. The initial transitive-component design was infeasible on metadata alone and remains preserved. The implemented direct-adjacency design has no multihop closure. Previously exposed whole days are excluded from holdout, but neighboring unselected days may contain prior analyst exposure. Heldout days can be geographically correlated; neither unseen regions nor complete route independence is established.

Both arms use the same fully frozen detector and identically initialized 3,457-parameter paint head per seed, 640-pixel input, ten epochs, 256 updates per epoch and batch eight. Threshold stays at 0.5. The earliest maximum **A2D2 validation IoU** selects checkpoints; ZOD is scored afterward. Selected baseline/mixed epochs are **9/7, 10/5 and 8/4** for seeds 20261009, 20262009 and 20263009. All curves contain ten epochs, and the independent audit verified each selection.

Each arm gets 2,560 updates and 20,480 frame exposures. Baseline receives 20,480 A2D2 exposures; mixed receives 10,240 A2D2 plus 10,240 ZOD. A2D2 retains 128 train / 32 validation / 32 test frames. The source mixture therefore halves A2D2 exposure. Equal source frame counts do not mean equal loss or gradient contributions: loss pools valid-pixel BCE with positive weight 20 plus soft Dice. Unknown ZOD pixels remain ignored. At the 640-pixel loss input, positive-only ZOD rows provide 686,486 valid positive pixels; the 16 complete rows provide 3,689,729 valid pixels, including 3,672,494 negatives. Private recordings and retrospective labels never enter training or checkpoint selection.

**Interpretation and next priorities.** The measured behavior is excessive paint prediction at the fixed threshold. Sparse positive supervision, source loss balance, reduced A2D2 exposure, domain differences and checkpoint selection are possible contributors; this experiment does not isolate their causal effects. The auxiliary-paint concept and preserving the existing lane recognizer remain separate from adopting this particular checkpoint.

1. **P1, #22:** predeclare development/validation controls for complete-label negative supervision, per-source loss normalization and A2D2 exposure. Use independently qualified source negatives; keep unknown pixels ignored. Calibrate on development/validation data only. Reserve a new untouched holdout before any follow-up fitting; the 100 scored frames are now development evidence. More epochs or indiscriminate expansion of the same sparse recipe is not the next gate.
2. **P1, #10/#21:** continue independent sequence truth, causal versus future-frame teacher qualification and the recorded candidate-opportunity experiment. Still-image paint scores do not establish temporal geometry or end-to-end selection benefit.
3. **Conditional, #23/#24:** retain default-off semantic delivery and established fallback behavior. New model export, live integration and both-phone field qualification depend on useful recognition evidence. This experiment does not close those issues or authorize model promotion.

**Verification and retained evidence.** Each run preserves exact detector checkpoint/state hashes, all parameters frozen and modules in eval, and a same-input detector probe with maximum absolute difference zero. This proves preservation of the recorded file/state and probe on this backend; it is not a proof of every exported output or mobile runtime behavior. The feature cache contains 1,104 frames and 14,470,348,800 bytes of retained tensors. CUDA seeded mode records its determinism limitations; no cross-stack bitwise guarantee is claimed.

Training code is pinned to commit `6dfcffe63e5a2691056d85cabc7743c7a7217ecc`; the later documentation commit does not change that experiment identity. Qualification before launch passed **234 tests**, with three existing local ffprobe/x265 skips; external execution guards passed 18 tests and preservation helpers passed 13. Android CI, DCO and protected speed-reference checks passed on the training commit. iOS CI retained the pre-existing `SpeedPenaltyRules.swift:590` compiler timeout. No additional training or runtime tests are implied by this report-only change.

The full 50.05 GB original source archives, selected originals, source QA and generated masks are retained on volz-db. Completed results are stored separately under `zod/2026-10-09-scale/comparison-scale-v2-results`: **103 artifacts plus the preservation manifest**, 15,704,590 extracted bytes, with a 15,882,240-byte tar. Contents include all three seeds, summary, immutable plan, code provenance, logs, guard helpers and failed operational preflight history. Every archive member was hash-checked during canonical installation and independently revalidated. The earlier preflight failure preceded container creation and training; only Docker diagnostic capitalization handling changed.

| Identity | SHA-256 |
|---|---|
| Operational plan | `a4ff789b5eef1b87c1f84bf4c8534bea8f4b9958149fd05f57543a5f09e6b80e` |
| Qualified ZOD manifest | `b103decad1fc5fa461153f7f304f8ff9d667cb82f58733460b283f55c65f2bb0` |
| Original detector | `698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a` |
| Final combined summary | `a43b72d2eccbd7ed324182d8ed12722538efc654bd92c5289052b64f49061026` |
| Canonical results tar | `6e2d60f9dc6a2c6866d19903fe867720fdd53a23024f73cadfe17450ebaab5e9` |
| Canonical preservation manifest | `319cfe90a3934284c9cd6c1521384623e6fc119d370fe306fb7a40703d8d9326` |
| Independent audit | `6634f3eebde628935dd45987590a11b585e07139986d035bf27f02bb5990f123` |
| Negative-scene derivation | `400109b2e0dc4b229cf691ac19005392ad96ffa9f5f9fbb3909d5addac268320` |

The independent audit, reproducible negative-scene derivation, verified inputs and report are preserved separately as final analysis alongside the immutable primary evidence. No private imagery, access URL or model weights are committed to Git. Reproduction tools and protocol are described in [CORPUS.md](../scripts/lanes/CORPUS.md); tracked work remains in #6, #10 and #21–#24 and draft PR #25.
