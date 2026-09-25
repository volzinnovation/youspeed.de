# French B31/B33 training pilot — 2026-09-24

This experiment adapts the existing French **crop classifier**, emphasizing B31
and B33 while retaining the original head and other sign classes. It does not
change the proposal detector, model packs, or installed iPhone/Android apps.

## Sources and validation

- Dataset: `Panoramax/classified_fr_road_signs`, revision
  `ea75988e381f16e4677c5f42aa5fedea005f23d6`, `train.zip`.
  SHA-256: `2cd16ce20ff6675de9a14b2a7362a0f27acf5d84df8543e0dfad445e65ecd538`.
- Initial classifier: `Panoramax/classify_fr_road_signs`, revision
  `7f2bdd58f20b3dfc7161c5aea7c672ce02749c8f`, `best.pt`.
  SHA-256: `5e70142feffd01ac15ce4f1fc2c3ce929a6dadb7c71ccf06ea20059ca5757641`.
- Archive inventory: 52,941 images, 258 class folders, including 1,234 B31/B33
  examples. The original checkpoint has **256 outputs**. Archive-only labels
  `B6D-M6j` (55 crops) and `B6d-M4b` (7 crops) were quarantined, not added to the model head.
  The final dataset has 48,087 training samples after oversampling and 7,939
  validation crops (including 185 B31/B33 crops).
- Every image is decoded and inventoried. Byte/pixel/perceptual duplicate groups
  remain on one side of a seeded 85/15 development split. Conflicting labels are
  quarantined. B31/B33 training samples are repeated four times *after* splitting;
  validation samples are never oversampled.
- Crop filenames lack reliable route/physical-sign IDs. The initial model may
  already have seen these crops. Consequently this development benchmark is not
  independent route validation or proof that missed detector proposals improved.
- Full-image RGB resize to 224×224 preserves the stripe. No random crop, erasing,
  rotation, or flip is used. AdamW starts at 0.0001 with a cosine schedule.

The real checkpoint was tested on RTX A5000 using torch 2.6.0+cu126,
torchvision 0.21.0+cu126 and Ultralytics 8.4.56. Forward, backward, optimizer
update, and atomic checkpoint reload passed. Reloaded logits matched exactly;
the original source checkpoint remained unchanged. This disposable two-image
smoke checkpoint is not a trained candidate.

## Server run

Host: `raphael@141.47.5.55` (`wingki01`). Physical **GPU 2**, RTX A5000, is mapped
to CUDA device 0 inside the isolated training container. Other workloads are not
stopped or reconfigured. The container uses eight CPU cores, 16 GiB host memory,
and 2 GiB shared memory. Its training phase has no network access.

Run root: `/mnt/nvme/youspeed-tsr-fr-end-signs-20260924/`.
Container name: `youspeed-fr-b31-b33-20260924`.
Launched at server UTC `2026-09-24T21:10:58.82301593Z`; container ID
`f64799c5550ac7d160a49ba8608ab876e2f77b4de282a881f395aaf7a7714295`.
The source/dataset hashes and full run record are retained in
`job/run-record.json` on the server.
Parameters: 15 epochs, batch 32, four data workers, seed 20260924, 3.25-hour
training budget. Training progress and all epoch/best/last checkpoints remain on
NVMe and survive an SSH/VPN disconnect. No Hugging Face job was launched.

The server image `youspeed-tsr-fr-end-training:20260924` extends the existing
`woladen-prolix:2ad3c2382d` runtime with Ultralytics 8.4.56. The base image ID
checked before building was
`sha256:c1e51a1cb1195b4471a530e7484f9bd8c3163ad7150c26207c077c1f93727607`.
The exact Dockerfile, source scripts and launch command are retained in `job/`.

```sh
ssh raphael@141.47.5.55 'docker logs --tail 20 youspeed-fr-b31-b33-20260924'
ssh raphael@141.47.5.55 'cat /mnt/nvme/youspeed-tsr-fr-end-signs-20260924/training/training-summary.json'
```

