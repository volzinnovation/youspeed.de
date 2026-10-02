# iPhone build 10024 fixes — 2026-09-30

Build 10024 (version 1.3) is installed on the attached iPhone 14 Pro, verified with CoreDevice's installed-app inventory. Automatic launch was denied because the device was locked; unlock and open YouSpeed. Device performance and sustained thermal behavior are not yet validated.

## Changes

- SpeedConsumer physical-device Debug builds now compile Swift with `-O`, retained debug logging and development signing. The Xcode project and `project.yml` both persist this setting; simulator Debug remains unoptimized. The actual signed build log confirms `-O` and `-DDEBUG`.
- Swift and Kotlin preview sessions now use a calibration generation anchored to stable measurements. Normalized principal-point drift up to 0.001 and focal-length drift up to 0.5% retain identity. These initial conservative tolerances must be evaluated on the next drive. The fixed anchor detects cumulative drift without rounding-bin chatter.
- Calibration revision, verification, mount dimensions/angles, availability, and larger intrinsic changes reset identity. Existing crop, image geometry, orientation, visual-calibration and session keys continue to invalidate history. Projection still uses the current frame's intrinsics.
- The new identity applies only to independent lane preview; the default TSR evidence path keeps its existing semantics. No speed-reference policy changed.
- iPhone preview logs now include luma sampling, filter, geometry and queue-wait timings, thermal state and build number. The 50 ms limit and thermal protection remain in place.

## Validation

- 63 native Swift lane XCTest cases passed, including tiny intrinsic drift maturing into visible lines, larger zoom and crop resetting maturity, and fixed-anchor cumulative drift, revision and calibration availability changes.
- 15 Android RoadPathSession tests passed, including equivalent regression cases. Android source is updated; only iPhone was installed in this follow-up.
- Signed physical-device build succeeded. Installed app inventory reports bundle `de.youspeed.SpeedConsumer`, build `10024`.
- `git diff --check` passed.

Evidence is preserved under `inspector/logs/2026-09-30-iphone10024-fix/`: build/compiler log, test logs, installation/locked-launch output, installed-app inventory and deployment manifest with executable SHA-256.

## Next test

Record a clearly painted stretch with the existing saved calibration, TSR and dashcam enabled. Confirm actual on-device budget success and sustained thermal behavior using the new stage timings before assessing residual lane jitter. This installation does not establish that thermal pauses or all line jumping have been eliminated.
