# Android road-path performance verification

The target is at most **200 ms of added processing**, including image preparation,
boundary fitting, trajectory handling, sign association and diagnostic serialization.
This is additional to existing recognition inference. The physical-device component
results below satisfy that bound for their measured workload; live end-to-end and
sustained driving validation remain separate.

## Moto g86 component results — 29 September 2026

The final debug app and test APK were installed in place on a Moto g86 5G,
Android 16/API 36, arm64-v8a, retaining app data. App version was `1.3-debug`,
build `10016`. Both instrumentation tests passed in 30.132 seconds.

| Input | Added p50 | Added p95 | Added p99 | Added maximum |
| --- | ---: | ---: | ---: | ---: |
| Landscape | 29.968 ms | 41.706 ms | 46.354 ms | 47.295 ms |
| Portrait | 22.654 ms | 24.362 ms | 24.839 ms | 24.897 ms |
| Landscape clutter | 28.223 ms | 31.865 ms | 33.030 ms | 33.037 ms |
| Portrait clutter, pixel stride 2 | 23.534 ms | 26.071 ms | 26.923 ms | 26.927 ms |
| Rotated landscape | 22.179 ms | 24.113 ms | 24.785 ms | 25.095 ms |
| Panoramax 0906fc23 still | 17.655 ms | 19.886 ms | 20.806 ms | 21.390 ms |
| Panoramax 49e25e66 still | 17.511 ms | 20.083 ms | 20.690 ms | 29.408 ms |

There were 120 measured samples per input, plus eight warmup samples and one cold
sample: **903 enabled frames and 903 paired baselines**. All component and paired
wall-time measurements stayed below 200 ms. The aggregate 840 measured component
samples had p50/p95/p99 of 22.666/31.660/39.928 ms. The maximum cold component sample
was 75.148 ms; maximum warmup was 55.401 ms. Worst measured on-minus-off wall time
was 47.277 ms (cold maximum 69.181 ms). All 903 frames had zero 200 ms overruns;
none of the 840 measured geometry runs hit the detector deadline. Thermal status
remained 0 throughout the short run.

The separate valid 24-track triangulation control had p95 4.307 ms and maximum
6.322 ms across 120 batches, with zero 200 ms overruns. Static image replay does
not establish temporal lane accuracy: the two real stills returned no retained
boundaries, and their low timings must not be read as correct lane identification.

Retained local evidence is under the ignored
`android/app/build/reports/road-path/20260929T105211Z-79965/` directory:
`report.json`, the privacy-safe aggregate `summary.json`, instrumentation output,
APK hashes and thermal/memory snapshots. The reported run uses the final session
locking and deadline-diagnostic handling.

Final APK SHA-256:

- App: `7f85160454fe280ce6055c9566d33c75ee26cb73cca0257c21bce6409bb417b9`
- Tests: `aa891051b569e3dfcc0a6e388db33140bc5b4f65ae79f3467b9c87d9763a27d1`

## Final-build live smoke check

After reopening the app and choosing **Keep logs and continue**, existing photo and
recognition preferences resumed. Video recording remained off; no capture settings
were changed. The lane-display preference was absent, so **Show detected lanes**
retained its default off state; no camera-preview surface was visible in the inspected
main-screen UI hierarchy.

The final build emitted 109 `tsr_path_evidence_v1` records over 64.2 seconds. Reported
added processing was p50 5.845 ms, p95 7.240 ms, p99 24.725 ms, maximum 80.860 ms,
with zero 200 ms overruns. One geometry run abstained because preprocessing consumed
the 50 ms geometry allowance. All 109 records had a known capture clock and available
camera metadata. The input was 1600×1200 at rotation 180°, reduced to 288×216. Capture
age at evaluation had p95 485.830 ms and maximum 633.814 ms, including prior recognition
work; this is different from added processing time.

