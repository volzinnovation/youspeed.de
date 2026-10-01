# Android crash diagnosis and lane performance-target correction — 2026-10-01

Android build 10023 crashed at **11:58:13.695 CEST** on October 1 with `IndexOutOfBoundsException` in `ConsumerSessionController.onLanePreviewPrepared`. The crash buffer, app's `uncaught_exception` event and process exit history agree. The recorded cause is an app exception, not a low-memory kill. Memory pressure is not required to reproduce it, and the device did not retain a useful memory measurement for that foreground exit.

## Cause and evidence

The lane pipeline selected boundary indices, then its final 50 ms deadline check discarded geometry without updating the already-created selection. Diagnostic formatting subsequently indexed the empty boundary list on the main thread. That fatal frame could not log its timing because formatting the event itself crashed. The exact delay on that exposure is unknown, but the same invalid state and exception are reproduced deterministically in the production Kotlin core.

The Swift implementation contained the same latent defect. Disabling persistent logging would not avoid the lookup, because diagnostic data was constructed before the logging-enabled check.

The final minute before the crash contains 193 successfully logged preview frames with no budget failures and preparation median/p95 of 14.61/27.84 ms. This was not a recorded sustained processing overload. The complete build-10023 log has 44 budget failures among 10,510 preview frames. None of those aggregate counts includes a successfully formatted event for the fatal frame.

Preserved evidence is under `inspector/logs/2026-10-01-android-crash/`: crash and exit records, 645,549,674 bytes of runtime diagnostics, 126,267,229 bytes of drive logs, GPS log, installed-package information, recording inventory, calibration preferences and source-frozen reproduction artifacts. No device data was cleared, app restarted or build installed during investigation.

## Applied correction

The user clarified that **50 ms is an engineering target, not a cutoff**. Both platforms now:

- Complete bounded lane preparation beyond 50 ms instead of cancelling sampling, filtering, detection, tracking or presentation solely because that time elapsed.
- Report `preparationTargetExceeded` in preview diagnostics and the equivalent preparation-performance flag in TSR sidecar diagnostics. A slow result does not by itself clear geometry or track maturity.
- Validate the selected indices before resolving boundary points. A malformed selection returns no selected boundaries and reports the invalid-index count, rather than throwing or partially rendering a different geometry snapshot.
- Keep geometry immutable after construction. Operation-limit failure still returns empty geometry and a rejected presentation together.

Existing image dimensions, operation caps, freshness, ordering, lifecycle and thermal controls remain. Independent preview does not inherit the separate 200 ms TSR sign-association budget; that separate association budget is unchanged. No shared speed-limit policy was modified.

## Validation

- **558 Android unit tests passed**, zero failures/errors/skips.
- **68 native Swift lane tests passed**, zero failures.
- Physical-device iPhone target compiled successfully with optimization enabled; compilation used `CODE_SIGNING_ALLOWED=NO` and did not install an app.
- The frozen baseline reproduces the late-deadline indexing exception. The corrected Kotlin core passes all eight combinations of preview/default mode with normal processing, 60 ms from entry, and crossing 50 or 60 ms after selection.
- Regression tests verify maturity survives slow frames, genuine operation exhaustion rejects consistently, invalid diagnostic indices do not crash, and existing association/lifecycle controls remain.
- `git diff --check` passed.

The first full Android run exposed one older test that expected the discarded 50 ms cutoff. It now verifies actual operation-limit exhaustion instead; the full rerun passed. Logs are `android-fix-tests-final.log`, `swift-fix-tests-final.log` and `iphone-fix-build-final.log` in the evidence directory.

## Recordings and remaining observations

The crash interrupted recording after approximately 11:01. Its **681,557,690-byte MP4** was copied completely, but lacks a readable `moov` index and cannot currently be opened by the decoder. The log has no recording-stop/finalize event. The unfinalized original and local copy are preserved; no recovery claim is made.

The earlier **869,550,963-byte low-light recording** opens, sampled frames and its tail decode, and the images show dawn/forest scenes with strong headlamp illumination on paint, followed by village roads and traffic. This supports the proposed contrast mechanism but is not an accuracy benchmark. The low-light contact sheet and video inspection hashes are preserved alongside the crash evidence.

A separate cadence issue remains: the final drive's median logged preview exposure interval is about 400 ms, despite much shorter processing time. The log reports no pending-frame replacements and substantial admission throttling. This should be traced independently after the crash fix; removing the 50 ms cutoff alone does not establish smoother dashed-line tracking or higher frame cadence.

**Installation status:** The corrections are tested in the working tree only. Android remains on build 10023 and iPhone on build 10024; neither contains this new correction yet. No commit, push or deployment was performed.

Details: [root-cause reproduction](LANE_ANDROID_CRASH_ROOTCAUSE_2026-10-01.md), [Android drive-log audit](LANE_ANDROID_LOG_AUDIT_2026-10-01.md), [earlier dashed-line research](LANE_DASHED_LINE_RESEARCH_2026-10-01.md).
