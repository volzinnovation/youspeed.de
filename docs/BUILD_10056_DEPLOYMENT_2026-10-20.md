# Build 10056 — cleanup, commits and device deployment

The completed app work is committed on `codex/youspeed-v1.4-app-foundations`
and pushed to `origin`. The separate lecture work remains outside these commits.

| Commit | Scope |
| --- | --- |
| `2cab578` | Preserve directional OSM speed tags through map builds, deltas and source-verified repairs. |
| `c8b3bf7` | Fix delayed location startup, recording recursion and camera setup; align road context, controls and sign feedback; localize recording help. |
| `b9ff1a0` | Export mobile SGBlur detectors at 1024, use the fixed rightmost window, and generate native-resolution upload crops without resizing. Remove unused calibration crop mapping. |
| `8e21171` | Set both apps to build 10056. |

## Validation

- Signed iPhone device app and Android debug APK builds succeeded.
- iPhone simulator: 58 tests passed, zero failures. This includes startup,
  recorder configuration, controls, road geometry, calibration and real Core ML
  inference with native crop pixel checks.
- Android: 741 unit tests, zero failures/errors, one skipped test; both normal
  app and instrumentation APKs compiled successfully.
- Directional map pipeline/repair: 12 tests and two subtests passed. An initial
  run skipped six pipeline tests because optional dependencies were absent;
  rerunning with isolated temporary dependencies executed all twelve tests.
- Model-pack/schema checks: 45 tests passed. Additional earlier 1024 validation
  is documented in `MOBILE_TSR_WINDOW_2026-10-20.md`, including four Android
  emulator instrumentation tests and export parity measurements.
- `git diff --check` passed. The shared speed-limit-reference policy and both
  interpreters are byte-for-byte unchanged from `917de04`.

The source build commit is `8e21171b7b9e633ae23aa1ea6b7b496b82ff065e`.
Android APK SHA-256:
`77b4771864ec9341b131ceffdebbf9d83e86d03a8e85a2d7c6b854bd717b66a9`.

## Physical devices

**iPhone 14 Pro:** normal app `de.youspeed.SpeedConsumer` installed successfully.
Device readback confirms version **1.4 (10056)**. Installation preserved the
active `2026-10-19-directional-speeds` map manifest, still identifying database
SHA-256 `bcbf2a36396052fedfac8e4d2f69400c77f0315de8d1c299cfebe6cdb6a951c4`.
The install updated the existing app; no uninstall, media deletion or map
replacement was performed.

After the user unlocked and reconnected the phones, the physical recording UI
test passed on build 10056 at 16:01 CEST. It exercised three real start/stop/save
cycles, cold relaunch after the first cycle and background/foreground recovery
after the second. All three saved HEVC movies fully decoded at 3840 × 2160:

| Cycle | Duration | Decoded frames | Fresh GPS fixes during clip |
| --- | --- | --- | --- |
| 1 | 12.112 s | 363 | 12 |
| 2 | 12.067 s | 361 | 13 |
| 3 | 13.118 s | 393 | 14 |

All 11 preexisting movies retained their paths and sizes. The successful test's
two drive logs contain 53 fresh GPS samples, all matched with current bundle
authority, with median horizontal accuracy about 2.0 m. Each clip has fresh
matched fixes throughout its recording interval.

Five physical iPhone detector/crop tests passed in a separate `.TestHost` app:
actual CPU Core ML inference with 1024 inputs, orientation handling, portrait
padding, resolution-independent geometry and exact native crop pixel retention.
The near reference correctly classified 70 km/h at 0.89502. The distant portrait
reference classified 120 km/h at 0.44767, below the 0.70 confirmation threshold;
it is not a reliable positive at 1024. The original distant-positive assertion
failed on hardware. Its regression now requires the clear positive and rejects
a confirmed wrong distant class; production thresholds are unchanged. See
`MOBILE_TSR_WINDOW_2026-10-20.md` for this measured limitation.

Earlier recording attempts were interrupted by an unrelated Exchange account
reauthentication alert and the optional sign-contribution sheet. The UI harness
now cancels only the Exchange prompt, closes sign sharing without consent, and
retries a start tap if that sheet intercepted it. The successful run is retained
separately from those failed attempts. No account credentials were entered and
no contribution permission was granted. The normal app was relaunched after
the isolated detector checks.

**Android Moto g86 5G:** normal app `de.youspeed.android.debug`, version code
**10056**, installed successfully after USB reconnection. All six physical
instrumentation tests passed: four 1024 detector/native-crop checks, the camera
graph lifecycle/movie-finalization check and the real dashcam/photo integration
test. Recording, TSR continuity and still capture while Settings pauses matching
were exercised. The test verified 2,713 preexisting media files with unchanged
sizes, removed only its own test media and restored the original preferences.
The active map manifest and movie-path inventory match their pre-test snapshots.

The normal Android dashboard then received 12 fresh GPS samples: all matched
with current bundle authority and four signal bars, with median horizontal
accuracy about 2.3 m. These are real OS fixes after the recorder test ended;
that integration test separately uses labelled controller-only capture fixes.

Both phones retain the same directional-speed map selection. This is a
stationary hardware validation; a sustained drive with many new photos has not
been repeated on build 10056.

Local build and validation evidence uses the prefix
`/private/tmp/youspeed-10056-`, including build logs, simulator results, app
identity, iPhone installation/readback, map manifests, decoded clips, XCTest
results, Android instrumentation output and `device-validation.json`.
These private device records are kept outside Git.
