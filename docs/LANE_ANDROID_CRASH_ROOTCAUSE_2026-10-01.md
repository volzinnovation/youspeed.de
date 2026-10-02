# Android lane-preview crash root cause — 2026-10-01

The recorded foreground crash is a lane-preview result-consistency bug. It is **not recorded as an out-of-memory termination**. A late preparation deadline clears the detected boundary list but leaves the previously computed visible boundary indices intact; diagnostic formatting then indexes the empty list. The same defect was present in Swift; both working-tree implementations are now corrected.

The user subsequently clarified that **50 ms is an engineering performance target, not a cutoff** and authorized correction. The working-tree implementation now removes that time-based cancellation on both platforms, preserves operation limits and lifecycle/freshness protection, and reports target misses as telemetry. No application was deployed and no shared speed-limit policy was changed.

## Device evidence

The retrieved Android crash buffer records the fatal exception at **2026-10-01 11:58:13.695 CEST** in process `de.youspeed.android.debug`, PID 7750, on the main thread:

```text
java.lang.IndexOutOfBoundsException: Empty list doesn't contain element at index 1.
  kotlin.collections.EmptyList.get(Collections.kt:37)
  ConsumerSessionController.onLanePreviewPrepared$app_debug(ConsumerSessionController.kt:1291)
  AndroidTrafficSignCameraRuntime$laneRuntime$6.invoke(AndroidTrafficSignRuntime.kt:823)
  AndroidLaneDetectionRuntime.drain$lambda$14$lambda$12$lambda$11(LaneDetectionRuntime.kt:400)
```

`dumpsys activity exit-info` independently records PID 7750 at **11:58:13.718** as reason **4 — APP CRASH(EXCEPTION)**, importance 100. The PSS/RSS fields are unavailable/zero-valued in this entry; they do not measure the process's peak memory use. Later entries marked `TOO MANY EMPTY PROCS` or `SmartBackground` concern background processes and do not explain this foreground exception. There is no need to infer an OOM to explain the captured stack trace.

Evidence: [crash buffer](../inspector/logs/2026-10-01-android-crash/crash.txt), [process exit history](../inspector/logs/2026-10-01-android-crash/exit-info.txt). The parent device audit records installed-build and collection details.

## Original failure path

The following line references describe the captured pre-fix sources frozen with the reproduction; subsequent edits shift current line numbers.

1. `RoadPathSession.prepare` detects boundaries and computes a `RoadBoundaryPresentationSnapshot` against that particular boundary list. A mature result can have selected indices such as `[1]`.
2. After the presentation gate and ego-side selector finish, the final time check runs. At **50 ms or more**, Android `RoadPathSession.kt:192–195` resets temporal/gate/selector state and replaces geometry with an empty, budget-exceeded `RoadBoundaryFrame`.
3. The local `presentation` value is **not replaced**. The returned `RoadPathPreparedFrame` combines empty geometry with an accepted snapshot whose indices reference the discarded geometry. Resetting the stateful gate does not modify this already-created snapshot.
4. Overlay publication correctly suppresses that frame because its geometry is budget-exceeded. This protects the overlay mapping at `RoadPathSession.kt:213`, but does not sanitize the returned diagnostic result.
5. `LaneDetectionRuntime.kt:400` queues the prepared result on the main executor. The `runCatching` around worker-side preparation has already finished; it does not enclose this later callback.
6. `ConsumerSessionController.kt:1291` formats diagnostic boundary points using `frame.geometry.boundaries[i]`. An index remaining in the old presentation now indexes `emptyList()`, producing the captured exception.

Disabling persistent debug logging would not prevent it: Kotlin evaluates the complete `mapOf(...)` argument before calling `appendRuntimeDiagnosticEvent`. The logging-enabled ticket guard is inside that function at `ConsumerSessionController.kt:6021`, after the unsafe lookup would have run.

The fatal frame's `lane_preview_frame` event cannot be relied on to report the deadline: constructing that event is the operation that crashes. The stack trace proves the empty-list mismatch; source inspection and the probe below establish the late-deadline path that creates it. They do not establish the exact wall-clock duration or cause of the delay on that particular exposure. CPU scheduling, GC, thermal effects or concurrent camera/inference work could increase latency, but none is required to explain the invalid result or demonstrated as its initiating delay here.

## Deterministic reproduction with production Kotlin core

The offline probe compiles the actual Kotlin image filter, detector, temporal tracker, presentation gate, selector and `RoadPathSession` into a small JVM executable. It processes eleven identical **128×72** images with two painted stripes, allowing both tracks to mature. It does not construct a malformed prepared result by hand.

Only the existing injected clock is controlled. A baseline pass counts clock calls on the eleventh frame. A second identical pass returns 1 ms for earlier calls, then 50 ms at the final readiness check. The same boundary-point formatting expression used by the Android callback runs against the returned result and captures the resulting exception.

