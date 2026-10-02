# Android night-drive review — 27 September 2026

## Finding

Low-light capture degradation is supported by the saved photographs and weak,
inconsistent recognition evidence. The pipeline stayed on GPU without a
multi-second backlog. The photos visibly show blurred or washed-out sign faces;
EXIF records 80–100 ms exposures at ISO 9,740–11,195.

These are **4096×3072 Panoramax stills**, not the exact **1600×1200 TSR analysis
frames**. The inspected stills are 0.7–2.7 seconds from selected recognition
events. They establish the capture conditions, but do not prove the live
analysis stream used identical exposures. Analysis-frame shutter time, ISO and
focus state are not currently logged.

## Session and model

Read-only inspection of attached moto g86 5G, app `de.youspeed.android.debug`.
The main session begins 20:00:44 UTC (22:00:44 CEST); the copied diagnostic
stream ends at 20:55:07 UTC. The reference distance counter reaches 73.5 km.
Capture and recognition remain enabled through the drive.

Loaded model at 20:00:52 UTC: **fr-panoramax-bootstrap-evaluation-v1**. This
is the French classifier, not the owner-accepted Swiss v9. Detector SHA-256:
`e5490acd60ceb015336bed487b5e247c2728b2b98b6336790bf6ffe02a6f7207`.
Reference policy: **1.1.0**. Older sessions in the same log are excluded below.

## Runtime evidence

| Measurement | Result |
| --- | --- |
| Analyzed applicability batches | 8,427 |
| Batches without candidates | 8,071 (95.8%) |
| Candidate observations | 434 across 356 nonempty batches |
| Sampled inference diagnostics | 2,435 |
| Backend | GPU in every sample; no reported fallback/failure |
| Inference time | Median 294 ms; p95 400 ms; max 867 ms |
| Camera receipt to result | Median 315 ms; p95 421 ms; max 902 ms |
| Backend queue wait | Median 0.19 ms; p95 0.52 ms |
| Source image | 1600×1200 |
| Full-image sampled luma | Median 52.8/255 |
| Authoritative camera passages | Four |

**Empty-frame percentage is not a missed-sign rate.** Most frames naturally
contain no sign. A labelled inventory of passed signs is needed to measure
recall. Full-image luma is also not an exposure measure for reflective sign
faces.

Diagnostic recognition states: 2,384 no-recognition, 40 unknown, eight
provisional, three confirmed. Stage diagnostics are rate-limited and can miss
confirmation frames; the passage log records four passages. Unknown can mean
a recognized non-speed class has no speed-limit semantic. There were 94
sampled display observations, so those labels cannot be equated to missed
pictograms either.

The existing pack requires two-frame confirmation within 1,500 ms and a
confirmed threshold of 0.7; detector proposals start at 0.25. Android combines
support with `min(detectorScore, classifierScore)`. Both are raw scores, not
calibrated probabilities. Strong classification cannot compensate for a weak
detector proposal.

Applicability reasons: 1,301 unqualified observations, 96 stale snapshots,
32 missing camera-calibration observations and nine unreliable-road-context
observations. These include tracked/lost observations, not independent signs.
There were no explicit exit/access-road rejection reasons. General
applicability remains in shadow mode, so UNKNOWN decisions do not themselves
explain wholesale suppression. `contextIsCurrent=true` denotes coherent
scope/generation, not always usable road geometry. The road-match file has
988 matched and 65 no-database records.

## Concrete sequences — local CEST

| Time | Evidence | Outcome |
| --- | --- | --- |
| 22:13:41 | 110 candidate, detector .826 / classifier .732; one qualified observation | Provisional, no camera activation |
| 22:49:24.420 | 110 candidate, .306 / .939 | Detector support insufficient |
| 22:49:25.195 | 110 candidate, .887 / .816 | Qualified observation |
| 22:49:25.855 | 130 candidate, .802 / .789 | Inconsistent class; no confirmed limit |
| 22:50:55.869 | 70 candidate, .521 / 1.000 | Detector support insufficient |
| 22:50:56.610 | 70 candidate, .818 / 1.000 | Qualified/provisional |
| 22:50:57.345 | 70 candidate, .880 / .585 | Classifier support insufficient; next observation is Bzz |
| 22:51:00–02 | Repeated strong 50 candidates | Camera activates at 22:51:02 |

These are model outputs, not ground-truth labels. The 22:49:24 photo visibly
contains paired roadside sign assemblies with substantial blur; ambiguous
digits should not be used to label the legal speed without sharper imagery or
owner confirmation.

## Measured photo exposure

EXIF was read from saved originals, without image enhancement. GPS speeds are
from matches within 0.3 s of each whole-second EXIF timestamp. Travel distance
is speed × exposure duration, not a measured blur length.

| Photo time CEST | Exposure | ISO | Speed | Travel during exposure |
| --- | --- | --- | --- | --- |
| 22:06:17 | 90 ms | 10,911 | 97.0 km/h | 2.43 m |
| 22:13:38 | 100 ms | 11,195 | 97.1 km/h | 2.70 m |
| 22:35:12 | 80 ms | 9,740 | 73.2 km/h | 1.63 m |
| 22:49:24 | 80 ms | 10,511 | 87.2 km/h | 1.94 m |
| 22:50:57 | 80 ms | 10,048 | 67.8 km/h | 1.51 m |

The Android camera setup requests fixed far focus but contains no explicit
night-driving exposure-duration bound. The next investigation should capture
actual analysis-frame shutter/ISO/focus telemetry and evaluate shorter
exposures against labelled night scenes. Shorter exposure reduces signal, so
hardware tests must assess the noise/blur tradeoff.

A blanket threshold reduction is not supported: plausible speed classes
already alternate. Evaluate capture quality first, then replay labelled night
examples through both mobile exports. No model, threshold, policy or camera
setting was changed in this investigation.

## Prior fixes on this drive

Disregard-vision was used at **22:39:43.716** and **22:42:15.145**. Both
immediately produced `T16 / BUNDLE / camera_dismissed`. No repeated
`camera_scope_invalidated` loop was logged. This does not establish that the
drive exercised every unresolved-end case.

## Evidence retention

Raw logs, analysis scripts, extracted summaries, reconstructed photo metadata,
and the five inspected original images remain local under
`/tmp/youspeed-android-night-20260927/`. They were not uploaded or added to Git.
Device files, settings and installation were not changed.

SHA-256 of copied evidence:

- `runtime_diagnostics.ndjson`: `d33f5789942386cb0e2f95b8f8aac947ebd2cbb3ffcd568e17e7693fc5091308`
- `drive_match_log.ndjson`: `15a2678786e65f711b28bcf7ce097908432d8f27dead036e6ebdb6daaa188703`
- `gps_fix_log.csv`: `393657dd97fd887df82472422caf902e0c6c592ab712875169f05e437d5c77ec`
- `night-photos.json`: `83d380a399d35d72321bf8011a22fecb3b7ad5f7c7e1106d28b5865ccd734a39`
- `night-journal.tar`: `fb1d29a1a5e63e18ee92a624913bd676b95da3d9c5c9b21942136ff13be5bd55`
