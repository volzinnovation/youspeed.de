# Build 10030: Data Manager on current main

## Source and integration

- Baseline: `main` at `366132e` (version 1.3 / previous build 10029).
- Ported Data Manager from `66ee6bb`; did not install its older version 1.1 baseline.
- Preserved the pre-existing local lane and Swiss-penalty changes. A recovery copy
  remains in the stash named `Preserve local changes before Data Manager on main 2026-10-02`.
- Data Manager is the first entry in Settings on both platforms.
- Retained main's download queues, cancellation, lookup pause during Settings and
  map deletion, camera calibration button, lane controls, and recording behavior.
- Region selection dismisses the search keyboard on both platforms.
- Shared speed-limit policy and Swift/Kotlin interpreter files have no changes.
- Committed and published on main at the owner's request before integrating PR #20.

## Verification

| Check | Result |
| --- | --- |
| Shared Data Manager geometry/asset contract | 6 passed |
| Android debug app and instrumentation APK builds | Passed |
| Android unit suite | 599 passed, no skips/failures |
| iPhone signed device build | Passed |
| iPhone simulator unit target | 588 executed, 26 fixture/platform skips, no failures |
| Final iPhone simulator UI flow | Passed |
| Final iPhone 14 Pro UI flow | Passed |
| Final Android emulator UI checks | 2 passed |
| Final Moto g86 5G UI checks | 2 passed |
| Whitespace/conflict-marker check | Passed |

The UI checks cover Data Manager being visible at the top of Settings without
scrolling; Map/List selection, return/back and reopening; the calibration button;
and reachable lane recognition settings. Android additionally exercises an
Overseas selection, Germany viewport reset and both landscape mounts. They use
synthetic app fixtures and do not download/delete the driver's map databases.
The large live-release map download test was excluded from the iPhone unit run.

Device UI automation initially required the owner to complete iOS's passcode
prompt. The final run succeeded after that prompt was completed. Android's new
navigation smoke uses a stationary fixture because current main intentionally
hides Settings while moving; node refresh handles Compose accessibility updates.

## Deployment

Version 1.3, build 10030 installed and launched normally on both attached phones:

- iPhone 14 Pro: `de.youspeed.SpeedConsumer`.
- Moto g86 5G: `de.youspeed.android.debug` (version name `1.3-debug`).

Both installs updated the existing app without uninstalling its data.

Local test results and deployment logs are under
`/tmp/youspeed-main-data-manager-20261002/`. Key evidence:

- `iphone-sim-v2.xcresult`: iPhone unit target and initial combined UI check.
- `iphone-sim-final.xcresult`: final UI, including top-of-Settings placement.
- `iphone-device-top.xcresult`: final physical iPhone UI check.
- `android-emulator-top.log`, `android-device-top.log`: final Android UI checks.
- `iphone-final-deploy.log`: completed install and normal launch.
- Android unit XML: `android/app/build/test-results/testDebugUnitTest/`.
