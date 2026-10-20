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

Launch was denied by iOS because the phone was locked. A final check at
15:37 CEST still reported `passcodeRequired: true`. Location and real-camera
recording on build 10056 remain unverified until the user unlocks the phone.
The signed physical recording UI test runner is built and ready; its test was
not run while the phone was locked. Earlier physical build-10055 results in
`IPHONE_LOCATION_STARTUP_2026-10-19.md` do not establish build-10056 success.

**Android:** normal app `de.youspeed.android.debug`, version code **10056**, is
built. ADB returned no attached devices, and installation reported device not
found. Installation and physical parity checks remain pending USB connection.

Local build and validation evidence uses the prefix
`/private/tmp/youspeed-10056-`, including build logs, simulator results, app
identity, iPhone installation/readback, map manifest and connection status.
These private device records are kept outside Git.
