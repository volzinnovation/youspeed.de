# Android Google Play preparation — 2 October 2026

## Candidate and status

The candidate keeps the existing source version **1.3 (10031)** and application ID
`de.youspeed.android`. Its minimum OS remains Android 14 / API 34; its target and
compile SDK are Android 16 / API 36. No Play upload, publication, physical-device
installation, key creation, or version-number reservation was performed.

The user's comparison point is iPhone 1.0.1 (10003). Android's documented 1.0.1
baseline is a different build number: 10001, tagged `android-v1.0.1` at
`69bf9a8a5951578cc37c9f090ada2c0f50b980e3` (see `docs/fdroid/README.md`). Do not
assume that the two stores have matching historical version codes. Confirm the
highest Play version code across all tracks before signing the final candidate.
F-Droid's per-ABI APK numbers (`base * 10 + 1…4`) must not be substituted for the
normal AAB build number.

## Release preparation changes

- Upgrade AGP 8.5.2 to **8.9.2** and Gradle 8.7 to **8.11.1**, retaining Kotlin
  1.9.24 and the device-validated CameraX/LiteRT/Vosk runtime versions. Remove
  the obsolete SDK-warning suppression and pin the official Gradle distribution
  SHA-256. API 36 requires at least AGP 8.9.1 according to the
  [official compatibility table](https://developer.android.com/build/releases/about-agp).
- Correct the signed per-ABI APK script's stale default build number from 10016
  to 10031. Marketing version remains 1.3 on both platforms.
- Restrict screenshot launch extras and screenshot-related review-prompt bypass
  to Android debug builds. An external launch of the exported release activity
  must not substitute a simulated speed/location/reference state.
- Add the debug dashcam screenshot fixture equivalent to iPhone's existing
  fixture. It presents real recorder controls without starting the camera,
  writing a movie/photo, or uploading anything.
- Declare the already-used Camera2 infinity-focus API's experimental opt-in;
  this fixes release lint without changing camera behavior.
- Constrain the transitive AndroidX Fragment dependency to 1.8.2. CameraX
  camera-view and the existing Play review integration otherwise resolve 1.1.0,
  while Activity Result contracts require at least 1.3.0; release lint identified
  three invalid-version errors. This is a dependency compatibility correction.
- Reserve the portrait recorder strip above the bottom action row, matching
  iPhone `MainView`'s control reservation, and split the compact Panoramax label
  from its count/status so it fits. Recorder state transitions are unchanged.
- Omit the unconfigured native preview only in debug screenshot fixtures. The
  camera-free emulator fixture otherwise obscured neighboring Compose content
  after relayout; production PreviewView behavior is unchanged.
- Add missing Spanish/Italian Android strings while preserving existing
  translations. Other contributors completed the remaining locales.
- Add local `prepare-play-release.sh` and `audit-release-artifact.py` checks.
  The preparation command never installs, uploads, publishes, or provisions.

The current
[Play target SDK requirement](https://developer.android.com/google/play/requirements/target-sdk)
requires API 36 for phone-app submissions from 31 August 2026. The candidate's
manifest meets that target.

## Signing and identity gates

All four `YOUSPEED_ANDROID_RELEASE_*` signing variables were absent in this
session. The repository's documented local setup (`android/README.md` and
`android/app/build.gradle.kts`) supplies only these exported variables. The
other documented setup, `.github/workflows/build_signed_sideload_apks.yml`,
uses GitHub Actions secrets and a temporary runner keystore; it also publishes
a GitHub release and was not dispatched. No local keystore/configuration path
or recorded Play upload-certificate identity is documented, and no
repository-local `.jks`, `.keystore`, `signing.properties`, or `key.properties`
file was found. This does not establish that the existing key is unavailable
elsewhere. No upload keystore or key password was printed, searched for broadly,
created, or changed. Consequently the local AAB is **unsigned**, and is a
preparation artifact rather than an upload-ready binary.

Before the final signed build:

1. Confirm that this is the intended Play application and inspect the latest
   version code across production, open/closed testing, and internal testing.
2. Supply the existing matching upload key using the four environment variables
   in `android/app/build.gradle.kts`; keep its key material outside the repository.
3. Verify its certificate against Play Console's upload-key certificate. Keep
   Play App Signing's app-signing certificate separate from the upload certificate.
4. Build a signed AAB with the agreed version code; verify its JAR signature and
   record its SHA-256, mapping file, and source fingerprint before approval.

## Native 16 KB compatibility

The existing native runtime dependencies are CameraX **1.4.2**, LiteRT **1.4.2**
(CPU, GPU, and GPU API), Vosk **0.3.75**, and its resolved JNA **5.18.1**. Relevant
primary-source references are the
[CameraX release notes](https://developer.android.com/jetpack/androidx/releases/camera),
[LiteRT releases](https://github.com/google-ai-edge/LiteRT/releases), and
[Vosk Android build source](https://github.com/alphacep/vosk-api/blob/master/android/lib/build.gradle).
Provider version/provenance claims do not replace inspection of the packaged bytes.

A narrow upgrade feasibility check inspected already-cached provider AARs.
CameraX 1.6.2 fixes the arm64 image-processing `RELRO` finding but still leaves
both 64-bit surface libraries misaligned. LiteRT 2.2.0 changes the native/API
family and still has a misaligned arm64 `libLiteRt.so`; it does not close the
gate. Vosk's
[published Maven metadata](https://repo.maven.apache.org/maven2/com/alphacephei/vosk-android/maven-metadata.xml)
lists 0.3.75 as its latest release when checked on 2 October 2026. These checks
do not justify an unvalidated camera/ML migration for this submission. Obtain
compatible provider builds, or rebuild the applicable dependencies with a modern
NDK and retest the existing flows; do not patch ELF protection headers in place.

The initial local AAB inspection found:

- Bundle configuration requests `PAGE_ALIGNMENT_16K`.
- All **12 packaged 64-bit libraries** have 16 KB-aligned ELF `LOAD` segments.
- **Nine** 64-bit libraries fail the current Android guidance's additional
  `GNU_RELRO` end-alignment check. A packaging/toolchain upgrade cannot rebuild
  these dependency-supplied ELF binaries.
- A bundletool-generated arm64 native split passes `zipalign -c -P 16 4`.
- The running emulator reports **4096** bytes per page; no installed 16 KB image
  was available. No 16 KB runtime execution was performed.

| ABI | Libraries with a nonzero `(RELRO VirtAddr + MemSiz) % 16384` |
| --- | --- |
| arm64-v8a | `libimage_processing_util_jni.so`, `libsurface_util_jni.so`, `libtensorflowlite_gpu_jni.so`, `libtensorflowlite_jni.so`, `libvosk.so` |
| x86_64 | `libsurface_util_jni.so`, `libtensorflowlite_gpu_jni.so`, `libtensorflowlite_jni.so`, `libvosk.so` |

JNA's 64-bit native bridge passes both static checks. The 32-bit Vosk libraries
use 4 KB `LOAD` alignment, which is recorded but is outside the 64-bit Play
requirement. No native libraries, GPU path, supported ABI, or speech feature were
removed to mask this finding.

**Release gate:** obtain/rebuild compatible native dependencies as necessary,
repeat both static checks, and exercise camera preview/recording, speech models,
and LiteRT CPU/GPU fallback on a runtime reporting `PAGE_SIZE=16384`. Do not claim
full 16 KB compatibility from ZIP or `LOAD` alignment alone. The
[current official page](https://developer.android.com/guide/practices/page-sizes)
requires support for 64-bit devices and currently states that incompatible app
updates cannot be released from **1 February 2027**. Older announcements had a
different deadline; confirm this app's actual Console warning before submission.

## Size and artifacts

The initial unsigned AAB was **446,679,452 bytes (426.0 MiB)**. Local bundletool
1.18.3 validation passed. For a sample arm64 / API 36 / German / density 480
device, bundletool estimated a download of **420,403,717 bytes (400.9 MiB)**.

The
[current Play size policy](https://support.google.com/googleplay/android-developer/answer/9859372?hl=en)
sets the base-module compressed download limit to 500 MB and displays a
nonblocking mobile-data warning above 200 MB. AAB ZIP size and universal APK size
are different measurements from a Play device-specific download. The sample
estimate is below 500 MB, but the final signed bundle and Play's calculation
still need confirmation. The largest assets are bundled country classifiers and
four offline speech models; their removal/download behavior would change product
behavior and was not introduced for release preparation.

## Verification and screenshots

Initial source/toolchain baseline: **616 debug and 616 release JVM tests passed**,
zero failures/errors/skips, and optimized release APK/AAB generation succeeded.
Release lint initially reported 101 errors (98 missing translation keys and three
Camera2 opt-in annotations); these were concrete preparation blockers. Final
candidate verification and artifact hashes are recorded below.

The updated screenshot script targets only an explicitly named emulator,
restores animation scales, per-app locale, and the existing orientation
preferences on exit, stages/validates images
before replacing known old gallery files, and produces eight phone shots per
locale. These are synthetic debug scenarios rendered by the app's real UI,
not claims of live model inference or a real recording.

| Shot | Fixture |
| --- | --- |
| 01 safe speed | Germany, 47 / 50 km/h |
| 02 dashcam | Real recorder controls in supported landscape orientation with the debug-only recording fixture |
| 03 camera recognition | Camera-sourced 30 km/h limit and its eye indicator |
| 04 traffic signs | Shared `give_way` pictogram, not generated artwork |
| 05 France | Urban 53 / 50: EUR 135; no French licence points |
| 06 Switzerland | Urban 61 / 50: CHF 250; no points |
| 07 Belgium | Urban 55 / 50: EUR 58; additional EUR 10.67 fee in details |
| 08 Netherlands | Urban 62 / 50: fine possible; no fixed tariff is implemented |

The fine examples use the app's actual bundled rules and country-selected GPS
fixtures. In particular, the Dutch image must not invent a numeric fine. Broader
road-scene accuracy, physical-camera compatibility, audio/haptics, thermal
endurance, upgrade/data-retention behavior, and real-service upload behavior
remain release validation gates. Earlier physical-device evidence is documented
in `docs/ANDROID_FEATURE_PARITY.md`; it does not establish current source or
16 KB runtime compatibility. Portrait screenshot inspection revealed an actual
recorder-strip/bottom-toolbar overlap; it was corrected in the production layout
and visually checked before/after. Both supported orientations were then checked.
Physical live PreviewView and movie-recording acceptance remain required:
the emulator fixtures cannot validate the real native camera surface.

The resource inventory now covers all default translatable XML keys in the nine
configured locales. This is key coverage, not full product-language acceptance:
some existing recorder/detail UI uses the four-language `parityText` helper and
falls back to English outside German, English, French, and Dutch. Review those
surfaces with native speakers before claiming complete additional-language UI.

## Final local evidence

- Final unsigned AAB: `android/app/build/play-release/YouSpeed-release.aab`,
  **446,636,511 bytes (426.0 MiB)**.
- AAB SHA-256:
  `4faa9237ac7bc98d81966ccd91dedd3b0899810db03c8aeb1bc3a90140f3c3c6`.
- Compiled-source/configuration fingerprint, over **1,694 recorded inputs**:
  `91f7e70c5b1a5fe93e98a9892f9ef87df4381e4e7bb8a3923c2521dcf724192b`.
  `source-inputs.json` records paths, byte counts and hashes against base commit
  `9013c1371f247db80ccdba1285d1a50060bc618e`. All recorded inputs still matched
  after build and captures; unrelated concurrent work was preserved.
- Final debug and release JVM suites: **615 tests each**, zero failures, errors
  or skips. Release build, optimized APK/AAB and release lint succeed;
  lint reports **0 errors / 172 warnings**. No lint error was suppressed.
- Bundletool 1.18.3 validates the final AAB. The final generated arm64 split
  passes `zipalign -c -P 16 4`; its sample device download estimate is
  **420,337,306 bytes (400.9 MiB)**. Generated split APKs use debug signing only
  for local analysis and were not installed or uploaded.
- The final native audit still reports all 12 64-bit `LOAD` checks passing,
  nine `RELRO` failures, and no 16 KB runtime validation. `--require-16k`
  correctly exits with status 2 for this outstanding gate.
- Release `MainActivity` bytecode contains none of the screenshot launch-extra
  or screenshot-environment-variable names, confirming compile-time removal
  of the external fixture entry points.
- **72 Play phone screenshots** (eight in each of nine locales) and Fastlane
  mirrors are complete. Portrait shots are 1080×1920; supported landscape
  dashcam shots are 1920×1080. The final French compact recording and photo
  statuses wrap fully. The pre-capture preference digest, locale and all three
  animation settings match exactly after capture.

`candidate.json`, `artifact-audit.json`, `source-inputs.json`,
`lint-results-release.txt`, `sample-arm64-download-size.csv`, and `mapping.txt`
are saved alongside the local AAB under ignored `android/app/build/play-release/`.
Large build/tool logs and the portrait before/after evidence are outside tracked
source under `/private/tmp/youspeed-android-store-2026-10-02/` and
`/private/tmp/youspeed-android-final-*-2026-10-02.log`.

## Reproduce locally

```sh
cd android
./scripts/prepare-play-release.sh --unsigned

# Once the matching existing upload-key environment is provided:
./scripts/prepare-play-release.sh

# No physical device is accepted by the screenshot command:
ADB="$HOME/Library/Android/sdk/platform-tools/adb" \
  ANDROID_SERIAL=emulator-5554 ./scripts/recreate_store_screenshots.sh

# Fail explicitly on the remaining 64-bit static native compatibility findings:
python3 scripts/audit-release-artifact.py app/build/outputs/bundle/release/app-release.aab \
  --output app/build/play-release/artifact-audit.json --require-16k
```

Keep build logs and large generated artifacts outside tracked source, or under
ignored `android/**/build/`. Submission, track selection, rollout, publication,
and physical-device deployment require their separate explicit approval.
