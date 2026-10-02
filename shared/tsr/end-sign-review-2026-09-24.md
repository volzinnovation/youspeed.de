# End-sign observation qualification and Panoramax training review

Reviewed 2026-09-24. No model weights, signed model packs, or installed apps were changed.

## Runtime change

B31 and B33 were already mapped to `restriction_end`; the missing observations were not a class-mapping omission. Both apps compared the **minimum of detector and classifier scores** against the class threshold (0.70 for these French classes), so a good classification on a weaker proposal could not contribute even an approach observation.

Both clients now admit speed-restriction end observations when the combined score and proposal meet the pack's observation floor (currently 0.25), and the classifier meets its class threshold (currently 0.70). This is semantic-based, including the mapped end signs in DE, FR, BE, NL and CH. Missing stage scores retain the old conservative path; calibrated packs require calibrated stage evidence, never raw-score substitution. Other sign thresholds are unchanged.

Admission does **not** mean confirmation or passage. Combined scores remain unchanged. Confirmation still requires the configured number of frames, a combined score reaching the confirmation threshold (currently 0.70), and a current combined score at least the provisional threshold (0.45). Applicability, current road context, and passage checks still apply. A distant low-score observation followed by a clear view can now confirm earlier; repeated weak views alone cannot reset the limit or trigger the full-size end pictogram.

Android also now publishes the current end observation's confidence instead of allowing an older preferred crop to replace it, matching iPhone. The applicability sidecar gains optional `detectorRawScore` and `classifierRawScore` so future per-frame reviews can distinguish proposal failures from classification failures. Legacy logs remain readable.

## Attached Android evidence

The retained September 24 log contains 12 B31 candidates, no B33 candidates, and no delivered end-sign passages. All 12 candidates were originally `recognitionEligible=false`, with combined scores 0.269–0.417.

Five candidates could be joined to sampled inference diagnostics by exact frame ID. Each had one proposal and B31 as the primary class:

| UTC | Detector | Classifier | New observation admission |
|---|---:|---:|---|
| 09:55:14.576 | 0.360 | 0.991 | eligible |
| 09:55:15.877 | 0.297 | 0.995 | eligible |
| 09:55:17.306 | 0.320 | 0.989 | eligible |
| 09:55:38.305 | 0.292 | 0.834 | eligible |
| 09:55:41.820 | 0.269 | 0.694 | rejected |

The other seven frames lack retained per-candidate classifier scores, so their new eligibility cannot be reconstructed honestly. None of the 12 has a strong enough combined score to confirm by itself.

Eleven boxes between 09:55:11 and 09:55:50 cover 26–32% of the image and recur near the left edge. This is suspicious for an interior/reflection/background proposal, not evidence of eleven physical signs. The final candidate at 10:39:45 has a small box (~0.1% of the image) and a combined score of 0.417. No aligned Android pixels were available in the exported diagnostic evidence to adjudicate either case. The saved evening iPhone log had no B31/B33 candidates. Absence from candidate logs cannot measure missed physical signs without image annotation.

Private evidence and test outputs: `.codex-tmp/end-sign-review/`; original exported log: `.codex-tmp/android-drive-20260924/`.

## Original Panoramax models

The app's French classifier is the original [Panoramax YOLOv8 crop classifier](https://huggingface.co/Panoramax/classify_fr_road_signs), pinned at `7f2bdd58f20b3dfc7161c5aea7c672ce02749c8f`; that remains the current Hugging Face revision checked today. Its published dataset is [classified_fr_road_signs](https://huggingface.co/datasets/Panoramax/classified_fr_road_signs), pinned at `ea75988e381f16e4677c5f42aa5fedea005f23d6`, with `train.zip` and `val.zip`. The dataset viewer currently fails to build; archive access is the reliable acquisition route.

Our existing `foreign-calibration/FR-classifier-operational-benchmark-v1.json` records:

| Class | Correct / labeled crops | Predictions of this class |
|---|---:|---:|
| B31 | 51 / 51 | 53 |
| B33-30 | 100 / 100 | 100 |
| B33-50 | 48 / 48 | 49 |
| B33-70 | 95 / 96 | 95 |
| B33-90 | 6 / 6 | 6 |

These are crop-only results from the published validation split, **not an independent route holdout or detector-recall measurement**. B33-90 has especially little evaluation support. They favor starting with proposal detection and difficult full scenes rather than assuming the classifier needs wholesale replacement.