Inspect baseline versus best-epoch target precision/recall, false positives and
all-class regression before considering export. `training/` contains baseline,
per-epoch and best metrics, `metrics.jsonl`, configuration, and `weights/`.
`data-v2/` contains the inventory, split provenance and dataset summary. The
older `data/` is the original archive audit before the vocabulary correction.

## Reproduction tools

```sh
python3 scripts/tsr/prepare_fr_end_sign_training.py \
  --archive train.zip --model-vocabulary model-vocabulary.json \
  --output data-v2 --validation-fraction 0.15 --seed 20260924

python3 scripts/tsr/train_fr_end_sign_classifier.py \
  --data data-v2 --model best.pt --output training \
  --device 0 --epochs 15 --batch 32 --imgsz 224 --seed 20260924 \
  --workers 4 --max-hours 3.25
```

The vocabulary JSON is exported from the pinned checkpoint's ordered `names`.
The trainer rejects changed output counts, reordered labels and source-weight
hash mismatches. Target per-class and end-family metrics are reported alongside
all-class top-1/top-5 metrics. Checkpoint selection favors target macro F1 with
overall top-1 as tie-break; a reported regression flag is not a release approval.

Validation: 16 tests passed (plus four parametrized subtests), and the real GPU
forward/backward/save/reload smoke passed. The final dataset inventory SHA-256 is
`72385f999e60e6d57fea3a3861dbc6445e0d0f76de582e31549aaabbc8e91802`.

## Eight-hour follow-up queue

Authorized on 24 September after the initial pilot showed no target gain and
all-class regression. The detached server supervisor launched at **21:41:24 UTC**
(23:41 French time) and has an absolute deadline of **25 September 05:41:24 UTC**
(**07:41 French time**). It waits for the initial pilot, then uses physical GPU 2
sequentially; training and evaluation survive a Mac/VPN disconnect.

The queue compares lower learning rates (3e-6, 1e-5, 3e-5), linear-head-only
updates, full updates with frozen batch-normalization statistics, and full model
updates. Selected runs add train-only downsampling, blur and brightness changes;
there are no crops, flips or stripe rotations. Six configurations repeat across
three seeds as the budget permits, each starting from the pinned original model.
A run receives at most 40 minutes including checkpointing, with remaining time
reserved for evaluation. This is a maximum budget, not a promise to finish all
18 configurations. Two consecutive training failures stop the queue.

Every trained candidate and the original undergo the same five full-vocabulary
validation passes: clean, 32-pixel and 64-pixel downsampling, Gaussian blur and
reduced brightness. Per-class metrics and individual misclassified crop paths
are saved for inspection. These synthetic stress tests do not establish detector
recall or independent route performance. Candidates are explicitly compared with
the original; a target gain cannot silently mask all-class regression. No model
is automatically exported, published or installed.

Supervisor PID at launch: `989607`. Server `job/overnight-launch.json` preserves
the launch time and deadline. `overnight/status.json` records live state and
paired candidate comparisons; `overnight/*-eval/` contains full evaluation and
error reports. `logs/overnight-supervisor.log` records supervisor exceptions;
individual container logs are in `overnight/`. The original pilot is retained.

```sh
ssh raphael@141.47.5.55 'cat /mnt/nvme/youspeed-tsr-fr-end-signs-20260924/overnight/status.json'
```

Tools: `scripts/tsr/run_fr_end_sign_overnight.py`,
`scripts/tsr/evaluate_fr_end_sign_robustness.py`, and the extended trainer.
Validation before launch: 18 tests plus four subtests passed. A real-checkpoint
CPU smoke test verified gradients update the linear head in all three modes,
linear-only mode preserves backbone weights, frozen modes preserve batch-normalization
statistics, and all five stress transforms produce finite RGB tensors. This
smoke test used no GPU and did not modify source weights.

### First hourly review — 24 September 22:43 UTC

