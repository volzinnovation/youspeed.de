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

## Original branch review and validation

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


## Restoration on the collection branch — 16 October 2026

The manual shutter implementation was on the separate
[`codex/driving-photo-button-2026-10-10` / PR #30](https://github.com/volzinnovation/youspeed.de/pull/30)
branch (`13820f3`, with test follow-ups through `692573d`). It was absent from
collection foundation commit `45fe404`, used for installed build 10046. The
missing shutter was therefore a branch integration gap; it was independent of
private crop-upload delivery.

The feature is restored on the collection branch,
preserving daily-interest startup/activation, raw class IDs and the iPhone
batch-readability repair. Android permission requests now match iPhone's
stationary-only rule. No new permission dialog is allowed while moving, and
ordinary dashboard controls retain their existing safety policy. The shared
speed-reference policy is unchanged.

The sharing explanation on both clients now distinguishes independent
sightings, daily-selected private crops and always-eligible negative examples.
Manual Panoramax photos retain their separate local review/upload flow.

A read-only audit of the installed build-10046 phones reconciled all 1,966
sightings / 3,097 crops on iPhone and 926 sightings / 1,482 crops on Android to
server records, with zero missing records or pending crop bytes. All 1,106
ordinary selected iPhone crops match their historical exact plan selectors;
29 iPhone and seven Android bad-family crops carry `always`. Android has no
new captured signs after 14 October, so its ordinary numeric active-drive
acceptance remains pending. Local queues, logs and identity-level evidence
are retained privately under `docs/collection-evidence/` and `.codex-tmp/`.

The isolated validation snapshot and local device candidates contain foundation
`45fe404` plus the Photo restoration and
crop-selection explanations; concurrent supplementary-OCR work is excluded from
those candidates.

### Completed local validation

| Check | Result |
| --- | --- |
| iPhone simulator Photo tests | Seven unit and two UI tests passed |
| Android focused collection/Photo tests | 27 passed; one optional private replay skipped |
| Android stationary-permission policy retest | Six passed |
| Android Photo UI tests | Five distinct cases passed, across the initial four passes and one focused retest |
| Shared reference/rules | 39 scenarios / 171 steps and 12 country rules passed; locked policy unchanged |
| Device candidates | Both version 1.4 / build 10047 candidates built; Android APK and iPhone development signatures verified |

The iPhone injected-camera fixture now ignores hardware-failure notifications
from its synthetic, unstarted capture session only while the DEBUG test capture
hook is installed. A regression test covers both notifications; real camera
readiness and failure handling remain active. Android's fast-failure retry test
now uses its existing injected clock to test the 500 ms boundary deterministically,
rather than assuming Compose synchronization finishes before the cooldown ends.
Neither test repair relaxes production admission gates.

Private receipts, logs and candidate hashes are retained under
`.codex-tmp/photo-button-restore-20261016/`. Simulator screenshots cover portrait
and both landscape mounts. The disposable Android emulator was stopped after
validation. These tests do not qualify physical camera output or moving-device
use.

### Installed builds refreshed during the audit

The upload reconciliation above was performed on build 10046 at approximately
09:01 CEST. A separate, owner-authorized supplementary-OCR deployment subsequently
installed version 1.4 / build 10047 on both phones. A read-only refresh at 09:19
CEST confirmed those versions; no Photo-only candidate was installed by this
audit.

The installed Android base APK exactly matches the root build artifact and
contains the compiled Photo policy, button, capture handlers and localized
messages. The iPhone deployment receipt identifies the Release artifact whose
binary contains `dashboard.photoButton`, the manual capture handlers and local
review hint. Thus both current builds include the Photo restoration alongside
OCR. The physical moving/camera Photo flow has not been exercised, and the earlier
drive reconciliation does not constitute a build-10047 road test. The iPhone's
existing saved-log decision prompt still needs to be passed before its dashboard
can be used.
