The overnight experiment is complete. **Keep the original French classifier in the apps.** Thirteen additional training runs produced modest, repeatable improvements on the development crops, but none improved B31/B33 recognition. Some candidates introduce errors on other speed signs, and the candidates with the highest clean accuracy lose end signs in darkened images. No checkpoint was exported, published or deployed.

The server queue ran from 24 September 21:41:24 UTC to 25 September 05:34:18 UTC (23:41–07:34 French time), stopping before the authorized 05:41:24 UTC / 07:41 deadline. That interval includes waiting for the initial pilot. The final run used a shorter budget to reserve evaluation time; the queue then stopped with about seven minutes remaining. All 13 training containers and their 13 evaluation containers exited with code zero. The two original/pilot comparison containers also exited successfully. At 05:46 UTC no queue containers or supervisor remained running. The hourly follow-up automation was paused after final verification.

Training used only physical GPU 2 on the KI server. Four additional runs completed 30 epochs; eight reached their planned time limits after 12 complete epochs, and the final run completed six epochs. Partial checkpoints are retained separately. These planned budget stops are not runtime failures. The original 15-epoch pilot is also preserved. The source checkpoint SHA-256 was verified unchanged at completion.

The table reports top-1 accuracy (%) on the same 7,939 validation crops in each column. “32px” and “64px” reduce resolution before resizing to the classifier input; blur and darkness are synthetic transforms. Scores use the published labels without applying the discovered label correction. Each row uses its selected training checkpoint, not necessarily the final epoch.

| Candidate | Update scope; learning rate; augmentation | Seed | Clean | 32px | 64px | Blur | Dark |
|---|---|---|---:|---:|---:|---:|---:|
| original | Original, unchanged | — | 99.660 | 98.829 | 99.647 | 99.673 | 99.610 |
| initial-pilot | Full; 1e-4; none | 20260924 | 99.043 | 97.771 | 99.030 | 99.005 | 98.778 |
| run-01 | linear; 1e-05; none | 20260924 | 99.698 | 98.929 | 99.735 | 99.723 | 99.647 |
| run-02 | frozen-bn; 1e-05; none | 20260924 | 99.710 | 99.018 | 99.660 | 99.660 | 99.622 |
| run-03 | frozen-bn; 3e-06; yes | 20260924 | 99.773 | 99.484 | 99.710 | 99.698 | 99.673 |
| run-04 | linear; 3e-05; yes | 20260924 | 99.710 | 99.043 | 99.710 | 99.723 | 99.647 |
| run-05 | full; 3e-06; none | 20260924 | 99.811 | 99.080 | 99.786 | 99.786 | 99.005 |
| run-06 | frozen-bn; 1e-05; yes | 20260924 | 99.673 | 99.257 | 99.647 | 99.698 | 99.584 |
| run-07 | linear; 1e-05; none | 20260925 | 99.698 | 98.942 | 99.735 | 99.735 | 99.673 |
| run-08 | frozen-bn; 1e-05; none | 20260925 | 99.710 | 98.980 | 99.647 | 99.660 | 99.698 |
| run-09 | frozen-bn; 3e-06; yes | 20260925 | 99.773 | 99.383 | 99.748 | 99.748 | 99.735 |
| run-10 | linear; 3e-05; yes | 20260925 | 99.710 | 99.080 | 99.698 | 99.723 | 99.723 |
| run-11 | full; 3e-06; none | 20260925 | 99.824 | 99.080 | 99.786 | 99.798 | 99.043 |
| run-12 | frozen-bn; 1e-05; yes | 20260925 | 99.698 | 99.282 | 99.622 | 99.622 | 99.647 |
| run-13 | linear; 1e-05; none | 20260926 | 99.673 | 98.866 | 99.685 | 99.698 | 99.622 |

“Linear” updates only the existing output layer. “Frozen-bn” updates model weights while keeping batch-normalization running statistics fixed. All runs retain the original 256-class output order and start from the pinned original weights. Augmentation is train-only downsampling, blur and brightness adjustment; there are no crops, flips or stripe rotations.