The initial pilot completed 15 epochs. Its selected checkpoint scored 99.0427%
clean top-1 against the original 99.6599%; it remains a regression. Overnight
run-01 (linear head, 1e-5, 30 epochs) completed and scored 99.6977%, three more
correct crops out of 7,939. All five B31/B33 stress-test results remained unchanged;
end-family precision and recall were 100% on this development set. Run-02
(frozen batch-normalization statistics, 1e-5) was progressing through epoch 4.
No runtime failures were reported; the original deadline remains in force.

Visual inspection of the sole target-class error found a dataset label error:
`val/B33-30/025658-c8e99f20d041dea9.jpg` visibly shows an end-of-90 sign, and
both original and run-01 predict B33-90. Its published label is B33-30.
`TSR_FR_END_SIGN_LABEL_AUDIT.json` records the crop hash and inspection. The
running split and scorer were deliberately kept unchanged. This apparent metric
ceiling reinforces the need for independently labeled, difficult full-frame
examples; it does not establish that the detector recognizes those signs on-road.

### Second hourly review — 24 September 23:43 UTC

Run-02 stopped normally at its per-run time budget, preserving 12 completed
epochs and a partial epoch 13. Its selected epoch 10 passed all five evaluation
passes: clean accuracy 99.7103% (four more correct than the original), 32-pixel
accuracy 99.0175% (15 more correct), and one fewer correct on the blur test.
B31/B33 metrics stayed unchanged across all variants: 184/185 exact-label
matches, with end-family precision and recall both 100% and no false end-family
predictions. The previously documented mislabeled end-of-90 crop remains in the
unchanged benchmark. Improvements are small development-set differences, not
independent evidence of better road recognition.

Run-03 (frozen batch-normalization statistics, 3e-6, train-only degradation) was
progressing through epoch 11. Its best clean checkpoint so far was 99.7481%,
with unchanged target F1; its paired stress evaluation was still pending. The
supervisor had no logged exceptions and server NVMe had about 1.3 TiB free.
No repair or queue change was needed. The deadline remains 05:41 UTC.

### Third hourly review — 25 September 00:44 UTC

Four overnight runs have finished training and all five paired evaluations with
exit code zero. Run-03 reached its planned time limit after 12 complete epochs;
its selected checkpoint improved clean accuracy to 99.7733% (+9/7,939 correct)
and 32-pixel accuracy to 99.4836% (+52 correct versus original). It also improved
64-pixel, blur and dark accuracy by 5, 2 and 5 correct crops respectively. These
are aggregate improvements; they do not establish per-class non-regression.
Run-04 completed 30 epochs, scoring 99.7103% clean, with positive aggregate
changes across all five evaluation variants.

B31/B33 exact-label results, family precision/recall and false end-family counts
remain unchanged in both evaluated candidates. The target-label error found in
the first review still limits interpretation. Run-05 (full model, 3e-6, no
augmentation) was progressing through epoch 7; its best clean checkpoint so far
was 99.8111%, with stress evaluation pending. No runtime failures or supervisor
exceptions were reported. No repair, deployment, or queue change was made.
The original 05:41 UTC deadline remains active.

### Fourth hourly review — 25 September 01:44 UTC

Six overnight runs finished training and all paired evaluations without runtime
failures. Run-07 is the first repetition with seed 20260925 and was progressing
through epoch 2. The supervisor log remained empty; no repair was required.

Run-05 illustrates why clean accuracy alone cannot select a replacement. Its
selected epoch 1 achieved the highest completed clean accuracy so far, 99.8111%
(+12 correct versus original), but dark accuracy fell to 99.0049% (-48 correct).
On dark crops it additionally missed two end signs: B33-50 became B14-50 at
0.7853 confidence, and B33-70 became AB4 at 0.0603 confidence. End-family recall
fell from 100% to 98.9189%; family precision stayed 100%. Target exact-label
matches fell to 182/185, including the previously documented label error.
This candidate should not replace the original on the present evidence.

Run-06 scored 99.6725% clean (+1 correct), improved 32-pixel accuracy by 34
correct crops, and lost two correct dark crops. Its B31/B33 results remained
unchanged. Run-03 remains the strongest completed candidate for further study
across these five aggregate tests: it improves every aggregate accuracy while
preserving target metrics. That does not prove per-class or on-road improvement.
All candidates remain experimental, and the deadline remains 05:41 UTC.

