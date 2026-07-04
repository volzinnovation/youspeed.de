# YouSpeed Store Release Checklist

Status date: 2026-07-04

## Data Refresh

- Top-country data sequence dispatched on `main`: https://github.com/volzinnovation/youspeed.de/actions/runs/28707346080
- Germany regional data sequence dispatched on `main`: https://github.com/volzinnovation/youspeed.de/actions/runs/28707346045
- Latest local check: both workflows were still `in_progress`.
- Verify both workflows complete successfully before submitting store binaries.
- Verify release manifests are public or served from a public HTTPS endpoint; production apps must not require an embedded GitHub token.

## Local Verification

- `python3 -m pytest tests/map`: passed, 72 tests.
- `cd android && ./gradlew :app:testDebugUnitTest :app:assembleDebug :app:bundleRelease`: passed.
- `cd android && ./gradlew :app:connectedDebugAndroidTest`: passed, 39 instrumentation tests with live/opt-in replays skipped.
- `xcodebuild build-for-testing -project iphone/SpeedDBBench.xcodeproj -scheme SpeedConsumer -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO`: passed.
- `xcodebuild build -project iphone/SpeedDBBench.xcodeproj -scheme SpeedConsumer -configuration Release -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO`: passed.
- Apple screenshot set: 24 PNGs at 1320x2868.
- Android phone screenshot set: 24 PNGs at 1080x1920.
- Android icon/feature graphic spot check: 512x512 and 1024x500.

## Apple

- Build uploads must use the current App Store SDK requirement. Apple announced that, starting April 28, 2026, iOS/iPadOS uploads need the iOS 26/iPadOS 26 SDK or later.
- SpeedConsumer is configured as iPhone-only for the first public release to avoid an unverified iPad screenshot/layout track.
- Regenerate project with `scripts/iphone/generate_xcode_project.sh` after project.yml changes.
- Archive with distribution signing and upload through Xcode Organizer or Transporter.
- Submit localized metadata from `store/apple/metadata`.
- Submit privacy answers using `store/apple/privacy/app_privacy.md`.
- Generate screenshots with `scripts/iphone/recreate_store_screenshots.sh`.

## Google Play

- Android targets API 35, matching Google Play's Android 15/API 35 requirement for new apps and updates.
- Production builds do not embed `YOUSPEED_RELEASE_READ_TOKEN`.
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
