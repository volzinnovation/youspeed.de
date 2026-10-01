# Lane device validation and backup cleanup — 2026-10-01

This records the physical-device follow-up to [the implementation](LANE_NEXT_IMPLEMENTATION_2026-10-01.md) and [offline evaluation](LANE_NEXT_EVALUATION_2026-10-01.md). Android workload validation passed; iPhone build 10028 is installed, but sustained validation remains incomplete after repeated background camera interruptions. Android has build 10027 installed. Experimental grouping, tentative identity retention and joint selection remain disabled in the normal app. The Android camera-ownership correction is enabled. The 50 ms preparation target remains diagnostic, not a cutoff.

## Android baseline and retention incident

Installed build 10025 ran for 600.412 timed seconds on the attached Moto g86 5G. It processed 2,277 lane exposures (3.80 Hz), with a p95 exposure interval of 433.5 ms and p95 lane preparation of 20.47 ms. Sampled process RSS reached 997.6 MB; all 507 thermal samples were status 0. Preview and movie recording remained active throughout the sampled interval.

The result is **failed**, because the final media-preservation assertion detected that normal dashcam retention had removed an older movie. The separate hard 10 GB movie quota was unaffected by the test's photo-storage protection. The 448,357,415-byte movie was restored from its local original, verifying SHA-256 equality on the phone. A second absent 471,323,516-byte older movie also has an exact verified local original; its deletion time cannot be established from the saved inventories. All other entries in the earlier 13-movie inventory were accounted for by unchanged sizes. The original failed summary remains unchanged.

The baseline's new movie was moved to its own evaluation directory. Subsequent tests use an isolated DEBUG recording destination and exact-file retention exemption from the start of capture. They persist original-media inventories before capture. The user subsequently authorized device cleanup where local backups are verified; that cleanup is recorded separately from the test failure.

Evidence: `inspector/logs/2026-10-01-lane-next/android-baseline-10025/`.

## Backup cleanup

The app processes are stopped before snapshotting logs. Video removal requires fresh equality of local and device SHA-256 plus size. Log archives are lossless gzip; their decoded SHA-256 is checked against the device file. Exact files are removed only after verification. Photos, preferences and databases are excluded. Unbacked videos remain on the phones.

Android cleanup completed: all 12 remaining owner videos (9,508,863,003 bytes), three test videos (1,386,479,017 bytes) and six operational-log snapshots (814,392,825 decoded bytes) were backed up, verified and removed. The owner/evaluation movie directories and operational log directory are empty. File-by-file paths, hashes and deletion checks are indexed by `inspector/logs/2026-10-01-device-cleanup/android/summary.json`.

iPhone cleanup completed for all pre-existing movies and logs: 11 owner videos totaling 9,463,512,913 bytes and 18 operational-log snapshots totaling 88,631,217 bytes were copied, hash-verified and removed. Before/after metadata checks preserved all 11,104 Panoramax/QA files. The initial and final inventories are in `inspector/logs/2026-10-01-lane-next/iphone-cleanup/backup-cleanup-manifest.json` and `iphone-final-archive/manifest.json`. The final inventory at 15:17 UTC has no normal movies or operational logs.

Across both phones, this removed 21,261,878,975 bytes (21.26 GB decimal): 26 videos and 24 log snapshots, all with verified local copies. A separate fresh local audit rehashed all 54 archived files successfully; see `inspector/logs/2026-10-01-device-cleanup/local-archive-verification.json`. The two original videos previously stored under Android build reports also have protected hardlinks outside regenerable build caches.

The interrupted iPhone 10027 test subsequently created a 644,503,703-byte movie and three operational logs totaling 6,102,485 bytes. Those were independently verified against their local copies and removed after stopping the producer. Its diagnostics and both test photos remain archived; original photos, settings and databases were preserved. Evidence: `ios-device10027-runA/archive-manifest.json`. New validation output is handled separately from the pre-existing cleanup totals. All three resumed iPhone runs and the final automatic-restart log snapshot are now archived and hash-verified. Across the complete cleanup, 29 videos and 35 log snapshots totaling 22,573,543,093 bytes (22.57 GB decimal) were removed. The fresh resumed-work audit rehashed all 28 additional archive files successfully. `inspector/logs/2026-10-01-device-cleanup/resume-summary.json` indexes every manifest and the final installed builds.

## Candidate validation

Android build 10026 passed 600.919 timed seconds, including movie finalization, original-movie SHA checks and preference restoration. All 495 preview samples were visible. No sampled thermal pause occurred. Its APK/source hashes, device metadata and results are under `inspector/logs/2026-10-01-lane-next/android-candidate-10026/`.

| Metric | Baseline 10025 | Candidate 10026 |
| --- | ---: | ---: |
| Lane exposure cadence | 3.80 Hz | 7.25 Hz |
| p95 lane exposure interval | 433.5 ms | 233.4 ms |
| p95 preparation | 20.47 ms | 23.31 ms |
| p95 known-clock sampled lane-worker age | 148.90 ms | 138.96 ms |
| p95 known-clock geometry-publication age | 135.13 ms | 133.04 ms |
| Completed TSR path-evaluation cadence | 1.925 Hz | 1.911 Hz |
| Mean sampled RSS | 942.35 MB | 1,048.86 MB |
| Maximum sampled RSS | 997.57 MB | 1,106.75 MB |