### Fifth hourly review — 25 September 02:44 UTC

Seven overnight runs have completed training and paired evaluation without
runtime failures. Run-07 repeats run-01 with a second seed: its clean accuracy
again equals 99.6977% (+3 correct versus original), with positive aggregate
changes in all four stress variants (+9 at 32 pixels, +7 at 64 pixels, +5 blur,
+5 dark). All target metrics remain unchanged, with no false end-family
predictions in these crop evaluations. This supports repeatability of the small
linear-head gains on the existing split, not generalization to unseen routes.

Run-08 was progressing through epoch 10. Its best clean checkpoint is 99.7103%,
while the latest completed epoch has fallen to 99.5339%; the earlier best is
preserved for evaluation. Target results remain unchanged. The supervisor has
no logged exceptions, no repair was necessary, and the queue remains within the
original 05:41 UTC deadline. The previous dark-regression finding for run-05
still prevents treating its high clean score as evidence for replacement.

### Sixth hourly review — 25 September 03:46 UTC

Nine overnight runs have finished training and all paired evaluations without
runtime failures; run-10 was training after 11 completed epochs. The supervisor
reported no exceptions. No repair or queue change was needed, and just under
two hours remain before the original deadline.

Run-09 repeats the promising run-03 configuration with a second seed. It again
scores 99.7733% clean (+9 correct versus original); the 32-pixel score is
99.3828% (+44 correct). Aggregate 64-pixel, blur and dark results improve by
8, 6 and 10 correct crops respectively. Run-03 remains better at 32 pixels,
while run-09 scores better on the other stress variants. Their shared gains
across all five aggregate tests repeat across seeds, but target B31/B33 metrics
remain unchanged and these are still development crops.

Run-08 repeats run-02: 99.7103% clean (+4 correct), +12 correct at 32 pixels,
unchanged 64-pixel, -1 blur and +7 dark. Neither run-08 nor run-09 introduces
false end-family predictions; their end-family precision and recall remain
100% in every crop variant. The unchanged exact-label score remains 184/185,
including the documented mislabeled end-of-90 crop. No candidate has been
exported, published or deployed.

### Seventh hourly review — 25 September 04:45 UTC

Ten overnight runs have finished training and paired evaluation without runtime
failures. Run-11 has completed training at its time budget and was undergoing
paired evaluation when inspected. Its best clean accuracy is 99.8237%, but its
stress results must be inspected before interpreting that score; the first-seed
full-model counterpart (run-05) had regressed in darkness. The supervisor reports
no exceptions and retains the 05:41 UTC deadline, with about 56 minutes left.

Run-10 (second-seed augmented linear head) scored 99.7103% clean (+4 correct),
with +20, +4, +4 and +9 correct for 32-pixel, 64-pixel, blur and dark inputs.
Its B31/B33 metrics remain unchanged, with no false end-family predictions.

An additional per-class audit confirms that the aggregate gains of runs 03 and
09 conceal regressions in individual classes. Both lose one clean B14-110
example (59/60 versus 60/60 originally). Run-03 additionally loses one
low-resolution B14-70; run-09 loses one additional dark B14-30 example. These
counts are against the published labels, not a new visual audit of those crops.
Consequently neither candidate demonstrates universal per-class non-regression,
and neither is approved for deployment. No queue change or repair was needed.

### Final review — 25 September 05:46 UTC

The queue reached `budget_completed` at 05:34:18 UTC, before its deadline.
All 13 additional runs and their paired evaluations exited successfully; no
queue containers or supervisor were still running at final verification.
The original source checkpoint hash is unchanged. Final metrics were downloaded,
the hourly automation was paused, and the completed analysis is recorded in
[TSR_FR_END_SIGN_OVERNIGHT_RESULTS.md](TSR_FR_END_SIGN_OVERNIGHT_RESULTS.md).
No checkpoint was exported, published or deployed. The recommendation is to
retain the original classifier and prioritize independent full-frame evaluation
of the proposal detector and end-sign processing.
