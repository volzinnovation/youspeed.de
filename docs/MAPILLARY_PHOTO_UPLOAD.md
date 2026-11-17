# Native Mapillary photo upload

Both apps offer Mapillary as an additional destination in the existing photo
gallery. Select photos, open Mapillary, and start the upload. Settings contains
a separate Mapillary account section: each user supplies their own user upload
token, with upload permission. A read-only application/client token is not an
upload account. There is no bundled user account or credential. Browser OAuth
would additionally require a registered YouSpeed application and redirect URL;
the current connection flow uses the user token directly.

Credentials are stored in iOS Keychain or Android Keystore-encrypted,
backup-excluded storage. Connecting or restoring an account does not upload
photos. The upload screen explains that selected photos, capture timestamps and
GPS positions are submitted to the user's Mapillary account for publication.

The implementation is native Swift/Kotlin. It follows the official Mapillary
Tools protocol without shipping Python:

1. Verify the user's identity with `GET https://graph.mapillary.com/me` using
   `Authorization: OAuth <user token>`.
2. Prepare a separate JPEG containing the documented `MAPLatitude`,
   `MAPLongitude`, UTC `MAPCaptureTime`, `MAPSequenceUUID` and optional heading,
   altitude and accuracy in EXIF ImageDescription. Verify the original against
   the capture sidecar; preserve the original bytes. App-specific Panoramax
   annotation comments are omitted from the Mapillary copy.
3. Query the upload session's offset at
   `https://rupload.facebook.com/mapillary_public_uploads/<session-key>`, then
   POST the remaining bytes with `Offset` and `X-Entity-Name`. Retries re-read
   the server offset. Token-bearing redirects are disabled.
4. Upload an ordered image-handle manifest and submit its handle to
   `/finish_upload` with `file_type=mly_bundle_manifest`. A returned cluster ID
   confirms submission for processing, not completed publication.

Prepared JPEGs, returned handles and processing cluster IDs are persisted in
an independent, account-bound queue. Interrupted jobs require an explicit
resume; no upload starts automatically on app launch or network changes.
Successful transfers are checkpointed before advancing. Retrying submission
after a lost/error response reuses the saved manifest handle. Completed photo
IDs prevent overlapping later selections from sending those photos again.
The gallery displays Mapillary submission status separately from Panoramax.

Recording/capture uses the same upload eligibility policy as the existing
Panoramax flow. Starting recording cancels active Mapillary requests. The two
destinations cannot upload concurrently, and Mapillary never changes Panoramax
item states or deletes the captured originals. Temporary Mapillary copies are
removed after the submitted cluster has been saved durably.

Protocol references:
[upload service](https://github.com/mapillary/mapillary_tools/blob/main/mapillary_tools/upload_api_v4.py),
[identity and submission API](https://github.com/mapillary/mapillary_tools/blob/main/mapillary_tools/api_v4.py),
[image metadata schema](https://github.com/mapillary/mapillary_tools/blob/main/schema/image_description_schema.json),
[manifest uploader](https://github.com/mapillary/mapillary_tools/blob/main/mapillary_tools/uploader.py).

Tests exercise the protocol with fake transports, real JPEG metadata, durable
restart/resume, offset validation, recording gates, original-file integrity,
account separation and overlapping selections. UI smoke tests verify the
per-user Settings entry. They do not publish real photos or validate a live
user's upload permission against Mapillary.

Validation on 17 November 2026: 12 Swift upload tests and 12 Android upload
tests passed, plus one Settings UI test on each platform (26 tests total).
The signed iPhone build and normal Android build use version 1.5, build 10107.
Both were installed in place on the attached phones. The iPhone dashboard was
verified through QuickTime; the Android dashboard and account field were
verified on the phone. Both retained the active BW Mapillary context with
SHA-256 `8551d98ea340ed2a1a747cec50f956d45e567b6f9993fdda7b5253bd5675864b`.
Machine-local screenshots, logs and installation receipts are retained under
`output/mapillary-upload-2026-11-17/`.
