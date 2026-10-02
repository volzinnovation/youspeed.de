# Google Play Data safety preparation — 1.3 / 2 October 2026

This is a review draft, not a submitted Play Console form. The CSV is an internal checklist, not Google's import template. Match final answers to the release binary, public privacy policy and both Panoramax operators' actual practices.

Google's definition of collection covers data transmitted off device; local-only access does not qualify. User-initiated transfer can meet a sharing exception, but that does not exempt collection. Mark collection optional only where all users can use the app without it. [Google Data safety guidance](https://support.google.com/googleplay/android-developer/answer/10787469).

## Known data flows and proposed form choices

| Play data type | Collection / purpose / optionality | Sharing assessment |
| --- | --- | --- |
| Photos | Yes; selected Panoramax JPEG upload; App functionality; optional; retained remotely, not ephemeral. | Confirm operator ownership and user-initiated sharing disclosure/consent exception. |
| Precise location | Yes for GPS embedded in uploaded photos; App functionality; optional remote collection. Live speed/road lookup is local. | Same photo-upload assessment. |
| User IDs | Yes for Panoramax account/token authorization and contribution association; App functionality / Account management; optional. | Confirm receiver roles and server handling. |
| Other user-generated content | Yes when sign annotations are embedded in uploaded JPEGs; App functionality; optional. | Same upload assessment. |
| Voice or sound recordings | Not collected by the app's ordinary voice feature: Vosk correction and dismissal run locally. | User exports, if added, would need separate review; no cloud speech endpoint is present. |
| Videos / ordinary camera analysis / device gravity | Local processing/storage; no automatic remote collection. Dashcam Share uses an external app chosen by the user. | Evaluate user-initiated transfer exception; do not claim local files can never leave the device. |
| Diagnostics / observation exports | Default-enabled logs remain local. Explicit user shares can contain GPS and technical details. | Confirm whether developer support receives/retains these, and whether a user-initiated exception applies. |
| IP/request metadata at download/API hosts | Recipients receive technical connection data. | Retention/purpose/type mapping requires operator confirmation. |
| Browser account-service name/email and server security diagnostics | Listed in YouSpeed's published server policy; actual app-flow collection scope, retention and purposes need reconciliation. Native clients do not parse name/email from validation. | System-browser login and host/research handling must be assessed; do not silently answer No. |

Global collection: **Yes**, because Panoramax uploads are an optional but implemented off-device flow. Global sharing: **pending confirmation**, not a blanket “No”. There are no advertising/analytics SDKs or tracking identifiers in app code; server practices still need verification. Known app network transfers use HTTPS. Export destination apps operate under their own handling rules.

## Permissions, defaults and local security

- `ACCESS_FINE_LOCATION` / coarse fallback and camera/microphone are declared; there is no background location permission or persistent foreground driving service. Continuous background operation is not a store claim.
- Camera sign recognition is opt-in and disabled initially. Photo capture and local diagnostic logs are enabled initially; permission is requested when the camera is first used, and photos are captured only under the app's runtime capture conditions.
- Local Vosk models for German, English, French and Dutch handle speed corrections; short local speech windows can accept “Wrong” after confirmed camera limits. Camera speech/output does not upload audio.
- Local app-private storage holds maps, photo queues, videos, corrections and logs. Android backup is disabled. Credentials are stored separately with Android Keystore-backed protection; tokens are excluded from diagnostic string representations.
- Production map downloads use public releases, without a private GitHub release token in the production artifact; verify the built bundle.
- Local delete/cleanup controls do not remove server-side contributions. Disconnect removes/revokes the authorization token; it does not delete the Panoramax account or uploaded images.

## Unresolved before submission

1. Both live configurations use public visibility and CC-BY-SA 4.0; published policies establish operator names and default pre-publication blur. Exact log/photo/backup retention, blur recipients, host contractual roles and research uses still require confirmation. See the [instance privacy audit](../../../docs/release/PANORAMAX_PRIVACY_READINESS_2026-10-02.md).
2. **Recommended account-deletion applicability: yes**, as a policy interpretation supported by OSM France's contributor-account creation on first login and external signup route. Google includes app-directed external creation. Verify an in-app and public account-and-data deletion request path before final Console answers; Disconnect only revokes the token. [Google account-deletion scope](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en-EN).
3. Verify prominent photo-upload disclosure and user selection support the sharing exception; otherwise declare sharing for the relevant types.
4. Verify any support-log receiver, purposes and retention; do not silently treat app-local diagnostics as server collection.
5. Confirm reviewer access for the upload flow and update the live public privacy policy before submission.
6. Reconcile account-service name/email, retained server diagnostics and research purpose mapping. Moonshots is the YouSpeed-instance publisher; HSPF's service-provider role is unverified, and OSM France is an independent public contributor service. Do not assume a service-provider sharing exemption.

Privacy URL: https://youspeed.de/datenschutz.html

## Source evidence

`android/app/src/main/AndroidManifest.xml`, `ConsumerSessionController.kt`, `PanoramaxAccount.kt`, `PanoramaxUploadClient.kt`, `PanoramaxUploadCoordinator.kt`, `PanoramaxJpegMetadata.kt`, `VoskSpeedCaptureSession.kt`, `VisionDismissalSpeech.kt`, `DebugLogPersistence.kt`, `StartupLogStore.kt`; equivalent iPhone flows checked first.