Runs 03 and 09 are the strongest repeated configuration for further investigation: frozen batch-normalization statistics, learning rate 3e-6, and degradation augmentation. Both improve aggregate accuracy in all five variants. Their clean scores improve by nine correct crops; their 32px scores improve by 52 and 44 correct crops respectively. However, both lose a clean B14-110 example that the original gets right (59/60 instead of 60/60). Run 03 also loses a low-resolution B14-70 example, and run 09 loses an additional dark B14-30 example. These are comparisons against published labels; those newly regressed crops have not received a visual label audit. Aggregate gains do not establish per-class non-regression.

Runs 05 and 11, which update the full model without augmentation, have the highest clean scores but reproducibly regress in darkness. Both lose two end signs: a B33-50 becomes B14-50, and a B33-70 becomes AB4. The B33-50 error has confidence 0.7853 in run 05 and 0.9806 in run 11, so a simple confidence cutoff would not eliminate it. Their dark end-family recall falls from 100% to 98.9189%, and their total dark accuracy is below the original. The initial higher-learning-rate pilot also regresses across all five aggregate tests and loses an additional B33-70 at 32px.

**B31/B33 outcome:** the original and every selected overnight checkpoint score 184/185 exact-label matches on clean crops, with target macro F1 0.98655. The original correctly identifies 29/29 B31 crops. For B33 the published-label counts are 59/60 for B33-30, 30/30 for B33-50, 58/58 for B33-70 and 8/8 for B33-90. The sole clean mismatch is shared by every candidate: the crop labeled B33-30 visibly shows an end-of-90 sign and is classified as B33-90. The [label audit](TSR_FR_END_SIGN_LABEL_AUDIT.json) records its hash and the visual finding. No running labels or scores were changed to improve results.

On these sign-crop evaluations, end-family precision is 100% for every evaluated checkpoint and variant: there are no non-end crops classified into the B31/B33 family. End-family recall stays 100% except for the initial pilot at 32px and runs 05/11 in darkness. This does **not** measure false positives on arbitrary roadway backgrounds or the detector's ability to find a sign in a full frame. Apart from the documented regressions, target results remain unchanged under all stress variants.

The evidence has significant limits. The split comes from the source model's published training archive, so the original model may already have seen these crops. Duplicate grouping prevents new train/validation leakage within this experiment but cannot undo source-model exposure or guarantee independence by physical sign or route. There are only 185 target crops, including eight B33-90 crops, and one confirmed label error. Repeated checkpoint selection on this development split can overfit it. Synthetic darkness and blur are diagnostic tests, not a substitute for night driving or independent footage. Only the crop classifier was trained; proposal detection and mobile tracking/admission logic were unchanged. Therefore this experiment cannot establish that the missed end signs during the user's drives have been fixed.

The next useful work is to:

1. Build a separately reviewed, route-separated B31/B33 full-frame evaluation set from the existing drive footage and licensed Panoramax imagery. Include missed signs, distant/small signs, poor light and confusing non-sign backgrounds, with bounding boxes and passage timestamps.
2. Measure detector recall before classification and trace each miss through crop classification and mobile observation/confirmation. Prior drive-log evidence points to weak or missing proposals, which classifier-only training cannot repair.
3. Correct the known crop label in a versioned audit and review other disputed labels. Preserve the raw benchmark and report corrected-label results separately; do not use the independent test set for training or checkpoint selection.
4. Compare original detector candidates and image-resolution choices on the reviewed full frames. Train a detector only once there are sufficient reviewed boxes and negatives. If revisiting classifier training, evaluate runs 03/09 on independent footage and specifically recheck other speed-limit classes before any mobile export.

The full checkpoints, optimizer states, per-epoch metrics and error lists remain on `raphael@141.47.5.55` under `/mnt/nvme/youspeed-tsr-fr-end-signs-20260924/`. Candidate paths are `overnight/run-NN/weights/best.pt`; evaluation paths are `overnight/run-NN-eval/`. The original remains `source/best.pt`. The [collected metrics](TSR_FR_END_SIGN_OVERNIGHT_METRICS.json) retain launch/finish state, checkpoint hashes, all aggregate and target-class results, target error paths and per-class regression lists. Full per-class metrics were also downloaded to `.codex-tmp/fr-end-sign-training/overnight-final-results.json`. The [training record](TSR_FR_END_SIGN_TRAINING.md) documents source hashes, preparation, validation and hourly reviews.

Report validation checked that all 13 run/evaluation exit codes are zero, every checkpoint has all five evaluation variants with 7,939 samples, no queue container remains running, and no clean target score exceeds the original. The report table was generated directly from the collected metrics.
