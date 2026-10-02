# Lane shadow review — 2026-09-30

The accepted display change and final combined build validation are documented
in the [Bézier and calibration review](LANE_BEZIER_AND_CALIBRATION_REVIEW_2026-09-30.md).

The lighting experiments did not demonstrate a reliable detection improvement. Both were withheld, and the Swift and Kotlin `RoadBoundaryDetector` implementations were restored to their original behavior. Dark/noise/shadow abstention tests and shared photometric parity fixtures remain. No presentation-maturity threshold, evidence lifetime, speed-reference policy or TSR applicability rule was relaxed.

The original detector requires a bright center and bilateral contrast for paint. Under shade, a real marking can retain local contrast while falling below the brightness floor. The first candidate normalized a dim bilateral response to that floor, subject to absolute brightness/contrast floors and a gain below three. Bright-response scores were unchanged, but the additional candidates still entered nonmaximum suppression, capped row selection and greedy track assignment. Consequently, preserving a bright score did not preserve its resulting track geometry.

The initial sparse 154-frame investigation showed a local gain on previously annotated paint: standalone held-out-subset coverage increased from 241/936 to 349/936 labelled pixels, while the tuning subset stayed at 299/492. This was insufficient evidence for acceptance. Full-session replay exposed regressions that isolated frames did not capture.

The longer comparison replayed 4,172 frames from the latest approximately 35-minute recording and 3,491 from an earlier approximately 29-minute recording, sampled at 2 Hz. It ran the production filter, detector, temporal processing and presentation gate with actual encoded timestamp gaps. Fourteen latest-recording frames and eight earlier-recording frames had partial manual paint annotations, with a three-analysis-pixel matching tolerance. Unlabelled detections were not classified as false positives; negative responses were measured only inside explicitly annotated no-paint regions.

| Partial manual coverage | Baseline | Candidate 1 | Candidate 2 |
| --- | ---: | ---: | ---: |
| Latest 14 frames, before presentation | 1,056/1,729 | 1,052/1,729 | 1,056/1,729 |
| Latest 14 frames, visible | 603/1,729 | 578/1,729 | 603/1,729 |
| Earlier 8 frames, before presentation | 307/772 | 305/772 | 307/772 |
| Earlier 8 frames, visible | 193/772 | 143/772 | 193/772 |
| Combined 22 frames, before presentation | 1,363/2,501 | 1,357/2,501 | 1,363/2,501 |
| Combined 22 frames, visible | 796/2,501 | 721/2,501 | 796/2,501 |

All three variants produced 39 response pixels before presentation and zero visible response pixels in the combined 88,422 explicitly labelled no-paint region pixels. Those restricted negatives do not establish overall precision.

Candidate 1 could extend a correct center marking into an unsupported upper hook. For example, `latest-002520` gained points from approximately y=0.595 to y=0.521 at x≈0.415; the changed geometry then lost presentation continuity. The earlier `earlier-003120` example also lost visible coverage. The presentation gate was retained because this was a geometry failure upstream.

Candidate 2 preserved original row suppression, association, predictions, boundary selection and confidence. It added measured dim samples only to already selected paint tracks, within two analysis pixels of their local geometry and at most two sampled rows beyond an endpoint. It restored the two inspected regressions but produced no coverage gain on any of the 22 annotated development frames. The older 12 partial-label frames also stayed at their full-pipeline baseline of 522/1,428 covered pixels before presentation. Across the two long recordings, 218 visible-frame geometries still changed and total visible boundary instances changed from 6,580 to 6,577. Counts alone are not an accuracy metric; no benefit justified retaining this extra behavior.

The 22 annotations were frozen for the first comparison. Once those results informed Candidate 2, they became development data. Candidate 2's matching scores are not an untouched held-out validation. Future detector selection needs new independently labelled sequences, including both paint and non-paint structures, and continuous-frame evaluation rather than only isolated frames.

This is encoded-video replay on macOS, not the live attached-device camera pipeline. It supplies no GPS, verified UTC association, metric camera calibration or visual calibration state. It cannot validate the user's current live camera calibration. Both long Candidate 2 replays had zero geometry-budget and sidecar-deadline misses, but host timing excludes decode, luma sampling and camera delivery and is not Android device performance qualification. Shadowed and changing-light markings remain a known detection limitation.

After restoring the detector, all 26 shared boundary cases and 21 path cases matched Swift/Kotlin output within 1e-9. The added photometric cases check parity and conservative abstention; they do not require successful dim-paint recognition. Focused Android detector/temporal/preparation/session tests passed (36 tests), as did the 11 actual Swift detector/preprocessor tests compiled in an isolated host SwiftPM wrapper. The two production detector files match their pre-experiment Git versions.

Reproducible local evidence is preserved under `inspector/logs/2026-09-30-lane-shadow-review/`: `latest-baseline/`, `earlier-baseline/`, `latest-detector-candidate/`, `earlier-detector-candidate/`, the corresponding `*-detector-v2/` directories, `*-label-scores/`, `*-label-v2-scores/`, `v2-comparison.json`, and `rejected-detector-v1/`. Reports retain source/input hashes and geometry output. The replay and scoring entry points are `scripts/lanes/replay_recorded_pipeline.py` and `scripts/lanes/score_recorded_pipeline.py`.
