# YouSpeed Store Release Checklist

Current Android preparation: **1.3 (10033), checked 4 October 2026**, saved in Play and awaiting review. See the [current Android audit](ANDROID_SUBMISSION_1.3_2026-10-04.md), [dated submission dossier](STORE_SUBMISSION_1.3_2026-10-02.md) and [store handoff](../../store/README.md). Historical public launch: 29 August 2026.

## Current release gates

- Chrome control is working. Play has 18 pending changes, including the signed 10033 bundle, all nine listing locales, Belgium, privacy URL and Data safety. Managed publishing is enabled; review submission remains pending.
- Align Play with the intended source: its recorded 10033 AAB predates the cross-border fix in the GitHub Android 1.3 release. A replacement needs a fresh unused Play version code and updated artifact names.
- Existing Android upload signing is verified and the old signed Play CI has passed. The iPhone 10032 upload is recorded separately; do not treat matching version names as matching platform binaries.
- Play reports 16 KB support for 10033. Actual 16 KB runtime verification and resolution of the separate native-audit findings remain outstanding; the Console compatibility result alone does not establish runtime acceptance.
- Complete the existing model rights/calibration/rollout reviews for the intended camera markets.
- Reconcile Panoramax operator privacy/deletion answers, approve and publish the revised public privacy/support sources, then verify live pages.
- Resolve account-and-content deletion initiation for the app-directed OSM France contributor-account creation flow; Disconnect only revokes a token.
- Finalize the corrected Data safety answers: the July declaration said no collection and no encryption. The owner-selected terms URL is now saved for privacy and deletion, and the URL field no longer blocks Next. Publish the prepared Moonshots contact/deletion amendment and verify retention and actual execution. Reconcile reviewer access: it currently says all features are unrestricted, despite Panoramax login.
- Freeze agreed source, match artifact fingerprints and complete physical-device acceptance before publication.

The prepared listings include four Apple locales, nine Android locales, 40 Apple screenshots, 72 Android screenshots and nine Play feature graphics. Camera recognition is presented as a standard feature. Validate and package the final local assets with `scripts/release/validate_store_package.py` and `scripts/release/package_store_submission.py`; neither contacts a store.

## Data Refresh

- Verify the top-country and Germany regional data workflows complete successfully before submitting store binaries.
- Confirm every manifest and referenced map asset is publicly downloadable without authentication.
- Verify hashes, sizes, bundle versions, and minimum app versions in the published manifests. The 2 October audit confirms 51 manifests and 198 distinct assets are anonymous/public and advertised sizes match HEAD responses; it does not independently hash full database bodies.

## Local Verification

- Run `python3 -m pytest tests/map`.
- Run `cd android && ./gradlew :app:testDebugUnitTest :app:assembleDebug :app:bundleRelease`.
- Run `cd android && ./gradlew :app:connectedDebugAndroidTest` on a representative device.
- Build and test `SpeedConsumer` for an iPhone simulator, then build the Release configuration with signing disabled.
- Check the Apple and Android screenshots, icons, and feature graphics at their store-required dimensions.

## Apple

- Confirm the build uses the App Store's current SDK requirement.
- Confirm the supported device families match the reviewed screenshots and layouts.
- Regenerate project with `scripts/iphone/generate_xcode_project.sh` after project.yml changes.
- Archive/export iPhone with `scripts/iphone/archive_consumer_appstore.sh`; use existing signing material first. The script rejects release credential keys in both the `.xcarchive` and exported `.ipa`. Provisioning changes require separate authorization.
- Submit localized metadata from `store/apple/metadata`.
- Submit privacy answers using `store/apple/privacy/app_privacy.md`.
- Generate screenshots with `scripts/iphone/recreate_store_screenshots.sh`.

## Google Play

- Confirm Android's target API meets Google Play's current requirement.
- Confirm production builds contain no repository credentials or private configuration.
- Configure upload signing with:
  - `YOUSPEED_ANDROID_RELEASE_STORE_FILE`
  - `YOUSPEED_ANDROID_RELEASE_STORE_PASSWORD`
  - `YOUSPEED_ANDROID_RELEASE_KEY_ALIAS`
  - `YOUSPEED_ANDROID_RELEASE_KEY_PASSWORD`
- Build and verify locally with `cd android && ./scripts/prepare-play-release.sh`. Use `--unsigned` only for preparation; an unsigned bundle is not upload-ready.
- Submit localized metadata from `store/android/metadata`.
- Submit Data safety answers using `store/android/data-safety`.
- Generate screenshots with `android/scripts/recreate_store_screenshots.sh`.

## Remaining Manual Review Items

- Confirm privacy/support URLs are live before submission.
- Run TestFlight and Play internal testing on physical devices.
- Review all user-facing text in non-welcome/debug screens for full localization coverage.
- Confirm legal review of advisory fine/points/driving-ban copy for each release country.
- Signed binary and listing uploads were performed in prior authorized work; the 4 October audit made no Console changes, review submission, deployment or publication. Follow the repository's explicit-approval policy for release actions.
