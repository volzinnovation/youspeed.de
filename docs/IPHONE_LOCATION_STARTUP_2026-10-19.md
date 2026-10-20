# iPhone location after a long capture drive — 19 October 2026

## Observed evidence

Inspected the attached iPhone 14 Pro running the installed YouSpeed 1.4 (10053).
Copied selected app logs and the capture-batch checkpoint without removing the
phone originals. Private evidence is outside the repository at
`/private/tmp/youspeed-location-20261019/`; it contains coordinates and must remain
private. No photos were needed for this diagnosis.

Times below are Europe/Berlin (CEST, UTC+2):

| Time | Observation |
| --- | --- |
| 15:22:26–16:25:13 | Return drive has 3,722 recorded fixes. Median horizontal accuracy is 2.04 m; final accuracy is 3.72 m. The largest interval between logged fixes is 31 seconds. Median map query time is 39.131 ms. |
| 15:26:07–16:24:47 | Capture batch contains 1,843 image records, consistent with the recorder's final photo count. GPS continued after the final image. The batch JSON is a checkpoint with journals, so its upload state is not treated as current. |
| 16:25:12 | Application becomes inactive. Camera/automatic photo capture shuts down normally; the final GPS row follows at 16:25:13. |
| 16:57 and 18:40 | Subsequent launch logs show foreground activity and a mounted dashboard, but capture configuration remains `driving=false`. There is no drive-start policy event, no new GPS row, and both corresponding matcher logs are empty. |
| 20:46–20:47 | Opened the existing installed app and inspected its screen through QuickTime. It initially showed the >100 MB log-review prompt. After the user continued, the dashboard resolved a location and speed limit. A fresh read of the GPS log contained 23 additional rows, ending at 20:47:34 with `matched` status. |

The saved drive does not show GPS progressively failing as images accumulate.
The later failing sessions show that normal driving/location tracking never
started. The successful live launch demonstrates that this is intermittent;
it does not establish the cause of every possible location outage.

## Startup defect and correction

`SpeedConsumerRootView` can mount `MainView` before map/onboarding preparation is
finished through its driving-controls safety branch. Previously, the dashboard
called `startDriving()` only in `onAppear`. That call returns while onboarding
state is not loaded or onboarding must be presented. If the same dashboard stays
mounted when preparation finishes, there is no second appearance and no new
location request. This source-level race is consistent with the later logs;
those logs alone do not prove which guard returned during each launch.

The dashboard now observes explicit startup readiness, including initial
readiness and foreground entry. It starts only when log review, map preparation
and onboarding are ready, the scene is active, and driving is stopped. Readiness
notifications cannot restart an already-running drive. The existing location
authorization/update implementation is preserved in a small helper; DEBUG-only
tests intercept that boundary without requesting actual location permission.

Android already observes startup readiness in `ConsumerAppUi`'s `LaunchedEffect`
and calls `startDriving()` once ready. This fix restores the same automatic-start
behavior on iPhone. It does not change capture outputs, network gating, bundle
schemas, or the protected speed-limit reference policy.

## Verification

The simulator suite passed **22 tests**: three new dashboard-startup regressions,
five recording-startup regressions, and 14 existing control-availability tests.
The new tests host the real SwiftUI dashboard and verify delayed preparation,
background-to-foreground startup, no duplicate start after readiness updates,
and blocking without a map or completed onboarding. Fixtures wait for initial
disk preparation before replacing its result to avoid asynchronous test races.

Result: `location-final-regressions-2.xcresult` in the private evidence directory.
`git diff --check` passes. The initial physical inspection used the existing
installed build. Subsequent installation and hardware verification of the fixed
build are recorded below.

## Requested device installation follow-up

At the user's subsequent request, built and signed the fixed app for the attached
iPhone and installed it successfully at approximately 20:53 CEST. The development
build retains version 1.4 (10053); its executable UUID is
`1BFDEC21-B69D-38B2-9978-58F031A81586`, distinct from the original TestFlight
executable. Installation retained the existing app container. The pre-test
inventory contains 3,732 JPEGs. Existing MOV recordings were also retained.

Added an explicit physical UI test for three recording start/stop cycles, cold
relaunch, and foreground recovery. The standard isolated test script skips this
class unless `--installed-app-ui-tests` is selected. No screenshot/GPS/camera
fixture is enabled for this flow. Saved video files and live GPS rows are
checked separately after the UI flow.

The first hardware attempt could not initialize because iOS displayed its
passcode prompt to enable XCTest automation. It timed out before executing the
test body. A later attempt overlapped installation/UI testing from the separately
authorized “Diagnose stale street references” chat and its runner was killed;
this is not evidence of an application recording crash. Device access was then
coordinated under the user's explicit authorization in that chat.

