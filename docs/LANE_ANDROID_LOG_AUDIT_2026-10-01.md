# Android lane and crash log audit — 2026-10-01

The Android application's own persisted log identifies the reported exit as an **uncaught `IndexOutOfBoundsException` on the main thread at 11:58:13.695 CEST (09:58:13.695 UTC), PID 7750**. It attempted to read element 1 of an empty list in `ConsumerSessionController.onLanePreviewPrepared`, line 1291 in the installed build's stack trace. This is direct evidence of a lane-preview publication/indexing failure; the application log does not identify an out-of-memory termination.

The final saved preview and TSR results completed normally just before the exception. Detection was still producing visible borders, and its preparation budget did not fail in the final minute. Independent operating-system exit records and the source-level race analysis should determine the full root cause; this audit concentrates on the saved application and drive logs.

## Evidence and scope

The complete copied files are under `inspector/logs/2026-10-01-android-crash/`:

- `runtime_diagnostics.ndjson`: **645,549,674 bytes**, covering September 30 14:36 UTC through the October 1 exception; no malformed JSON rows.
- `drive_match_log.ndjson`: **126,267,229 bytes**; no malformed JSON rows.
- `runtime-audit.json`: compact derived timings, recording windows, capture configuration, final frames/events and SHA-256 hashes.
- `audit_runtime.py`: read-only streaming audit script; `event-schema-samples.json` retains representative event schemas.

The runtime file spans multiple sessions and includes an older build before the verified Android build-10023 update on September 30 at approximately 18:27 CEST. The build-10023 window begins at 16:27 UTC, with its first `session_init` at 16:27:44.742 UTC. The iPhone's subsequent build-10024 results are not Android results.

Percentiles use the sorted numeric samples and the element at `floor(0.95 × n)`, capped to the final element; medians use the element at `floor(n / 2)`. These are observed event statistics, not a throughput benchmark or lane-accuracy labels. Recording/log anchors are estimated callback anchors, not exact exposure synchronization.

## The final session

PID 7750 initialized at **11:46:46.550 CEST**. Recognition became active at 11:46:51.737. Dashcam recording began at **11:47:12.614**, and the most recent capture configuration enabled recognition, dashcam recording, detected lanes and the independent lane preview, with the application active. Panoramax photos were disabled. The saved visual-calibration revision was `a3537673-5303-40a3-beb0-af918dea136c`.

The last events establish the ordering:

| CEST time | Saved evidence |
| --- | --- |
| 11:58:11.248 | Recorder progress: 658.264 seconds written; no later stop/finalize event. |
| 11:58:13.243 | Preview `lane-1803`: one selected border, preparation **11.09 ms**, geometry budget not exceeded. |
| 11:58:13.664 | Last TSR path result saved. |
| 11:58:13.665 | TSR inference result: **333.02 ms** inference, **383.27 ms** camera-receipt-to-result, no terminal backend failure. |
| 11:58:13.695 | Uncaught main-thread `IndexOutOfBoundsException`: empty list, index 1. |

The final dashcam file is `dashcam-1790848032414-6e23d5c4-5e58-4c70-b698-bba5b714ae6b.mp4`. The time from its start callback to the exception is **661.081 seconds (11:01)**. Independent inspection of the transferred **681,557,690-byte MP4** found no `moov` atom and an `mdat` size extending past the file end; the decoder cannot open it. This is consistent with the interrupted recording/finalization. The device original and copied bytes are retained.

The final drive match was recorded at 11:58:11.230 CEST, with speed **60.19 km/h**, GPS horizontal accuracy **8.54 m**, and a stable road match on K 3549. Preview motion projection remained eligible on every frame in the final minute. These facts establish active driving but are not evidence about lane correctness.

## Processing just before the crash

| Measurement, final minute | Observed value |
| --- | ---: |
| Preview evaluations | 193 |
| Preview geometry-budget failures | **0** |
| Preview preparation median / p95 / maximum | **14.61 / 27.84 / 49.03 ms** |
| Frames with a selected border | 155 / 193 (**80.31%**) |
| Frames with two selected borders | 38 / 193 (**19.69%**) |
| Preview exposure interval median / p95 | **366.87 / 500.01 ms** |
| TSR path evaluations / preparation budget failures | 127 / 3 |
| Sampled TSR inference median / p95 | **323.66 / 432.65 ms** |
| Sampled TSR backend queue-wait median / p95 | **0.13 / 2.92 ms** |