Intrinsics used the explicitly labeled Camera2 physical-sensor approximation:
normalized `fx=0.733948`, `fy=0.978597`, `cx=cy=0.5`. The sidecar recorded the supplied
1.6 m height and −0.08 m lateral mount offset with the level-camera assumption.
Metadata availability does not independently validate the physical mount or lens
calibration. GNSS history grew to five recent samples. The stationary scene produced
no retained road boundaries or sign associations, so this verifies runtime operation
and timing, not correct lane identification or applicability in traffic.

The local `live-summary.json` contains these aggregate checks without location or
sign-track payloads. Raw diagnostic snapshots remain only in the ignored report
directory. This short live run is neither a matched off/on interference measurement
nor the required recording/thermal endurance drive.

## Offline component replay

`RoadPathPerformanceInstrumentedTest` runs existing applicability without the new
road-path processing and with `RoadPathSession` enabled. Each pair receives the same
synthetic sign candidates. Their order alternates to reduce ordering bias. Timings use
`elapsedRealtimeNanos`; synthetic exposure/pose timestamps are used only as replay
inputs, never as elapsed-time measurements.

The enabled path includes metadata conversion, an owned luminance-buffer allocation,
stride-aware sampling, the production session's boundary detector, GNSS coordinate
conversion, histories, association and serialized diagnostics. It uses a background
worker and reports dispatch delay separately. Cold, warmup and measured samples count
toward the 200 ms assertion. Negative paired timing differences remain visible as
scheduling noise. It also reports absolute component costs so subtraction cannot hide
an overrun.

Inputs cover landscape, portrait, lane-like bright clutter, padded rows, two-byte pixel
stride, rotated input, and the two existing Panoramax stills. Neither a still nor
synthetic calibration establishes real sign applicability. A separate 24-track
synthetic triangulation control guarantees that valid three-view association is
exercised even if a photograph has no usable painted boundaries. Cancellation and
stale-observation assertions verify that invalid evidence remains unknown.

Build offline from `android/`:

```sh
./gradlew --offline :app:assembleDebug :app:assembleDebugAndroidTest
```

Run installed APKs on the only connected Moto g86:

```sh
./scripts/benchmark-road-path.sh
```

If updating the phone is authorized, explicitly request the installation step:

```sh
./scripts/benchmark-road-path.sh --install
```

The script only installs the two already-built debug APKs with `adb install -r`; it
does not build, download, uninstall or clear app data. With several connected devices,
select the Moto with `--serial SERIAL`. A non-Motorola or non-g86 target is rejected.
Use `--iterations 300 --warmup 12` to lengthen the component replay.

Results go to the ignored `android/app/build/reports/road-path/<run-id>/` directory.
They include device/build identity, APK hashes when installed, instrumentation output,
per-sample timings, p50/p95/p99/max, deadline counts, and thermal/memory snapshots.
The script verifies the report's unique run ID and completion status to reject stale
results. The report is retained before performance assertions fail.

## Live and sustained validation still required

This test excludes GPU sign inference, live CameraX delivery, encoder/photo workload,
map lookup, focal-characteristic retrieval, camera backlog and app-worker contention.
A component pass cannot establish the full live overhead target or on-road accuracy.
These exclusions are also stored in the machine-readable report.

Compare the same Moto, app build, route and settings with the experimental processing
off and on, with ordinary TSR, recording and photo capture active. Capture at least
30 minutes per configuration and record added p50/p95/p99/max, >200 ms events,
geometry-deadline abstentions, actual capture age, recognition throughput, encoder
drops, memory and thermal state. Preserve whether camera capture age is measured or
estimated. No recognition result should wait for a future frame or fix to complete
its trajectory history.

Keep positive controls beside wrong-road failures: the saved 24 September drive has
the main-road 90 at 550–562 s, wrong access-road 30 at 614–626 s, and valid 50 on the
exit actually taken at 1360–1370 s. Use real presentation timestamps, independent
per-sign review and exposure-aligned calibration. The recorded France candidate-only
corpus supplies regression evidence, but contains neither exact analysis images nor
verified sign applicability labels.
