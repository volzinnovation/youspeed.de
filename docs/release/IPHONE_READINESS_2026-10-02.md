# iPhone App Store preparation — 2 October 2026

## Prepared version and provenance

- Marketing version: **1.3**; build: **10031**. Neither was changed during release preparation.
- Product/scheme: `SpeedConsumer`; bundle identifier: `de.youspeed.SpeedConsumer`.
- Minimum iOS: **17.0**; device family: **iPhone only**; packaged languages: German, English, French and Dutch.
- Starting HEAD: `71872dbc24cf17f400913a6107b3bce6db374eea` (`Integrate PR 20 secondary sign speech into both mobile apps`).
- The release preparation used the shared working tree, including concurrent native review-prompt work. Source fingerprints are retained beside the build evidence; this is a local preparation artifact, not an immutable committed submission candidate.

The user supplied TestFlight version 1.0.1 (10003). Git history does not prove the exact source of that upload: commit `01153756c52fe9d094d53d14e0f493e08707fc84` first sets build 10003 but also sets marketing version 1.1. Its parent, `6a55f564373b0059e60e246836bc3cfc192643db`, is version 1.0.1 (10002). The store record and any build-time override must establish the uploaded baseline before claiming an exact commit comparison.

## Toolchain and local distribution artifact

The installed toolchain is **Xcode 26.6, build 17F113**, with **iPhoneOS SDK 26.5**. Existing Apple Development and Apple Distribution identities for team `F4CT29PZS5` were available. No certificate, profile or provisioning registration was created or changed.

Final local output paths:

- Archive: `/private/tmp/youspeed-appstore-readiness-2026-10-02-iphone/SpeedConsumer-1.3-10031-ready.xcarchive`
- Distribution IPA: `/private/tmp/youspeed-appstore-readiness-2026-10-02-iphone/export-1.3-10031-ready/SpeedConsumer.ipa`
- Archive/export log: `/private/tmp/youspeed-appstore-readiness-2026-10-02-iphone/archive-export-ready.log`
- Source fingerprint: `/private/tmp/youspeed-appstore-readiness-2026-10-02-iphone/source-fingerprint-ready-start.json`

**The final archive and App Store export succeeded.** The IPA is 248,007,491 bytes; SHA-256: `02f91ad081b5c14da0bc316246b3b58bab5848ec0050627adfff4c4ca36d0bbb`. Its profile is `iOS Team Store Provisioning Profile: de.youspeed.SpeedConsumer`, expires 12 July 2027, and has `get-task-allow=false`, `beta-reports-active=true` and no provisioned-device list. The packaged privacy manifest matches the source byte for byte. The archive signature passed macOS strict verification, and the existing script verified both products contain no release credential keys.

`artifact-verification.json` records the checks. Source hashes were unchanged between `source-fingerprint-ready-start.json` and `source-fingerprint-ready-end.json`. Earlier successful artifacts without the final screenshot-fixture correction remain preserved in the same evidence directory and are superseded.

## Tests and practical limits

| Check | Result | Evidence |
| --- | --- | --- |
| Full unoptimized Debug unit/parity suite, iPhone 17e simulator / iOS 26.5 | 596 tests, 26 skipped, 4 assertion failures in one lane pipeline test | `unit-tests.log`, `SpeedConsumer-unit-tests.xcresult` |
| Isolated unoptimized lane pipeline retry | 1 test, 2 assertion failures, 1.652 s | `lane-retry.log`, `SpeedConsumer-lane-retry.xcresult` |
| Same lane pipeline with production Swift optimization (`-O`), retaining Debug test hooks | **1 test passed**, 0.248 s | `optimized-lane-test.log`, `SpeedConsumer-optimized-lane-test.xcresult` |
| Full optimized unit/parity suite with Debug test hooks | **597 tests, 26 skipped, 0 failures**, 96.316 s | `optimized-unit-tests.log`, `SpeedConsumer-optimized-unit-tests.xcresult` |
| Updated native review-request eligibility, cooldown and stationary gating | **3 tests passed** | `native-review-tests.log`, `SpeedConsumer-native-review-tests.xcresult` |
| Simulator build with corrected screenshot fixtures | **Passed** | `screenshot-build.log` |
| Privacy manifest plist structure | **Passed** | `plutil -lint iphone/SpeedConsumerApp/PrivacyInfo.xcprivacy` |

All named test evidence is under `/private/tmp/youspeed-appstore-readiness-2026-10-02-iphone/`.

The failing unoptimized test is `LaneDetectionRuntimeTests.testRealFramePipelineRetainsTrackerBetweenJobsAndClearsGeometry`. It expects fresh lane geometry while the unoptimized detector exceeds the overlay freshness window on this simulator. The optimized test retains and clears geometry correctly within 0.248 s, and the full optimized suite subsequently passed. No production lifetime window, lane behavior, shared policy or interpreter was changed to satisfy the test. The original unoptimized Debug failure remains part of the evidence.

A direct Release-configuration test build is incompatible with the existing test target because many test helpers are compiled only under `#if DEBUG`; `ENABLE_TESTABILITY=YES` alone does not supply them. `release-lane-test.log` preserves that harness failure. Production optimization was instead applied to the Debug test build.

