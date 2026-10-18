# YouSpeed 1.4 alpha build 10053 — 19 October 2026

Build 10053 contains the driving-control, photo-row, iPhone sign-size, nighttime TSR and Gernsbach tunnel fixes. Source: `6283797620d039419bd0b9688162ad7399a61d5c`. See the [diagnosis and validation](../DRIVE_UI_TUNNEL_DAYLIGHT_2026-10-18.md) and [release notes](RELEASE_NOTES_1.4_ALPHA.md).

Android: the [GitHub alpha release](https://github.com/volzinnovation/youspeed.de/releases/tag/android-v1.4-alpha) contains four signed 1.4-alpha APKs, base build 10053. [Arm64 APK (100532)](https://github.com/volzinnovation/youspeed.de/releases/download/android-v1.4-alpha/YouSpeed-1.4-alpha-100532.apk) is appropriate for the attached Moto g86. Its downloaded SHA-256 and v2 signature were verified; the certificate matches build 10052. The tag identifies the exact build source. Previous APKs remain labeled as build 10052; SHA256SUMS covers all retained APKs. The stable latest release remains android-v1.3.

Apple: **1.4 (10053)** uploaded successfully at 00:16:51 CEST and processed as VALID. Internal TestFlight state is IN_BETA_TESTING. Both existing internal and Beta-Ext group assignments and German test instructions were verified. The [TestFlight invitation](https://testflight.apple.com/join/k3a1pgce) retains its existing public-link configuration.

External review of 10053 is pending. Apple rejected the initial submission with ANOTHER_BUILD_IN_REVIEW because build 10052 remains WAITING_FOR_REVIEW. A later conditional submission was blocked by automatic approval review, which requires explicit user approval for external beta review beyond reuploading. The final read-only check confirmed 10053 remains READY_FOR_BETA_SUBMISSION. The public invitation may therefore offer an older approved build. No production submission was made.

The [artifact receipt](BUILD_10053_ARTIFACTS_2026-10-19.json) records build IDs, hashes, URLs and validation. Fresh drive verification remains pending with the owner.
