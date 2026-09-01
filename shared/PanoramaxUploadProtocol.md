# Panoramax client contract

The iPhone and Android clients share this protocol boundary instead of embedding the Python CLI. The CLI is a useful reference implementation, but it also contains terminal UX, filesystem reports, migration, and download commands that do not belong in a mobile app.

Panoramax still capture is one independent consumer of the shared Drive Recorder camera session. It shares the drive-session ID, timestamps, and location samples with Dashcam and traffic-sign recognition, but neither Dashcam frames nor traffic-sign detections are Panoramax upload inputs.

## Authentication

1. Normalize and require an HTTPS instance origin.
2. `POST /api/auth/tokens/generate` creates a token.
3. Open the returned claim link so the user can associate the token with their Panoramax account.
4. Store the token only in the platform secure store (iOS Keychain; Android Keystore-backed encrypted storage).
5. Validate with `GET /api/users/me` and send it as `Authorization: Bearer`.

There is no YouSpeed-wide API key. Credentials are instance-specific. Connecting an account never opts the user into capture and never schedules an upload.

## Post-drive upload gate

Capture and upload are different state machines. The upload transport must reject processing unless all of the following are true:

- the shared drive session is fully inactive, not preparing, recording, interrupted, stopping, or finalizing;
- the Panoramax batch is no longer `capturing`;
- the user has reviewed the local stills and explicitly included at least one original;
- the batch has been explicitly approved for upload; and
- valid credentials exist for the selected Panoramax instance.

Stopping a drive only closes the local batch and makes it available for review. It must not create an upload set, upload a file, or schedule an automatic upload. Restoring a batch, regaining connectivity, connecting an account, or retrying app startup must not bypass this gate. Processing may happen immediately after the drive or in a later app session.

## Upload set

After the post-drive gate succeeds, the platform adapter implements this sequence:

```text
POST /api/upload_sets                         {title, estimated_nb_files}
POST /api/upload_sets/{id}/files              multipart field: file
POST /api/upload_sets/{id}/complete
GET  /api/upload_sets/{id}                     poll until ready/complete
```

Only user-included Panoramax originals are sent. Dashcam video and transient TSR frames are never part of this protocol. The local queue records the remote upload-set ID and per-item state so a partial upload can be retried later without discarding captures or reopening the camera. Already accepted originals must not be uploaded again.

## Image metadata and cadence

Every Panoramax original must be a JPEG with EXIF GPS latitude/longitude, capture date, and, when available, `GPSImgDirection`. The still cadence is independent of traffic-sign detections and Dashcam segment boundaries. Distance mode requires movement of at least `max(configured distance, 2 × max(previous accuracy, current accuracy))`; time mode still requires enough movement to reject stationary or GPS-ambiguous duplicates.

## Platform split

`shared/` defines the capture metadata, queue-state, and post-drive upload boundary. Swift and Kotlin own the shared camera adapters, secure credential storage, local queue persistence, and platform upload transport. A single neutral camera owner fans frames out to independently enabled Dashcam, TSR, and Panoramax consumers; no Panoramax uploader participates in the active camera pipeline.
