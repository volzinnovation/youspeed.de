# Android crash and memory review — 2026-10-01

**Follow-up:** The phone was subsequently connected. The captured crash is a lane-result indexing exception, not a recorded OOM termination; see [confirmed cause and correction](LANE_ANDROID_CRASH_FIX_2026-10-01.md). The analysis below records the earlier hypotheses before device evidence was available.

The reported Android crash is **not yet diagnosed**. The Android device was unavailable during this review, and the retained September 29–30 evidence does not contain an app crash stack, low-memory kill record, or memory trace from the newly reported incident. Memory pressure is plausible, but a native camera/GPU failure, Java exception, ANR, or recorder failure must remain separate possibilities.

This is a source review plus an audit of older local evidence. No production changes, device commands, installs, or video decoding were performed for this review. Line references describe the working tree on October 1; they are not a claim that the currently installed Android build contains every working-tree change.

## What the retained evidence establishes

- `inspector/logs/2026-09-30-build10021-device/crash-log.txt` contains September 26 vendor initialization messages, not a YouSpeed fatal exception. Its `beginning of crash` header identifies the log buffer; it does not establish an app crash.
- Searches of `inspector/logs/2026-09-30-tsr-independence/logcat.txt` and the retained road-path replay process logs found no `OutOfMemory`, `FATAL EXCEPTION`, `lmkd`, `am_kill`, `Fatal signal`, `SIGABRT`, or `SIGSEGV` evidence attributable to this new incident. These are older, limited log windows, so absence is not evidence that the new drive was healthy.
- The build 10022 runtime log has recording start at **2026-09-30 14:39:45.276 UTC** and stop at **15:08:46.358 UTC**, with **1,740.403 seconds** recorded. This preceding drive reached a stop callback; it cannot explain a later crash.
- An older instrumented replay has one mid-run snapshot of **482,108 kB PSS / 644,957 kB RSS**, including **126,472 kB native heap PSS** and **145,969 kB graphics**. Evidence: `android/app/build/reports/road-path/drive-20260929-1143/correction-replay/moto-replay/full-20260929-01/memory-midrun.txt`. The same replay's `instrumentation.txt` ends with `OK (1 test)` after 963 seconds. This demonstrates that graphics/native allocations matter; it is not a live-drive memory measurement or proof of a leak. Before and mid-run PIDs differ, and `memory-after.txt` says no process was found after instrumentation ended, so these files cannot be treated as a before/after leak measurement or a crash.

## Ranked areas to measure

The ordering is investigation priority based on allocation size and ownership, not a probability estimate of the crash cause.

| Priority | Area | Confirmed code behavior | What remains unproven |
| --- | --- | --- | --- |
| 1 | TSR conversion plus camera/GPU resources | Full-resolution ARGB source, reusable full-resolution rotation target, and sometimes a separate calibrated crop coexist. Two LiteRT models, camera analysis, preview, movie, and optional still output also share the process/device. | Actual peak allocation at the reported crash; native/GPU leak; which consumer was active. |
| 2 | Runtime replacement during model/camera changes | Backend close is asynchronous on its inference executor. A replacement can begin initialization on another executor before old disposal has completed. | Whether any replacement occurred near the crash, whether overlap was material, or whether native resources failed to release. |
| 3 | Calibration preview while UI is blocked | Up to 5 fresh display bitmaps per second are posted to the main handler without replacing older pending preview posts. The separate full-size calibration rotation target remains until camera runtime release. | Whether calibration was open; main-thread backlog; persistent bitmap retention. |
| 4 | Independent lane preparation and result delivery | Preview adds a 10 Hz preparation path beside TSR's preparation; small arrays are allocated repeatedly, and every completed result posts to main. | Whether this increased CPU/GC or main-thread pressure enough to contribute. There is no unbounded camera-frame queue in this lane worker. |

### TSR has the largest visible allocation opportunities

