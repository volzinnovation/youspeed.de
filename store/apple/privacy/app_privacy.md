# Apple App Privacy preparation — 1.3 / 2 October 2026

This is an evidence-backed draft for App Store Connect, not a record of submitted console answers. Reconcile it with the final binary, privacy manifest, public privacy policy and Panoramax operator practices before submitting.

## Interpretation

Apple defines collection as off-device transfer accessible beyond servicing a real-time request. Local processing alone is not collection. Optional upload is not automatically exempt: all optional-disclosure conditions must hold. Panoramax contribution is a normal feature and account name is not prominently shown beside every submission; disclose its retained uploads. [Apple App Privacy details](https://developer.apple.com/app-store/app-privacy-details/).

## Known flows and proposed answers

| Flow / data type | Proposed collection and purpose | Linkage / tracking |
| --- | --- | --- |
| Panoramax geotagged photo uploads: Photos or Videos | Collected, optional feature; App Functionality. Only selected JPEGs are uploaded. | Linked to the authorized Panoramax account; not used for tracking by app code. |
| GPS coordinates embedded in those photos: Precise Location | Collected for upload; App Functionality. Core live positioning remains local. | Linked to the same upload/account. |
| Panoramax authorization/account identifier: User ID | Collected for account authorization and authenticated contributions; App Functionality. Credentials are not advertising identifiers. | Linked; no advertising linkage in app code. |
| Embedded traffic-sign annotations: Other User Content | Collected when present in the uploaded JPEG; App Functionality. Contains recognition/capture context. | Linked through photo/account. |
| Microphone / voice corrections / short “Wrong” listening window | On-device only; do not mark Audio Data collected merely because permission is requested. No cloud recognition fallback. | Local; no app audio upload endpoint. |
| Dashcam videos / ordinary recognition frames / gravity | Local only until user shares externally. Videos are not a Panoramax upload type. | No automatic developer collection. |
| Diagnostic logs / observation exports | Local by default; no automatic analytics upload. A user can explicitly export/share them, potentially with coordinates. | Evaluate the actual recipient and optional-disclosure conditions for developer support collection. |
| Map/model/catalogue downloads and Panoramax API requests | HTTPS; hosts receive connection metadata such as IP, requested resource and time. | Operator retention, purposes and account linkage require confirmation. |
| Browser account-service contact fields and server diagnostics | YouSpeed's published server policy lists name/email, authentication/security data and IP/server logs. Reconcile actual app-flow scope and retention before finalizing categories. | Native validation discards the profile body; system-browser login and server-side handling still require review. |

Tracking: the app integrates no advertising/tracking SDKs or advertising identifiers. Confirm both supported Panoramax operators' practices before final console submission. Do not substitute “Data Not Collected” for these optional authenticated uploads or mark upload location/photos unlinked.

## Local defaults, permissions and deletion

- Recognition and dashcam saving start disabled; photo capture and local diagnostic logging start enabled. Camera permission remains optional and is requested when camera use begins.
- Location uses When In Use authorization. Camera processing is suspended when inactive; no continuous background-driving feature is advertised.
- On-device speech uses Apple Speech with `requiresOnDeviceRecognition = true`; unsupported devices/languages do not fall back to a cloud recognizer.
- iOS Panoramax tokens are stored in Keychain for the selected server. Disconnect removes credentials and requests token revocation. It does not delete the remote account or uploaded photos.
- Videos, photos, map downloads and saved logs have local management/cleanup flows. Local deletion and uninstall do not delete retained remote contributions.

## Submission owner confirmations

1. Public server configuration confirms public upload defaults and CC-BY-SA 4.0 on both instances; the actual legal pages identify operators and pre-publication blur. Exact retention, blur recipients, host processing roles and research uses remain unresolved. See the [instance privacy audit](../../../docs/release/PANORAMAX_PRIVACY_READINESS_2026-10-02.md) and its linked primary sources.
2. OSM France creates its contributor account on first browser login. Apple's guidance covers external-browser account creation; reconcile this shipped flow with an appropriate in-app account-and-content deletion initiation path. Published email rights contacts and Disconnect alone do not demonstrate compliance. [Apple account-deletion guidance](https://developer.apple.com/support/offering-account-deletion-in-your-app/).
3. Supply review access for the optional authenticated upload flow without putting real tokens into metadata.
4. Verify the privacy manifest declares the same retained-upload categories and linkage as these proposed answers. Local-only audio is not a collected category.
5. Confirm any voluntary support/log collection exemption rather than silently choosing an unsupported answer.
6. Reconcile the newly inspected server contact fields, diagnostics and research purposes with store answers and the privacy manifest; the existing four-category upload proposal is not a complete certification of server practices.

Privacy URL: https://youspeed.de/datenschutz.html

Support URL: https://youspeed.de/support

## Source evidence

- `iphone/SpeedConsumerApp/PanoramaxAccount.swift`: HTTPS server presets, browser claim, validation, Keychain, disconnect/revocation.
- `iphone/SpeedConsumerApp/PanoramaxUploadClient.swift` and `DriveSessionViewModel.swift`: explicit selected-photo upload, authenticated JPEG transfer after recording stops.
- `iphone/SpeedConsumerApp/PanoramaxCapture.swift`: GPS/time/heading and EXIF UserComment sign annotations in JPEG bytes.
- `iphone/SpeedConsumerApp/VisionDismissalVoice.swift` and `DriveSessionViewModel.swift`: on-device speech requirement and bounded dismissal window.
- `iphone/SpeedConsumerApp/DebugLogPersistence.swift`, `StartupLogStore.swift`, `Info.plist`: default-enabled local logs, cleanup and permission declarations.
