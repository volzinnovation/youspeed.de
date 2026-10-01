# iPhone build 10024 log audit — 2026-10-01

Build 10024 fixes the earlier universal preparation timeout on the actual phone: **1 / 4,953 preview frames exceeded the 50 ms budget (0.0202%)**, versus 744 / 744 in build 10023. Lane continuity and thermal endurance remain unresolved. This is a log audit; detection accuracy, dashed-paint recall and the user's night/low-light observation require video review.

## Evidence and measurement

The copied session starts at 08:44:43 UTC / 10:44:43 CEST. Sources are `inspector/logs/2026-10-01-drive-review/20261001_084443_582_tsr_log.ndjson` (preview, presentation, TSR and capture diagnostics) and `20261001_084443_580_drive_match_log.ndjson` (872 drive-match rows, 552 during recording). All 4,953 preview records report build `10024`; no selected diagnostic JSON was malformed. Derived data, source SHA-256 hashes and a reproducible read-only audit script are in `iphone10024-audit.json` and `audit_iphone10024.py` in that evidence directory. No source logs were modified.

The recording is `drive-37FD1D0A-3EA8-46D4-A6EB-1289EA3A463D-583D5B35-D019-4396-8C75-391169D96E35.mov`. Start callback: **08:44:48.997 UTC**; stop callback: **08:54:11.502 UTC**; reported media duration: **562.238 s**. Video offsets below subtract the start callback; they are approximate, because the anchors explicitly say `callback_anchor_estimated`. The source image is consistently 3840 × 2160 with 180° rotation.

Frame percentages use the 4,953 evaluated preview exposures, not all camera frames or recording duration. The preview exposures span 495.244 s at an exceptionally regular 100.009 ms median interval. Percentiles use median p50 and nearest-rank p95. Presentation events are sampled diagnostics, not duration-weighted state percentages.

## Preparation performance and heat

| Preview stage | p50 ms | p95 ms | maximum ms |
| --- | ---: | ---: | ---: |
| Luma sampling | 0.291 | 0.641 | 5.488 |
| Queue wait | 0.085 | 0.195 | 73.229 |
| Filter | 0.836 | 2.931 | 23.368 |
| Geometry, tracking and selection | 1.945 | 5.656 | 31.345 |
| Total preparation | **3.181** | **9.496** | **77.029** |

These are the new preview's own stage measurements. Stage quantiles must not be added together. The sole budget failure, `lane-1218` at video offset 121.714 s, spent **73.229 ms waiting in the queue**. Filter/geometry then exited promptly after the deadline. Raising the geometry budget would treat the wrong cause.

Thermal state changes from nominal to fair at video offset **25.306 s**. The first `thermal_paused` presentation occurs at **08:53:04.345 UTC**, approximately **495.348 s** into recording, immediately after the last preview exposure. Fourteen thermal-paused presentation samples span 65.469 s; no recovery appears before recording stops. This supports a roughly **67 s thermally gated tail**, subject to notification and callback timing, rather than a percentage computed from those fourteen samples. TSR also reports 757 `thermal_paused` records, continuing through 08:59:28.801 UTC. Exact temperature and serious-versus-critical state are not recorded at the pause. Logs do not establish which workload caused the heat.

## Availability, selection and continuity

| Outcome | Frames | Share of preview frames |
| --- | ---: | ---: |
| At least one raw/fused candidate | 4,736 | 95.62% |
| At least one confirmed track | 3,570 | 72.08% |
| At least one selected visible boundary | 3,071 | 62.00% |
| Exactly one visible boundary | 2,996 | 60.49% |
| Two visible boundaries | 75 | 1.51% |
| Confirmed tracks, but none selected | 499 | 10.07% |

These are availability measurements, **not accuracy or recall**. Raw/fused candidates include tracked geometry. The detector/temporal stage often finds candidates that maturity and ego selection subsequently omit; a missing overlay cannot be assumed to mean no paint was detected.

The unchanged saved calibration gives the ego selector an anchor at `y = 0.78`, with left reference `x = 0.0085`, right reference `x = 0.5590`, and center **`x = 0.283766`**. Relative to that center, output is right-only in **2,936 frames**, left-only in **60**, and both in **75**. Of 3,146 displayed boundaries, 3,011 classify right and 135 left; median displayed `x(0.78)` is 0.6481. This strong asymmetry warrants checking the calibration against the current video. If both actual lane borders fall right of the calibrated center, the current one-per-side selector makes them compete. The log alone cannot establish where the true borders are.

There are **67 observed `scope_or_geometry` resets**; 40 immediately follow a frame with visible output. Reset-to-reset intervals have median **4.30 s**, p95 22.20 s and maximum 40.10 s. The system creates 8,745 presentation identities, of which 132 become selected visible identities. A visible identity's first-to-last selected exposure span has median **1.70 s** and p95 9.00 s; this span can contain interruptions. There are **850 changes of the selected identity set**, including appearance/disappearance. These are identity/availability churn, not measured pixel jitter.

All preview records retain the same visual-calibration revision. All 2,113 simultaneous calibrated TSR records retain the same source geometry and camera-calibration revision. However, their intrinsics change in every consecutive pair. Applying the production preview tolerances (0.5% focal length; 0.001 principal-point coordinate, against a fixed anchor) to this **sampled TSR sequence** produces 55 anchor changes: 50 for focal length and five for `cx`. This supports further investigation of threshold-triggered resets, but **does not prove which of the 67 preview resets came from calibration**: preview diagnostics omit intrinsics, identity generation and the component that changed; TSR and preview sample different exposures. Do not report these simulated 55 changes as observed preview reset causes.

The default TSR sidecar still reports `scope_or_geometry` on 2,112 / 2,113 calibrated records. The stable-identity fix is preview-only; this sidecar result must not be mistaken for preview behavior or silently changed as part of display tuning.

## Motion and next measurements

Motion projection is eligible on **4,257 / 4,953 frames (85.95%)**. Eligibility means the prior can be constructed; it does not mean any projected point was accepted or a prediction passed patch validation. Ineligible-frame conditions overlap: course accuracy outside 0–15° (438), fix age outside 0–1.1 s (264), speed outside 1–60 m/s (248), heading rate outside ±35°/s (50), and fix interval outside 0.1–2.5 s (40), plus missing startup history. `motionHint.used = false` on a straight road is not evidence that straight-ahead projection is disabled.

Priority measurements are: verify the saved calibration against visible road borders before using harder split detection zones; log the precise scope-reset component, anchor/current intrinsics and delta; label dashed versus solid borders in selected video intervals; log per-side candidates rejected by maturity/anchor/score rules and accepted motion projections; and measure thermal endurance with bounded analysis demand. The existing implementation already selects at most one mature boundary per calibrated side. A proposed two-zone detector changes candidate search upstream and should be evaluated separately from that existing output cap.