[`CameraXTrafficSignFrame.withOrientedBitmap`](../android/app/src/main/java/de/youspeed/android/alpha/AndroidTrafficSignRuntime.kt#L204) calls `image.toBitmap()` for each admitted TSR frame and recycles the source after inference. [`AndroidTrafficSignBitmapRotation.orient`](../android/app/src/main/java/de/youspeed/android/alpha/AndroidTrafficSignBitmapRotation.kt#L22) retains one reusable ARGB target for nonzero rotation. [The calibrated crop](../android/app/src/main/java/de/youspeed/android/alpha/AndroidTrafficSignRuntime.kt#L703) allocates another bitmap, which is explicitly recycled afterward. These lifetimes are bounded, but simultaneous transient memory can still be substantial.

For ARGB pixel storage alone, one 1600×1200 frame is **7.32 MiB**, 1920×1440 is **10.55 MiB**, and 3840×2160 would be **31.64 MiB**. The latter is a size illustration, not the measured Android analysis resolution. The older build 10022 first-frame log reports 1920×1440 before the recording graph changes, while later path geometry uses 1600×1200. Measure the actual active resolution instead of assuming that the requested 1920×1080 is guaranteed.

[Persistent engine buffers](../android/app/src/main/java/de/youspeed/android/alpha/AndroidTrafficSignRuntime.kt#L361) account for approximately **34.05 MiB** before model allocations: 18.75 MiB detector float input, 12.50 MiB detector bitmap plus integer pixel array, 1.79 MiB output buffer plus float copy, and approximately 1 MiB classifier/encoder storage. This excludes model mappings, interpreter tensors, GPU delegates, camera surfaces, maps, framework overhead, and per-frame bitmaps. These calculated capacities are not measured resident memory.

The [camera graph](../android/app/src/main/java/de/youspeed/android/alpha/AndroidTrafficSignRuntime.kt#L1095) requests analysis with keep-only-latest backpressure and separately binds preview, optional stills, and movie recording. Movie output is streamed to a file; the application does not load the growing movie into a byte array. A large dashcam file alone is therefore not evidence of Java heap growth. Codec or camera native resources still require measurement.

Android's official documentation explains that modern bitmap pixel data occupies native memory, so Java heap alone is an incomplete measure. [Android bitmap memory guide](https://developer.android.com/topic/performance/memory/guide/bitmaps).

### The lane worker is bounded, with a small avoidable allocation cost

[`AndroidLaneDetectionRuntime`](../android/app/src/main/java/de/youspeed/android/alpha/LaneDetectionRuntime.kt#L250) holds one working frame, at most one pending downsampled frame, and a two-array free pool. It copies admitted luma synchronously before TSR takes image ownership. Preview input is bounded to **384×216 = 82,944 bytes**. Replacing a pending frame discards the old work; it does not accumulate camera images.

[`RoadPathLaneFilter`](../android/app/src/main/java/de/youspeed/android/alpha/RoadPathLaneFilter.kt#L18) creates two similarly bounded arrays. [`RoadBoundaryTemporalTracker`](../android/app/src/main/java/de/youspeed/android/alpha/RoadBoundaryTemporalTracker.kt#L144) retains a copy of only the preceding luma image and at most six selected boundaries. [`RoadPathSession`](../android/app/src/main/java/de/youspeed/android/alpha/RoadPathSession.kt#L222) replaces grayscale with an empty array before returning a prepared result. However, [the UI delivery closure](../android/app/src/main/java/de/youspeed/android/alpha/LaneDetectionRuntime.kt#L400) references the original `frame` to check its epoch/scope, so that closure can still retain the small luma array while waiting on main. Capture only the primitive epoch/scope and coalesce pending deliveries; a blocked main thread could otherwise retain about 0.79 MiB of these arrays per second at 10 Hz, plus geometry/closure objects. No such backlog has been measured in the reported incident.

There is a concrete allocation inefficiency: preview `roadFrameFactory` allocates new luma in [`roadPathFrame`](../android/app/src/main/java/de/youspeed/android/alpha/AndroidTrafficSignRuntime.kt#L181), bypassing reuse from the lane worker's pool. The pool nevertheless retains two completed preview arrays. With filtering and tracker copying, the straightforward array traffic is up to roughly **3.16 MiB/s at 10 Hz**, excluding small objects and the independent TSR path. This is churn, not an unbounded leak. Safe buffer reuse or shared immutable preparation should be benchmarked; reuse must preserve the temporal tracker's ownership and session independence.

The [diagnostics executor](../android/app/src/main/java/de/youspeed/android/alpha/ConsumerSessionController.kt#L457) is bounded at 128 tasks and discards oldest pending diagnostics. Main-handler/result posts are not similarly coalesced. Lane callbacks can retain small downsampled luma through the closure described above; calibration posts carry substantially larger display bitmaps and deserve earlier attention if the incident occurred in calibration.

## Evidence to collect from the Android device

Before clearing logs, force-stopping, reinstalling, or starting another test, save the following read-only outputs using the actual attached serial and installed package:

```sh
adb -s SERIAL shell dumpsys package de.youspeed.android.debug > package.txt
adb -s SERIAL shell dumpsys activity exit-info de.youspeed.android.debug > exit-info.txt
adb -s SERIAL logcat -b crash -d -v threadtime > crash.txt
adb -s SERIAL logcat -b all -d -v threadtime > logcat-all.txt
adb -s SERIAL shell dumpsys meminfo de.youspeed.android.debug > meminfo-current.txt
adb -s SERIAL shell dumpsys thermalservice > thermal-current.txt
adb -s SERIAL shell dumpsys media.camera > camera-current.txt
adb -s SERIAL shell dumpsys media.codec > codec-current.txt
adb -s SERIAL shell df -h /data > storage-current.txt
```

Also transfer app runtime diagnostics, drive/match logs, recording file inventory and the relevant clips while retaining the device originals. Match crash/exit timestamps, PID, package/build, last `capture_configuration`, last successful inference/preview, model-switch events, and recording start/progress/stop. Inspect video metadata and tail decodability: a missing finalization callback or truncated movie is evidence of interrupted recording, not a diagnosis of why the process stopped.

Classify the evidence explicitly:

- **Java exception / OOM:** app-matching fatal stack, including allocation size and allocating callsite if present.
- **System low-memory kill:** relevant `ApplicationExitInfo` reason, correlated with system log/process timing. Some devices report a signaled SIGKILL instead; SIGKILL alone is insufficient to identify memory pressure.
- **Native crash:** tombstone/abort message, native backtrace, signal, process and build identity. Distinguish LiteRT/GPU, camera/codec, and application native code.
- **ANR:** exit info and traces; inspect lock waits, GPU stalls, and main-thread backlog.
- **Recorder-only failure:** app remains alive and `VideoRecordEvent.Finalize` reports an error; correlate with free storage and camera/codec events.

These are distinct exit categories in [ApplicationExitInfo](https://developer.android.com/reference/android/app/ApplicationExitInfo); [ActivityManager.getHistoricalProcessExitReasons](https://developer.android.com/reference/android/app/ActivityManager#getHistoricalProcessExitReasons(java.lang.String,int,int)) can persist a compact classification on next app start. Current source has no corresponding app-level exit-history capture.

## Recommended implementation and validation order

1. Preserve and classify the actual incident first. Add compact next-start exit-history reporting, active camera/model configuration, periodic PSS/native/Java/graphics measurements, memory-pressure events, and queue depth/drop counters. Avoid continuous heap dumps during driving.
2. If memory pressure is confirmed, remove redundant full-size TSR rotation/crop intermediates by applying rotation/crop/letterboxing into existing model-sized storage. Preserve the pinned model's sampling/crop geometry and classifier detail; verify detection parity before replacing preprocessing. Sequence old-model disposal before replacement construction, with diagnostics proving resource lifetimes.
3. Coalesce calibration previews and lane result delivery to the latest pending UI result. Release calibration-only rotation storage after calibration ends using its owning worker and safe UI bitmap ownership. Do not recycle a bitmap still used by Compose.
4. Reuse bounded lane scratch storage or share eligible preprocessing without changing independent preview/TSR state. Implement proposed left/right lane zones as masks/search bands over the same small luma image; do not introduce two full-resolution RGB copies or two model instances.
5. Run an attached-device matrix with TSR, lanes, movie and still capture individually and together, plus repeated start/stop/calibration/model changes. Record memory at steady intervals and after each stop, with a long combined session at least as long as the failed drive. A stable plateau and clean disposal are useful evidence; one successful short run does not establish that the original crash is fixed.

Retain the user's selected recording quality while measuring and removing avoidable copies. The current evidence does not justify lowering dashcam quality, disabling thermal protection, increasing the lane deadline, or labeling the incident an out-of-memory crash.
