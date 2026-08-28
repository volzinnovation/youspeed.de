# YouSpeed Store Release Checklist

Public launch: 29 August 2026.

## Data Refresh

- Verify the top-country and Germany regional data workflows complete successfully before submitting store binaries.
- Confirm every manifest and referenced map asset is publicly downloadable without authentication.
- Verify hashes, sizes, bundle versions, and minimum app versions in the published manifests.

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
- Archive/export iPhone with `scripts/iphone/archive_consumer_appstore.sh --allow-provisioning-updates`; the script rejects release credential keys in both the `.xcarchive` and exported `.ipa`.
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
- Build the Play artifact with `cd android && ./gradlew :app:bundleRelease`.
- Submit localized metadata from `store/android/metadata`.
- Submit Data safety answers using `store/android/data-safety`.
- Generate screenshots with `android/scripts/recreate_store_screenshots.sh`.

## Remaining Manual Review Items

- Confirm privacy/support URLs are live before submission.
- Run TestFlight and Play internal testing on physical devices.
- Review all user-facing text in non-welcome/debug screens for full localization coverage.
- Confirm legal review of advisory fine/points/driving-ban copy for each release country.