Simulator startup also emitted CoreML MPSGraph compatibility diagnostics. The simulator cannot establish physical camera/model performance, GPS accuracy, road-noise speech recognition, thermal behavior or the real dashcam/Panoramax capture flow. No attached phone was installed, deployed or touched during this preparation.

## Refreshed store screenshots

The four Apple locales each contain ten **1320 × 2868** PNG screenshots in `store/apple/screenshots/<locale>/iphone-6.9/`:

1. Safe dashboard, 47 km/h against a 50 km/h map limit.
2. Camera-reference presentation, 30 km/h with the camera-evidence marker.
3. Shared give-way pictogram alongside the speed-limit display.
4. Portrait dashcam interface, with the existing idle-camera demonstration fixture.
5. France: limit 50, excess 3, urban residential road; EUR 135, without a points deduction in the selected rule band.
6. Switzerland: limit 50, excess 11, urban residential road; CHF 250.
7. Belgium: limit 50, excess 5, urban residential road; EUR 58 (the rule details separately describe the EUR 10.67 fee).
8. Netherlands: limit 50, excess 12, urban residential road; contextual review indication, with no invented fixed tariff.
9. Walking-speed zone.
10. Unlimited motorway with 142 km/h telemetry.

The [country-example report](COUNTRY_STORE_EXAMPLES_2026-10-02.md#separate-official-dutch-monetary-reference-example) separately records the official Dutch monetary reference and correction calculation. Precise Dutch tariff selection is not implemented; the Dutch screenshot retains the actual contextual warning.

These are actual rendered application UI using explicit screenshot fixtures. They are synthetic demonstrations, not camera-inference or physical-device evidence. The dashcam preview is empty because the simulator fixture does not start a real camera or write a movie. Original screenshots were preserved in `screenshots-before/` beside the evidence.

All four complete contact sheets were visually inspected after regeneration. All 40 simulator captures had fully opaque RGBA alpha (255 throughout) and were re-encoded as RGB PNGs to satisfy App Store requirements. Decoded RGB bytes, dimensions, sRGB metadata and EXIF are unchanged; the originals and per-image before/after hashes are retained outside the repository in `screenshots-rgba-final-originals/` and `screenshot-rgb-normalization.json`. `screenshot-inventory-final.json` records every image's dimensions and hash; `screenshot-reports-final/` records all sixteen country examples and four give-way examples. Every country report resolved the requested country and rendered the requested language.

The capture script now accepts `PREBUILT_APP_PATH`, `DERIVED_DATA_PATH`, `CAPTURE_REPORT_DIR` and `CAPTURE_FILE` overrides. It also normalizes opaque captures to RGB with the declared Pillow dependency and preserves raw originals; non-opaque input is rejected without replacement. The store-package validator passed with zero errors after conversion. Country/pictogram reports are copied from the simulator for checking against the selected fixtures. The common screenshot fixture now supplies its already interpreted map/walking/unlimited input through the unchanged reference runtime, matching the existing country fixture; without that seeding, runtime startup could replace the displayed sign with an unknown dash. No policy or interpreter semantics were changed.

## Privacy and permission alignment

`PrivacyInfo.xcprivacy` now declares **precise location, photos/videos, user ID and other user content**, each linked to the user, for app functionality, without tracking. This describes the optional Panoramax path: geotagged JPEGs are uploaded with an account-linked bearer token; speed/sign annotations are embedded in the uploaded JPEG EXIF user comment. Audio processing remains on device and is no longer falsely declared as remotely collected audio.

Evidence: `PanoramaxAccount.swift` generates/claims a token and validates `/api/users/me`; `PanoramaxUploadClient.swift` sends authenticated uploads; `PanoramaxCapture.swift` embeds GPS and recognition annotations. Existing required-reason API declarations were retained. Server retention, access logs and deletion policy still require operator review; the manifest does not invent unverified remote retention claims. The store questionnaire and privacy policy must agree with this manifest.

Apple's recognized collected-data keys and manifest structure were checked against [Apple's data-type documentation](https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacycollecteddatatypes/nsprivacycollecteddatatype) and [TN3184](https://developer.apple.com/documentation/technotes/tn3184-adding-data-collection-details-to-your-privacy-manifest).

Camera, location, motion, microphone and Speech permission purpose strings are packaged in all four languages. Onboarding's spoken-correction copy now correctly names German, English, French and Dutch.

The current iPhone UI does not label camera recognition experimental. The remaining experimental labels apply to the distinct opt-in lane preview and were retained.

## Gates before external submission

- Freeze/commit the intended source, including the concurrent review-prompt implementation, and ensure the final artifact fingerprint matches it.
- Confirm the selected marketing version and unused build number in App Store Connect; build 10031 was retained for preparation.
- Review the current store SDK requirement, privacy answers, age rating, review notes and export-compliance answers. `ITSAppUsesNonExemptEncryption` is absent, so the console compliance declaration remains required unless an applicable exemption is confirmed.
- Review the ten screenshots and localized metadata as a single listing. Camera fixtures establish presentation only; do not claim broader recognition coverage than the validated country packs.
- Complete owner-approved physical-device/TestFlight acceptance checks before publication. Upload, submit, publish and deployment actions were not performed.
