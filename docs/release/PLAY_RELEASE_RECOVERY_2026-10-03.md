# Play release recovery — 3 October 2026

The signed Android **1.3 (10033)** bundle is attached and saved to production release 2. Play reports **zero blocking release errors and zero devices losing support**. Two advisory warnings remain: increased APK download size and missing native debug symbols in vendor libraries. The replacement targets API 36, addressing the target-SDK issue shown for the previous production build.

The original draft contained no bundle. The existing local Woladen signing configuration was found, and its public certificate exactly matched YouSpeed’s Play upload certificate before use. No key replacement, credential publication or upload-key reset occurred. After signing and uploading 10032, Play identified 116 devices excluded by the CAMERA permission’s implied rear-camera requirement. Android’s existing camera binding failure already reports UNAVAILABLE; iPhone likewise handles camera absence. Build 10033 explicitly declares camera, any-camera, autofocus and flash optional, preserving the non-camera app and the protected speed-reference policy. Play confirms all 116 devices remain supported. Official reference: https://developer.android.com/guide/topics/manifest/uses-feature-element

All nine Play listings have eight ordered localized phone screenshots, one localized feature graphic and the actual video URL. All nine release-note languages are saved. The updated German copy is retained, with its unsubstantiated “over 800” sign claim corrected to “hundreds.” The production release, Belgium availability change and listings are saved together as **16 changes awaiting submission**, with managed publishing enabled. Uploading and saving are not review submission.

The preview is actually published on Raphael Volz’s channel as **unlisted**: https://www.youtube.com/watch?v=89oEyuqHVMw . English timed captions and original media credits are saved; YouTube copyright checks report no problems. The user confirmed the upload terms at the upload dialog.

## Remaining release work

Play’s July Data safety declaration still stated no collection. A partial draft now records verified collection, HTTPS transmission and OAuth account creation. The form requires an actual account-and-data deletion URL before it can advance. Disconnect only revokes the token. The operator’s deletion process and additional server-data handling must be reconciled before final declarations and combined review submission; no fabricated deletion URL or false no-collection answer was submitted. See PANORAMAX_PRIVACY_READINESS_2026-10-02.md.

The signed APK is ready. A fresh adb inventory shows only emulator-5554; the previously attached Moto g86 is absent. No physical-device deployment is claimed for this turn. Reconnect the unlocked phone for deployment and Info-flow acceptance.

## Verification

Local release lint/build, APK certificate and JAR signature verification passed. The built APK reports version code 10033 and all four camera features as optional. All 220 store text/image checks pass. Artifact hashes and source commit are retained in BUILD_10033_ARTIFACTS_2026-10-03.json. The earlier signed CI run completed 619 release JVM tests and lint successfully; its two locale-sensitive tests were fixed and separately passed 35 tests under an English host locale. A replacement signed CI run is tracked separately; its outcome must be verified before claiming success.

Apple metadata work remains outside this recovery report. The previously uploaded iPhone build is 1.3 (10032); this Android compatibility-only replacement does not change it.
