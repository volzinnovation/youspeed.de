# TestFlight feedback and iPhone recording startup — 19 October 2026

## Evidence

Read App Store Connect's screenshot and crash feedback APIs for app 6787469256.
There are 14 screenshot submissions, including three for 1.4 (10053), build ID
`3e818c45-d946-46b6-a031-a7df5b6f9b7b`:

| Feedback | Observation | Resolution |
| --- | --- | --- |
| `AEHQeBwbO8FIjUjDWpWUHMQ` | German onboarding displays `onboarding.back`, wrapped across two lines. | Use the localized-key initializer at the Back call site. The same defect affected startup Retry and is corrected there too. All four translations already existed. |
| `ADwJah2GtcZ77cpRdwXVVu8` | Dashcam onboarding shows a gallery screenshot without showing how to begin recording. | Put start instructions first, add an unmodified native dashboard capture with the red recording control, explain stop/save, then retain the library example. Added English, German, French and Dutch copy. |
| `AFK-un2sK8DDCHfnSdhAsf4` | Tester indoors sees “Suche Signal” without controls. | The existing workspace changes restore setup controls without a usable signal. Focused control tests pass, including signal-loss recovery and fresh-moving-fix relocking. Those control changes predate this task and were preserved. |

The crash feedback collection returned **zero submissions**. After the paired
phone reconnected, two matching device reports were retrieved without removing
the originals:

| Device report | Build | SHA-256 |
| --- | --- | --- |
| `SpeedConsumer-2026-10-19-122915.ips` | 1.4 (10053) | `25140381e7407ac08c2e07cfadc61e0758950aa0e130014c07a0c51e091ab953` |
| `SpeedConsumer-2026-10-19-122948.ips` | 1.4 (10053) | `eb1e8c4d2990932672e5302226eb5c463c793233a376d51ee9faaf0ebaf4838c` |

Both terminate with main-thread `EXC_BAD_ACCESS / KERN_PROTECTION_FAILURE` at a
stack guard. Their repeated application-frame cycle ends inside sorted JSON
serialization, consistent with recursive capture-state/configuration logging.
The application image UUID is `9fbfc306-069c-3b92-b14b-65b4a228beda`. A matching
local dSYM was not found; the application frames were not fully symbolicated.

Private feedback JSON, screenshots and device crash reports are retained outside
the repository in `/private/tmp/youspeed-testflight-fix-20261019/`. Signed screenshot
URLs, tester contact details and full device reports are not copied here.

## Crash cause and targeted fix

The build-10053 source has this synchronous notification loop:

1. The recorder enters recording and calls `onChange`.
2. `syncDriveRecorderState()` calls `reconcileAutomaticCapture()`.
3. For a user-started recording, reconciliation unconditionally reapplies the TSR
   setting, including the default disabled setting.
4. `setTrafficSignRecognitionEnabledDuringRecording(false)` unconditionally
   notifies `onChange`, even though TSR was already disabled.
5. The loop repeats until the main stack is exhausted.

Two bounded regressions reproduced the defect before the targeted fix: the real
view-model/coordinator callback reached the eight-notification recursion cap, and
ten unchanged disable requests emitted ten notifications and overwrote recording
detail. The cap prevents the test host itself from overflowing.

The TSR setter is now idempotent for an already-committed state. Repeated
unavailable-enable failures also avoid duplicate notifications. Reconciliation
only applies a changed selection and waits for a usable output before enabling
recognition. This breaks the feedback loop while keeping independent TSR,
Dashcam and photo selections intact.

## Recording startup changes

`DriveCaptureCoordinator` previously configured the entire 4K/movie/photo/video
session on MainActor while start and stop used a separate serial queue. Graph
configuration now runs on that same serial queue. Output availability returns as
a value and is published on MainActor only if the request generation is still
current and preparing. A Stop during configuration cannot revive stale startup
state, and a thrown configuration still releases the queue for subsequent work.

Movie startup now checks that the session is running, the output is idle and its
video connection is enabled. Codec overrides require both the codec-setting key
and an advertised HEVC/H.264 capability; otherwise the native default remains.
The previous unconditional H.264 fallback could pass an unadvertised value to an
Objective-C setter. Initial recording and live Dashcam activation share these
checks, with normal failure-state handling when the connection is unavailable.
A startup log records the preset and advertised codecs.

These additional changes address startup risks separate from the reproduced
notification recursion. A subsequent physical-camera run passed on development
build 10054: three start/stop/save cycles, cold relaunch and foreground recovery,
with all three 4K clips fully decoded. See
`docs/IPHONE_LOCATION_STARTUP_2026-10-19.md` for the device results. No replacement
TestFlight build is uploaded.

The native recording-control image uses the existing simulator demonstration
fixture at 0 km/h, portrait, iPhone 17 Pro (iOS 26.5). Its pixels are copied without
redrawing the interface; the street/city are fixture data. It contains no captured
camera image or tester data. The UI regression fixture is DEBUG-only and requires
the separate `.TestHost` app container; it does not download maps or request
location/camera permission.

Android's CameraX path retains its existing start/finalize and independent-module
behavior. This change is confined to iPhone AVFoundation setup and iPhone help
content. No capture-output format, default, storage limit, network gate, bundle
schema or speed-limit reference policy is changed.

## Validation

- Isolated iPhone simulator build passed.
- Final focused suite: **32 unit tests passed**, comprising five startup/crash
  regressions, five autofocus regressions, 14 control-availability tests and eight
  existing recorder-state/module/finalization regressions.
- All four Localizable.strings tables parse, have identical sets of 479 keys,
  contain no duplicate keys and preserve format-placeholder parity.
- Four-language UI verification passed: Back labels are correct and the native
  recording reference opens and closes in German, English, French and Dutch.
- Seven existing recorder-state/module regressions passed in the same final UI run.
- Before the recursion fix, both new bounded crash regressions failed as expected.
- After the targeted fix, both bounded crash regressions pass: initial
  recording notification no longer recurses and unchanged TSR updates are silent.
- Physical camera smoke test passed on development build 10054: three real
  recording cycles completed without the original startup crash; saved 4K clips
  decode fully and GPS fixes continue during each recording. Sustained driving
  with many newly captured images remains a separate real-world scenario.

Evidence: `/private/tmp/youspeed-testflight-fix-20261019/regression-3.xcresult`,
`final-validation.xcresult`, `recursion-before.xcresult` and
`crash-fix-regressions.xcresult`.

Recording-control asset SHA-256:
`18c257ef3004eda183ecf83ade0c5afae5c913e82f00fb3f9055862aceac6d2b`.
No build upload, release, merge or device deployment was performed.

## References

- [Apple: available video codecs](https://developer.apple.com/documentation/avfoundation/avcapturemoviefileoutput/availablevideocodectypes)
- [Apple: TestFlight screenshot feedback](https://developer.apple.com/documentation/appstoreconnectapi/get-v1-apps-_id_-betafeedbackscreenshotsubmissions)
- [Apple: TestFlight crash feedback](https://developer.apple.com/documentation/appstoreconnectapi/beta-feedback-crash-submissions)
