# First-run walkthrough

The iPhone and Android apps use the same five-step setup flow. Loading local
services is separate from completing setup; the old welcome screen and its
Germany-only coverage illustration are replaced by actionable setup.

1. **Map:** ask to use the current location to suggest a containing region, or
   let the user choose a map manually. Downloading is explicit. Show progress
   and retry failures. A validated, active downloaded map is required before
   continuing; seed data does not qualify. Cellular downloads remain available.
2. **Driving settings:** explain precise foreground location, provide permission
   and system-settings recovery, and expose voice alerts and their threshold.
   A location fix is not required to finish, but precise location permission is.
3. **Dashcam:** explain starting and stopping the recorder, local videos, and
   switching video off independently of the other camera features.
4. **Speed-limit sources:** distinguish downloaded map limits, personal spoken
   corrections, and camera recognition. Camera recognition can run without
   saving video. Spoken corrections currently use German speech on-device;
   camera and microphone permissions are requested when their features are used.
5. **Panoramax:** surface the existing photo-capture preference. Explain local
   geotagged pictures, review and selection after recording stops, account
   connection, and an explicit upload. Setup never records or uploads media.

## State and existing users

Both clients persist `youspeed.onboarding.completed` and
`youspeed.onboarding.step`. An unfinished walkthrough resumes. Missing map data
returns the flow to the map step, and completion checks the map and location
requirements again.

At the first startup with the new code, users who already have a usable map
are migrated as complete. New users are persisted as incomplete before they
can download, so a first download does not skip the remaining explanations.
Map age no longer determines whether to display a welcome screen. Settings
provides a way to repeat setup while the recorder is stopped.

The selected map also persists across restarts. Manually choosing a region
cancels a pending location suggestion so that a delayed fix cannot replace it.

Location discovery only recommends a region. It neither starts a download nor
starts a driving/camera session. Existing feature defaults are retained; changes
made in setup use the same settings as the driving interface.

## Screenshot examples

Each platform includes five screenshots captured from its native app with
synthetic simulator media: the normal map limit, the camera limit with its eye
marker, the video library, photo review, and Panoramax account connection.
Examples appear before detailed instructions and open with pinch zoom and pan.

Video instructions reflect the actual platform controls. Android provides Play
and Share; iPhone provides selection, sharing, and deletion. Sharing lets users
open or upload a video through another app. Panoramax uploads are for selected
photos. The disconnected-account example does not imply an upload occurred.

Text and screenshot captions are localized in English, German, French, and
Dutch. Other Android locales use the documented English fallback for this flow.

## Validation

The platform policy tests cover migration, resumption, and required map/location
gates. Android's `OnboardingInstrumentedTest` exercises the real Compose screens
with isolated state: map selection, download/error gating, denied-location
recovery, optional controls, and navigation on every step. It does not download
maps, connect an account, or access existing user preferences or media.

Verified on 11 September 2026:

- Android: 229 JVM tests passed; debug, release, and test APKs built; lint has
  zero errors (102 warnings).
- Seven focused tests passed on the Pixel emulator and the attached Moto g86
  5G: walkthrough gates and controls, screenshot viewing, startup isolation,
  and live recorder module transitions. The recorder test restores its map
  fixture, settings, and media after running.
- iPhone: 263 simulator tests passed and 22 optional tests skipped. The live
  release-download test was excluded. Final build and native manual checks
  verified localized headings, region selection, displayed download size,
  and a disabled Continue action before map activation.

Logs are under `/private/tmp/youspeed-onboarding-*`; rendered screen checks
are in `/private/tmp/youspeed-onboarding-review/`. No real Panoramax account
connection or upload was performed during validation.
