# Driving photo button — 2026-10-10

## Requested behavior

Both native dashboards expose a single manual photo button at the bottom right
while the current speed is **strictly greater than 1 km/h**. The threshold uses
the apps' existing internal km/h convention, independent of displayed units.
At exactly 1 km/h, below it, or for a non-finite speed, the button is hidden.

The existing ordinary-control safety policy remains unchanged: those controls
hide at 4 km/h. Between 1 and 4 km/h, their row reserves vertical room above the
new shutter, so touch targets do not overlap. Portrait and both landscape mounts
use the dashboard safe area. The camera icon uses the existing circular control
style, with a localized accessibility label and capture feedback.

## Capture and privacy

- The manual action uses the existing native still-camera and local Panoramax
  photo queue, JPEG metadata, thumbnail and review flow
- A tap requests one photo rather than starting or stopping dashcam video
- Manual capture is independent of the automatic-photo setting, distance/time
  cadence and recognized-sign-only filter; those automatic behaviors retain
  their existing gates and defaults
- The still output is prepared before starting the camera session; adding a
  shutter must not rebuild an active dashcam session
- With all other camera features off, manual-only camera demand ends when speed
  drops to 1 km/h or below, after any accepted still finishes; its local batch
  becomes available for review
- The control remains disabled until the camera, local storage and a usable
  recent location are ready, and while a photo is already in flight
- Repeated taps cannot queue a burst; session changes and stale completions
  retain the existing capture ownership checks
- Missing camera permission does not open a permission dialog while moving
- Photos remain local until the existing review and explicit upload flow is
  used; the shutter does not start an upload or change upload preferences

## Review and validation

This change is based on
`codex/youspeed-v1.4-app-foundations@d9f0ab0e878a3881f2e7d39993f53b6c96e8a577`,
which includes the current app and test-isolation fixes. It does not incorporate
the unrelated crop-review PR or lane-training changes.

Validation covers the strict speed boundary, disabled/readiness conditions,
manual-versus-automatic capture policy, repeated requests, and bottom-right
placement in portrait and both landscape mounts. The change adds seven Android
unit tests, five isolated Android instrumented tests, six iPhone unit tests and
two simulator UI tests. The existing real CameraX recorder test also exercises
manual capture with automatic photos off while the movie remains active.
Native Android CI uses an isolated emulator installation; iPhone CI uses the
isolated simulator host. The PR's exact-head checks record the executed native
build/test results. Request-injection tests validate admission and persistence;
they do not independently validate camera hardware.

Local source checks:

```sh
python3 scripts/speed_limit_reference/check.py
python3 scripts/check_mobile_rules.py
git diff --check
```

The implementation environment is Linux with no Xcode or Android SDK, so local
source checks are not a claim of native build or camera validation. GitHub CI
provides the native runners. No physical phone was installed, tested, reset or
otherwise accessed for this change. Simulator/emulator evidence does not qualify
real-device camera output or driving safety. No merge or deployment is included.
