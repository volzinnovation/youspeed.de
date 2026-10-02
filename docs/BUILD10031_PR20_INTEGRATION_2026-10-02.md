# Build 10031: spoken secondary signs on the Data Manager baseline

## Source and behavior

Data Manager build 10030 was committed and pushed to main as `fdb0de6`.
PR #20 (`ddd9635e86af6e3427a13b712e537117a7a1dc4c`) was then applied
without conflicts to that baseline. Both apps now offer the opt-in combined
speed/secondary-sign speech mode, retaining existing stored modes and defaults.
Reviewed speech metadata covers German, English, French and Dutch; unavailable
voices and explicitly ambiguous classes remain silent. See
`TSR_SPOKEN_SIGN_FEEDBACK.md` for admission, repetition and priority rules.

The Data Manager remains first in Settings. Calibration, lane controls, queued
downloads and deletion/lookup guards remain intact. The shared speed policy and
its Swift/Kotlin interpreters have no changes. The preserved lane-detector fix
allows iPhone builds to compile, resolving the baseline compile blocker noted
in PR #20. Both platforms use version 1.3, build 10031.

## Verification

| Check | Result |
| --- | --- |
| Shared speech catalog and Data Manager contracts | 15 passed |
| Speed-reference contract | 39 scenarios / 171 steps passed |
| Mobile rule packaging | 12 country rules passed |
| Android unit suite | 612 passed, no skips/failures |
| Android app and instrumentation builds | Passed |
| Signed iPhone device build | Passed |
| iPhone simulator unit target | 593 executed, 26 skips, no failures |
| iPhone simulator Data Manager UI | Passed |
| iPhone simulator combined speech Settings UI | Passed |
| Android emulator Data Manager/navigation/rotation UI | 2 passed |
| Android emulator combined speech Settings UI | Passed |
| Physical-device final UI/launch validation | Pending unlock |

The live-release map download test was excluded from iPhone unit testing.
Initial added UI checks required harness corrections: iPhone recognition must
be enabled to open its feedback picker, switch taps must target the control,
and Android uses Compose scrolling instead of gesture flings that overshoot
the relevant controls. Final simulator runs pass. The speech UI checks capture
screenshots without selecting a new feedback mode. The iPhone check restores
the previous recognition setting when it enabled it.

## Device installation and remaining validation

Build 10031 has been installed as an update on the attached iPhone 14 Pro and
Moto g86 5G, retaining their app data. Both phones subsequently locked. iOS
blocked its UI-test launch, and Android's lock screen prevented its test
activity from reaching the foreground. These attempts do not establish a
physical-device regression. Unlocking both phones is required to finish the
new Settings flow, Data Manager regression checks and normal foreground launch.

Pronunciation, Bluetooth/car audio routing and live-driving speech interruption
behavior have not been verified on a drive. Unit tests exercise freshness,
repeat suppression, busy speech, movement, session resets and priority guards.

Evidence is retained under `/tmp/youspeed-pr20-20261002/`:
`iphone-sim.xcresult`, `iphone-speech-ui-final.xcresult`,
`android-emulator-5554-ui.log`, `android-emulator-speech-final.log`,
`android-build.log`, `shared.log`, `policy.log`, `mobile-rules.log`,
`iphone-device-build.log`, `iphone-install.log` and device-blocking logs.