| Condition | Geometry boundaries | Visible indices | Presentation accepted | Overlay published | Diagnostic formatting |
| --- | ---: | --- | --- | --- | --- |
| Entire preparation at 1 ms | 2 | `[0, 1]` | true | true | succeeds |
| Deadline exceeded from the first check | 0 | `[]` | false | false | succeeds |
| Deadline reached only at final readiness check | 0 | `[0, 1]` | **true** | false | **IndexOutOfBoundsException** |

The late case reproduced with `previewMode=true` and `previewMode=false`. This fixture throws on index 0 because it selects both sides; the device threw on index 1 because that was its first selected index. Both failures have the same invalid empty-list access. This host probe validates result consistency, not device performance or the exact original image contents.

Artifacts under `inspector/logs/2026-10-01-android-crash/`:

- `LateDeadlineProbe.kt` and `run-late-deadline-probe.sh` reproduce the pipeline and diagnostic expression.
- `late-deadline-probe.json` contains all six results (normal/early/late in both session modes).
- `probe-sources/` freezes the ten production Kotlin core sources; `late-deadline-source-sha256.json` records their hashes.
- `LaneImageGeometry.kt` and `NormalizedTrafficSignBoundingBox.kt` are exact extracted production value types, avoiding an Android UI dependency in the host executable.
- `late-deadline-probe.jar` and `late-deadline-probe-compile.log` preserve the successful binary and compiler diagnostics.

Run from the repository root:

```sh
bash inspector/logs/2026-10-01-android-crash/run-late-deadline-probe.sh
```

The existing early-deadline unit test checks suppressed geometry/overlay, but does not first mature a visible track and then cross the deadline after selection. That difference explains why its passing result did not cover this failure.

## Swift parity and applied working-tree correction

Swift `RoadPathSession.swift:335–336` also empties geometry after computing presentation without replacing the snapshot. `LaneDetectionRuntime.swift:356` then uses `prepared.geometry.boundaries[$0]` while constructing a diagnostic dictionary. Its dictionary is constructed before invoking the optional diagnostic callback. The pre-fix Swift source therefore contained the equivalent array-bounds trap. This was a **latent source vulnerability**, not evidence that the reviewed iPhone drive crashed this way.

The user's clarification changes the correction: **do not discard completed lane geometry simply because preparation reaches 50 ms**. Both `RoadPathSession` implementations now run their bounded pipeline without the 50 ms cancellation callbacks, late geometry clearing or publication rejection. Swift's camera luma sampler also no longer abandons a bounded copy for crossing that target. A computed `performanceTargetExceeded` flag records preparation above 50 ms; `preparationPerformanceTargetExceeded` adds the same distinction to sidecar diagnostics.

Dimensions, detector/temporal/presentation operation limits, preview freshness, thermal admission, clock, source-ordering, calibration and lifecycle checks remain. The separate 200 ms cumulative TSR association budget remains; the independent preview does not inherit that sign-association limit. Real operation-budget exhaustion still produces empty geometry and a rejected presentation together. A configurable session detector cap defaults to the existing 250,000 operations, cannot exceed that cap, and allows the regression to exercise actual exhaustion at 100 operations.

Overlay publication now uses the same defensive selected-boundary validation helper as the consumer diagnostics. A malformed selection yields no selected boundaries as a whole, instead of partially indexing unrelated output. Diagnostic points/counts/IDs are derived consistently, and invalid indices can be reported without crashing. This is defensive protection in addition to removing the invalidating cutoff.

New Swift/Kotlin session tests cover:

- Repeated 60 ms preparations that retain two detected boundaries and mature both tracks in preview and default session modes.
- Crossing exactly 50 ms or 60 ms at the final readiness clock read, after mature selection, with geometry, indices and overlay remaining coherent; then a timely frame without losing maturity.
- A real detector operation limit of 100 operations rejecting geometry and presentation together, independently of elapsed time.
- A 250 ms independent preview retaining its current output rather than inheriting the separate TSR association deadline.
- Existing cumulative 200 ms association rejection and lifecycle/ordering tests retained.

The baseline failing probe and frozen sources remain intact. Corrected-source probe results are stored separately in `inspector/logs/2026-10-01-android-crash/fixed-probe/`, together with its sources, source hashes, executable and compiler log. The corrected Kotlin probe preserves two mature boundaries, publishes a coherent overlay and produces no diagnostic exception in all eight combinations: preview/default × 1 ms, 60 ms from entry, exactly 50 ms after selection, and 60 ms after selection. The 60 ms cases report a target miss without rejecting geometry. Full application test/build results are recorded by the parent task's validation report. Device-load and driving validation still require a later explicitly authorized deployment.