Lane cadence increased 91% and p95 exposure gaps fell 46%, while mean RSS rose 107 MB. Candidate RSS warming slowed but did not clearly plateau: its final 300-second slope was +1.91 MB/min. One of 4,347 frames exceeded the 50 ms preparation target (58.0 ms) and was processed normally. No OOM-fix claim follows from this result. Worker/geometry age is distinct from visible painted-line age; no observed paint was available in this scene.

The run started at thermal status 0, with battery temperature 32 °C versus 28 °C for the baseline. Both runs used USB charging and automatic brightness; source mean luma changed from 2.28 to 3.61. A controlled heat-improvement claim would be unsupported.

Build 10027 changes Android telemetry serialization only, making nested camera/lane cadence fields actual JSON objects. All 586 unit tests passed. Its 30.351-second device smoke passed and verified seven structured camera and seven structured lane diagnostic events, movie continuity, original-movie hashes and restored preferences. Build 10027 is installed; the measured 600-second result remains explicitly attributed to 10026.

The first iPhone 10026 test failed before recording because the harness used a lagging published dashboard state when waiting for automatic camera capture to stop. Build 10027 corrected coordinator/preview synchronization. Its fresh run on resume failed after 144.668 timed seconds; the movie finalized at 144.112 seconds in 3840×2160. There were 1,440 timed lane diagnostics, 139 visible-preview samples, two actual photos and no sampled thermal pauses. Preparation p95 was 5.486 ms; sampled RSS peaked at 300.91 MB and physical footprint at 237.55 MB. Exposure cadence was approximately 10 Hz.

The 10027 harness overwrote the original interruption with its secondary movie-duration validation error and defaulted failed-run inference totals to zero. Raw samples demonstrate at least 278 completed inferences between the first and last samples. Neither the original stop trigger nor its exact inference total can be recovered from that summary. The console records an explicit dashcam-disable transition just before cleanup; this does not establish whether a person or another app action triggered it. The original summary remains unchanged.

Build 10028 changes test diagnostics only: it preserves the first error, logs pre-cleanup app/coordinator/preview/module state, captures final inference metrics on failure and reports movie validation separately. Scene metadata now describes an uncontrolled physical camera rather than assuming stationary conditions from the test setup. It compiled, signed and installed. Its first run stopped after 229.187 seconds because the app entered the background (application state 2) and AVFoundation reported session interruption, code −11818. The camera finalized its 229.085-second 4K movie; thermal state was 0 and TSR remained available before stopping. It processed 2,282 timed lane frames and 440 completed inferences. All 221 preview samples were visible before interruption, preparation p95 was 6.483 ms, sampled RSS peaked at 327.40 MB and physical footprint at 231.93 MB. One 135.376 ms preparation frame was processed normally. Preferences and owner photos were preserved. The test remains failed. The XCTest console subsequently reports CancellationError, but the saved summary preserves the original background-interruption reason. Evidence: `ios-device10028-runB/`.

The movie callback briefly labelled this successful interruption finalization as “Dashcam-Dateigrenze erreicht”; the actual AVFoundation code denotes session interruption, not a size limit. The subsequent camera state correctly reports interruption. This misleading transient movie detail is a separate diagnostic issue, not evidence that a 5 GB file limit was reached.

Run B was independently archived and hash-verified before its movie and operational logs were removed; its diagnostics remain. A final retry of unchanged build 10028 also stopped on background session interruption, after 121.210 seconds. It recorded 1,202 timed lane frames, 233 completed TSR inferences and a finalized 120.542-second 4K movie. All 117 preview samples were visible before interruption; preparation p95 was 5.112 ms, sampled RSS peaked at 349.70 MB and physical footprint at 231.38 MB. At interruption, thermal state was fair (1), with no sampled serious/critical pause and no TSR unavailability. It captured no still photos. Preferences and owner photos were preserved. Evidence: `ios-device10028-runC/`.

No sustained iPhone pass is claimed. The measured background transitions are established; their external trigger is unknown. The app already disables automatic screen idle while its scene is active. Another retry requires an uninterrupted foreground window, rather than repeatedly restarting a camera that iOS is interrupting. The latest runs do not establish an OOM fix, thermal improvement, moving-road accuracy or classifier-heavy workload performance.

Three extracted frames from 10027 show a dark view at 10/70 seconds and a tabletop with printed papers/cables at 140 seconds. This is not a driving lane-accuracy clip. The final samples report speed zero, though the run's maximum GPS-reported speed was 31.86 km/h; no claim of physical vehicle movement follows from that maximum. All guide-trust diagnostics stayed weak. The baseline displayed borders during approximately one second at the end of this non-road scene, another specificity concern to evaluate on labelled road negatives. Experimental options remain disabled.

These camera tests can establish camera, detector, lane worker, movie and display continuity over their observed intervals. Both Android runs captured zero still photos; every sampled inference diagnostic recorded zero classifier invocations, which is not an all-frame classifier counter. They do not establish moving-road border correctness, photo-encoder load, recovery from the earlier crash, or performance under a busy sign scene. Logged TSR inference events are throttled and must not be interpreted as actual inference throughput. Use unthrottled completed path-evaluation frame IDs for exposure cadence. Memory maxima are sampled rather than exact peaks.