An exclusive attempt found an additional startup guard mismatch: the Record
button was enabled before saved-photo queue maintenance finished. Its handler
rejects starting during that period, so an early tap was silently ignored.
The Start control now remains disabled while that existing guard is active;
Stop remains available. The physical UI test waits for enabled readiness.

The combined source, including both chats' fixes and this control correction,
was built and installed as **1.4 (10054)**. Its executable UUID is
`CAD8910C-9635-34C2-94D5-3E094F2F83F2`. At 21:09 CEST a queued hardware test was
waiting for the device to unlock before launching. Some early temporary evidence
under `/private/tmp/youspeed-device-fixed-20261019/` is no longer present. The
final run and copied device evidence are retained at the path below.

## Completed hardware verification

After the user unlocked the iPhone and requested a retry, the final exclusive
hardware test **passed** at 21:52 CEST on build **10054**. It exercised three
start/stop/save cycles with real camera and GPS, a cold app relaunch after the
first clip, and Home/foreground recovery after the second. It checks the actual
`REC` indicator; the SwiftUI module chip does not consistently expose its
accessibility value to XCTest. No screenshot or simulated-location fixture was
enabled. Earlier user-interrupted and assertion-refinement runs are not counted
as successful application tests.

All three finalized MOV files were copied without removing the phone originals
and fully decoded with native AVFoundation on the Mac:

| Clip | Duration | Dimensions | Decoded frames | GPS fixes during recording | Median GPS accuracy |
| --- | --- | --- | --- | --- | --- |
| 1 | 11.80 s | 3840 × 2160 | 354 | 12 | 3.19 m |
| 2 | 11.77 s | 3840 × 2160 | 353 | 11 | 3.01 m |
| 3 | 11.97 s | 3840 × 2160 | 359 | 12 | 2.79 m |

The complete final test window contains **45 fresh GPS fixes**, from
21:51:26.540 to 21:52:20.999 CEST, all `matched`, with median horizontal accuracy
2.99 m. This includes both sides of the cold relaunch and foreground cycle.
All **3,732 pre-existing JPEG paths** and both pre-existing MOV paths remain on
the device. Test clips remain in the local video library. No media was uploaded.

This is a stationary hardware smoke test; sustained driving with many new
images remains a separate real-world validation scenario.

Private evidence: `/private/tmp/youspeed-phone-verify-20261019-2144/` contains
`physical-recording-indicator.xcresult`, `test-summary.json`,
`hardware-validation-summary.json`, `clips-selection.json`,
`clips-decoded.jsonl`, the copied clips, GPS CSV, and the two recording-session
logs. Raw GPS and video stay outside the repository. The other authorized chat
was notified that exclusive device testing was finished before its next tests.

## Build 10055 recording verification

At the user's request, repeated the same real-camera recording test on the
attached iPhone with the normal **1.4 (10055)** app at 22:21–22:22 CEST.
Installed version and local product identity were checked before running.
Executable UUID: `B600CECA-C274-3E53-98A9-BD3F797E150E`.

The physical UI test **passed**: three start/stop/save cycles, cold relaunch after
the first clip, and background/foreground recovery after the second. All three
new files fully decoded using native AVFoundation:

| Clip | Duration | Dimensions | Decoded frames | Matched GPS fixes during recording |
| --- | --- | --- | --- | --- |
| 1 | 11.73 s | 3840 × 2160 | 352 | 10 |
| 2 | 11.63 s | 3840 × 2160 | 349 | 12 |
| 3 | 12.10 s | 3840 × 2160 | 363 | 12 |

The test window contains **43 fresh GPS fixes**, all `matched`, with median
horizontal accuracy **8.63 m**. All **3,732 existing JPEGs** and **eight existing
MOV files** remain present. The three new clips remain on the iPhone; no media
was deleted or uploaded. This repeats the stationary smoke-test scope above.

Private evidence: `/private/tmp/youspeed-dashcam-10055-20261019/` contains
`recording.xcresult`, `test-summary.json`, `build-identity.json`,
`validation-summary.json`, `decoded-clips.jsonl`, SHA-256 clip records, copied
video, GPS and camera-session logs. No application source changes were needed
for this validation.

Selected original-investigation source SHA-256 hashes (historical inventory in `analysis-summary.json`):

| Source | SHA-256 |
| --- | --- |
| Original `gps_fix_log.csv` | `46fdfb0b334618ebc940fede3307a1c577b9b0e2d801efb27569a482f2c81086` |
| Drive TSR log | `d9c20da6481574c9b927464fde7ce56e9f4787ca8801d6d929219a6ed13449e0` |
| 18:40 launch TSR log | `4e8466b0b9b93b26637603626be7ded1437541f6dc9e676cd3621edf22025b94` |
| Live GPS read | `5a82349a6470bff85a483e2280b7674066dda792cfe274d4ff2659c1960865df` |