At 11:58:10.865, the last sampled worker counters reported **1,797 processed, 0 replaced, 1,081 throttled and 0 timestamp-rejected frames** in that runtime. The trailing window was **3.58 completed frames per second**. Its capture-to-result median/p95/maximum was **90.75 / 123.84 / 156.88 ms**. This is not evidence of an accumulating preview queue.

Cadence is still an improvement target: across the final recording the median preview exposure interval was **399.69 ms**, while median preparation was only **15.24 ms**. The preparation deadline alone therefore does not explain the low update cadence. Camera delivery, shared TSR analysis and throttling need an admission/callback timing audit before claiming a cause. Raising the preparation deadline would not fix the recorded exception.

The runtime log contains no thermal or memory event type and no explicit memory-pressure event. This absence cannot rule out memory pressure, because memory telemetry was not recorded. It does mean that a memory diagnosis should not replace the explicit Java exception. There is no app-log evidence of a thermal pause in the build-10023 lane-presentation samples.

## Other build-10023 recordings

All times below are CEST. Counts describe selected output availability, not accuracy: unmarked roads, occlusion and false detections affect them. Mean source luma is camera-image brightness, with exposure and scene content as confounders; it is **not** a night/day label.

| Recording start | Callback duration | Preview frames | Frames with selected borders | Budget failures | Preparation median / p95 | Sampled source-luma median |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sep 30 18:37:17 | 2:56 | 461 | 173 (37.53%) | 0 | 16.72 / 29.35 ms | 118.46 |
| Oct 1 07:11:18 | 13:07 | 2,322 | 1,113 (47.93%) | 28 (1.21%) | 11.87 / 26.18 ms | 80.25 |
| Oct 1 10:15:41 | 8:59 | 3,371 | 2,097 (62.21%) | 4 (0.12%) | 17.11 / 28.53 ms | 134.07 |
| Oct 1 10:54:38 | 9:59 | 2,386 | 1,052 (44.09%) | 2 (0.08%) | 17.90 / 29.24 ms | 126.37 |
| Oct 1 11:25:57 | 1:05 | 169 | 57 (33.73%) | 1 (0.59%) | 18.68 / 33.68 ms | 130.14 |
| Oct 1 11:47:12 | 11:01 to crash | 1,801 | 1,164 (64.63%) | 9 (0.50%) | 15.24 / 29.34 ms | 121.78 |

There was also a 1.6-second recording at 07:11:11 with no preview samples. Across the full build-10023 window, **44 of 10,510 preview frames (0.419%)** exceeded the preparation budget. Median/p95 preparation was **15.76 / 28.70 ms**; **5,656 frames (53.82%)** had any selected border and **848 (8.07%)** had two.

Independent video inspection confirms that the early-morning recording contains dawn/low-light headlamp-lit forest sections during approximately 0–230 seconds, followed by village/unmarked-road/traffic scenes. The **869,550,963-byte**, 1280×720 file has approximately **786.18 seconds** of encoded duration; eight overview samples and a tail decode succeeded. This is sample/tail validation, not verification of every encoded frame. See its [contact sheet](../inspector/logs/2026-10-01-android-crash/dashcam-1790831478322-a6bcfcaa-feb4-4bdd-a9f8-72da344a1c19-contact.jpg) and `recordings-inspection.json`. The lower source-luma samples are consistent with these images, but output-availability counts across the mixed scenes do not establish a night accuracy improvement or explain dashed-line misses; that requires painted-border labels. Much of the separate September 30 evening/overnight TSR log contains almost black images (hourly median source luma around 2–3 from 22:00 CEST onward) without lane-preview or recording samples. Those records must not be treated as a successful night lane-detection test.

## Limits and next checks

The Android preview-frame schema in installed build 10023 logs selected boundaries and identities, total preparation, motion eligibility and geometry. It does **not** log raw candidates, per-candidate confidence, preview track-reset reasons or detailed stage rejection. TSR-sidecar `scope_or_geometry` and `exposure_gap` resets belong to the independent TSR path, and cannot be assigned to the preview tracker.

Prioritize a coherent immutable publication result, frame/geometry validation and a regression case covering a reset between worker completion and UI publication. Then add the missing preview diagnostics and inspect the unexpectedly low cadence. Preserve the bounded pending-frame design. Neither memory-pressure optimization nor dashed-line tuning can substitute for fixing the directly observed indexing failure.

This report describes the installed build-10023 evidence, before any subsequent fixes. No production files, device settings or deployments were changed by this log-audit subtask.
