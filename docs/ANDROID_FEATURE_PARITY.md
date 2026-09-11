# Android / iPhone feature parity

Implementation checkpoint: 11 September 2026. Reference: the current iPhone
working tree, including its existing local photo-deletion changes. This change
modifies Android only; it does not change shared schemas or the iPhone behavior.

## Implementation coverage

| Area | Android behavior | Regression evidence |
| --- | --- | --- |
| Default road matching | M7 tunnel entry/exit/hold and surface admission; linked low-speed junction release; polyline distances | `MatcherParityInstrumentedTest`, copied iPhone SQL fixtures |
| Diagnostic matching profiles | M10 node heading, M11 particle transitions, M12 rolling ten-fix graph/Viterbi | `MatcherParityInstrumentedTest` |
| Bundle updates | Raw/zlib SQL delta chains, recent-base eligibility, checksums, staged atomic activation and full fallback; all preferred-country endpoints | `BundleDeltaTests`, `BundleDeltaInstrumentedTest` |
| Recognition activation | Finite speed >= 1 km/h, coherent context/generation, foreground/session gating, optional independent recognition | `TrafficSignRecognitionOrchestratorTests`, `TrafficSignPassageTests`, `ConsumerLifecycleParityTests` |
| Recognition runtime | iPhone speed bands, 1.5-second candidate burst, thermal caps, three consecutive failures, visible unavailable state | `TrafficSignFramePolicyTests`, `TrafficSignRecognitionOrchestratorTests` |
| Recorder workspace | Elapsed timer, preview show/hide, independent video and TSR controls, photos continue with video off; finalization barrier on restart | `ConsumerLifecycleParityTests`, `DriveRecorderInstrumentedTest`; on-road and thermal validation remain necessary |
| Feedback | Sound default, spoken speed or silent; per-track suppression; driving-ban haptic even with speech off | `ConsumerLifecycleParityTests`; hardware audio/haptic validation remains necessary |
| Capture defaults | Enabled photo preference, distance mode, 25 m, 5 s, 1 GB quota; live/favorite/accepted items protected | `PanoramaxCaptureTests`, `PanoramaxParityTests` |
| Capture outputs | GPS/time/altitude/course EXIF, sign JSON UserComment and sidecar, verified hash after EXIF write, upright dimensions/thumbnails | `PanoramaxMetadataInstrumentedTest` |
| Sign/photo association | Project confirmations received during capture; nearest existing photo within five seconds; consume attached drafts | `PanoramaxMetadataInstrumentedTest` |
| Capture recovery | Request/session IDs reject stale callbacks, errors release capture gate, restart seals interrupted batches, corruption reported and thumbnails repaired | `PanoramaxParityTests`, `PanoramaxMetadataInstrumentedTest`; physical capture retry remains necessary |
| Photo review | Available after recorder stops regardless of capture preference; originals, favorites, bulk selection/deletion, upload approval | `ConsumerLifecycleParityTests`, `PanoramaxParityTests`, UI smoke coverage |
| Panoramax account | Claim in browser, explicit validate/disconnect, AES-GCM credential storage with Android Keystore | `PanoramaxParityTests`, `PanoramaxMetadataInstrumentedTest` |
| Panoramax uploads | Explicit jobs, progress, cancel/resume, durable acceptance, uncertainty quarantine, processing completion before optional local cleanup | `PanoramaxParityTests` with local mock transport |
| Movie library | Full list, play/share/bulk delete; 5 GB per file and 10 GB retention; failed files removed | `DriveRecorderInstrumentedTest`, native runtime/controller inspection; physical movie validation remains necessary |
| Voice correction | Four seconds; no spoken startup prompt; partial transcripts display only, completed transcripts commit | Existing speech tests and `VoskNativeRuntimeInstrumentedTest`; actual utterance validation remains necessary |
| Country state | Duplicate/older valid GPS fixes preserve current result and original deadline; invalid/expired fixes suppress penalties | `CountryPenaltyTests` |
| Settings and status | Four-language controls; first-location failure state; no ordinary Android-only manifest/sync controls | UI smoke coverage and production path inspection |

## Verification boundary

Verified results:

- 223 Android JVM tests passed, zero failures.
- Full Android emulator suite: 59 passed, six optional tests skipped, zero failures.
- Final focused emulator check: recorder module/lifecycle regression and native
  Vosk test both passed after the camera/voice fixes.
- 25 shared TSR schema/catalog tests passed.
- Final UI/camera rerun: five tests passed after fitting the recorder workspace.
- Debug APK, optimized release APK, and debug lint completed successfully
  (zero lint errors; 79 warnings remain).
- Earlier iPhone simulator reference run: 257 passed, 22 skipped; the live bundle
  download test was excluded. iPhone source was not changed by this work.
- Manual emulator check confirmed movie/still capture, post-recording review,
  favorite selection, full-size photo viewing, readable recorder controls, and
  preview show/hide without stopping the movie. The subsequent regression
  test verified the corrected four-output camera graph with live module changes.

Logs: `/private/tmp/youspeed-parity-final.log` (full emulator suite and initial
translation-lint failures), `/private/tmp/youspeed-parity-camera-final.log`
(successful builds, unit tests, lint and recorder/voice checks),
`/private/tmp/youspeed-parity-layout-final.log` (final responsive layout checks), and native
XML snapshots `/private/tmp/youspeed-parity-native-full.xml` and
`/private/tmp/youspeed-parity-native-camera.xml`.

Emulator checks exercise Android SQLite, EXIF, Keystore, packaged speech and
vision libraries, and basic UI navigation. They cannot establish physical-camera
support, thermal behavior, actual speech/haptics, or real-service upload behavior.
The initial implementation was verified on an emulator. The later authorized
physical-device deployment is recorded below. No real account connection or
external Panoramax upload was performed.

Platform implementations differ intentionally: CameraX/LiteRT/Vosk/Android
Keystore provide the Android equivalents of AVFoundation/Core ML/Apple Speech/
Keychain. Camera hardware determines which simultaneous use cases are supported.
The runtime reserves all four outputs at the initial binding so a live module toggle
does not rebuild an active movie graph. It reports a failed binding; other device models should exercise preview,
movie, stills, and recognition together before release.

## Reproduce

```sh
cd android
./gradlew --offline :app:testDebugUnitTest :app:assembleDebug :app:assembleRelease :app:lintDebug
ANDROID_SERIAL=emulator-5554 ./gradlew --offline :app:connectedDebugAndroidTest
```

Use an emulator serial explicitly. The live bundle bootstrap and optional private
trace tests skip unless their input/opt-in arguments are supplied. Upload unit
tests use local transport doubles and never send images to Panoramax.

## Attached-device deployment — 11 September 2026

Updated the existing `de.youspeed.android.debug` installation on a Moto g86 5G
(Android 16, arm64-v8a) in place, retaining its application data. The deployed
build is version `1.1-debug`, version code `10006`.

All 20 selected instrumented tests passed on the physical phone: live movie,
recognition and photo module transitions; M7/M10/M11/M12 matching; delta bundle
activation; JPEG GPS/sign metadata and orientation; Keystore credential storage;
and packaged LiteRT/Vosk native runtimes. Tests used isolated data or restored
preferences and removed their newly created media. The auxiliary test package
was removed after validation; the updated app was launched for use.

Deployed APK SHA-256:
`40cc23e54dad783a75989559c85beb9810cbf6cc888ce4a1c2e5fc14ae5676d5`.

Device-test log: `/private/tmp/youspeed-moto-parity-tests.log`.
On-road recognition accuracy, thermal endurance, and real Panoramax uploads
remain outside this deployment smoke test.