The mobile detector is `yolo11n_panoramax.pt`, pinned to SGBlur commit `169451970702aca0dde9ff3106dba0f67e0b88a8`. The [original model inventory](https://github.com/cquest/sgblur/tree/169451970702aca0dde9ff3106dba0f67e0b88a8/models) contains:

| Candidate | Original checkpoint bytes | Role in a comparison |
|---|---:|---|
| YOLO11n | 5,979,923 | Current mobile baseline; first fine-tuning target |
| YOLO11s | 19,524,947 | First larger-detector challenger / offline teacher |
| YOLO11m | 40,886,949 | Offline teacher candidate |
| YOLO11l | 51,562,194 | Larger offline candidate; not selected by that server's default configuration |
| YOLOv8s | 22,998,735 | Older control candidate |

These are checkpoint sizes, not mobile RAM or latency estimates. No comparative inference benchmark was run in this review. The project has moved to [Panoramax SGBlur on GitLab](https://gitlab.com/panoramax/server/sgblur), which also lists those checkpoints.

The pinned server [detector implementation](https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/src/detect/detect.py) chooses nano on CPU and small/medium according to GPU memory. It runs 1024 and 2048 passes, with extra high-resolution processing for large panoramas. The apps run nano at 1280. Consequently server annotations and phone detections are not an equal-input comparison. Sampled live annotations identify `SGBlur-yolo11s/0.1.0` and classifier `classify_fr_road_signs/26.08.11`; that classifier version string alone does not establish checkpoint identity with our pinned Hugging Face model.

## Dataset selection and transfer learning

**Yes: transfer learning is feasible, and Panoramax exposes the requested tag filter.** Its [tag documentation](https://docs.panoramax.fr/tags/) and [semantic-overlay examples](https://docs.panoramax.fr/web-viewer/tutorials/semantics_overlays/) document searches such as:

```text
GET /api/search?filter="semantics.osm|traffic_sign" = 'FR:B31'&limit=25
GET /api/search?filter="semantics.osm|traffic_sign" = 'FR:B33[50]'&limit=25
```

`FR:B33[50]` is the OSM annotation label; `B33-50` is the model class. The selector URL-encodes parameters. Repeat exact tags for the desired variants; it does not claim that the four variants in our current classifier exhaust all possible B33 signs.

```sh
python3 scripts/tsr/select_panoramax_end_signs.py \
  --tag FR:B31 --tag 'FR:B33[50]' --limit 25 \
  --bbox 4.2,43.0,7.8,44.5 \
  --output .codex-tmp/end-sign-review/osm-fr-queue.json
```

The default endpoint is `https://panoramax.openstreetmap.fr/api/search`. That host refused connections over IPv4 and normal address selection during this review. No claim is made about its current matching population. The equivalent query was verified on `https://panoramax.ign.fr/api/search`: a two-tag smoke run selected six annotations from six returned pictures. A broader five-tag request timed out, so regional bounds and small batches are advisable.

The script collects metadata only. It preserves picture/sequence/annotation IDs, original pixel polygons and boxes, image dimensions, asset URLs, license/producer, timestamps, and all confidence/model qualifiers. It selects matching **annotation-level boxes**, not every box on a tagged picture. It deduplicates repeated annotation IDs, marks the result as a bounded sample rather than a complete inventory, and marks every selected annotation `unreviewed` and ineligible for training. Machine-generated labels are useful proposals, not automatically ground truth. No reliable standardized “human reviewed” tag was established from the inspected API responses.

Recommended experiment order:

1. Review selected B31/B33 boxes and label complete nearby sequences, including missed signs and hard negatives (backs of signs, no-overtaking ends, glare, reflections and the suspicious large left-edge proposals). Selection by model-generated tags alone misses the very failures we need to repair.
2. Reproject 360° imagery to phone-like perspective views and transform the boxes consistently. Keep original IDs and hashes. Include small/distant signs, oblique views, poor contrast, rain/night examples where available; image manipulation must not reverse the stripe or invent a label.
3. Split by route/sequence **and physical sign location**, with image/perceptual duplicate checks across train/validation/test. Keep the user's reviewed drive out of training if it is used for acceptance. The existing crop split is bootstrap evidence, not a new holdout.
4. Compare the pinned nano and small detectors on exactly the same reviewed perspective frames; measure B31/B33 proposal recall at multiple sizes, false positives per driving hour, and end-to-end passage/reset precision. Benchmark phone latency and thermal behavior before replacing nano with a larger model.
5. Fine-tune nano from its existing weights using reviewed full-scene sign boxes, balanced with other signs and hard negatives. Fully annotate the training detection classes: do not treat unlabelled signs/faces/plates as background when retaining the original three-class head. A sign-only head initialized from the existing backbone is an alternative requiring new export/output contracts and parity tests.
6. Fine-tune the French classifier only if the held-out crop error breakdown justifies it, mixing the existing classes with verified difficult end-sign crops to avoid forgetting. A larger detector can supply additional proposals for review/distillation, but its predictions still need checking.
7. Recalibrate thresholds and export/test Core ML and LiteRT against identical inputs, then replay the passage/reset/display behavior. Retain the source-specific image licenses and existing model lineage requirements before any release.

No training job, new model pack, bulk image download, or model publication was performed.

## Verification

- iPhone simulator: 62 tests passed (new qualification regressions, applicability, passage/resolution tests).
- Android JVM: 102 tests passed (fusion, applicability, orchestrator and passage tests).
- Python: 15 tests passed (shared applicability and selection tests).
- Live metadata selector: six unreviewed annotations selected using the two-tag IGN smoke query.
- `git diff --check` passed. No physical-device deployment was requested for this change.
