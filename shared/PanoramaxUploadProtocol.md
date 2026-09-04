# Panoramax client contract

The iPhone and Android clients share this protocol boundary instead of embedding the Python CLI. The CLI is a useful reference implementation, but it also contains terminal UX, filesystem reports, migration, and download commands that do not belong in a mobile app.

Panoramax still capture is one independent consumer of the shared Drive Recorder camera session. It shares the drive-session ID, timestamps, and location samples with Dashcam and traffic-sign recognition, but neither Dashcam frames nor traffic-sign detections are Panoramax upload inputs.

## Authentication

1. Use the fixed `https://panoramax.youspeed.de` instance origin.
2. `POST /api/auth/tokens/generate` creates a token.
3. Open the returned claim link so the user can associate the token with their Panoramax account.
4. Store the token only in the platform secure store (iOS Keychain; Android Keystore-backed encrypted storage).
5. Validate with `GET /api/users/me` and send it as `Authorization: Bearer`.

There is no embedded YouSpeed-wide API key. Each device creates and claims its own token on the fixed YouSpeed Panoramax instance. Connecting an account never opts the user into capture and never schedules an upload.

## Post-drive upload gate

Capture and upload are different state machines. The upload transport must reject processing unless all of the following are true:

- the shared drive session is fully inactive, not preparing, recording, interrupted, stopping, or finalizing;
- the Panoramax batch is no longer `capturing`;
- the user has reviewed the local stills and explicitly included at least one original;
- the batch has been explicitly approved for upload; and
- valid credentials exist for `https://panoramax.youspeed.de`.

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

## Progress, stopping, and local retention

Uploading is an asynchronous post-drive job. The gallery remains interactive and exposes durable item progress rather than waiting synchronously for an entire upload set. An item waiting for transfer is visibly distinct from one whose successful Panoramax response has already been recorded.

The user may stop an active upload. The client cancels the active transport task and persists the queue before returning control to the UI. Items with a completed server response remain uploaded and are skipped by later retries. An item whose request was in flight when cancellation occurred is recorded as `abandoned`, because the server may have accepted its bytes even though the client did not receive a response; it must not be retried automatically. Items whose requests had not started remain available for a later explicit upload.

Clients may offer an opt-in **delete local images after upload** setting. It defaults to retaining the local gallery. When enabled, originals, thumbnails, and gallery records are removed only after the remote upload set has successfully completed. A transfer response alone is not enough to delete the local evidence needed to finish or recover the upload set.

The same retention boundary applies to manual deletion: an accepted item in a partial or processing upload set remains selectable for an explicit Resume action, but cannot be deleted until that remote set completes. Captured, excluded, failed, or deliberately abandoned local items may still be removed while no upload task owns their batch.

Queue recovery runs before a new capture session can start. Historical `capturing` batches with no live camera owner become reviewable, interrupted upload states become resumable, and unreferenced files inside a successfully decoded batch directory may be scavenged. Recovery must never delete a referenced original or thumbnail, treat an unreadable queue record as proof that its images are orphaned, or conceal cleanup failures.

## Image metadata and cadence

Every Panoramax original must be a JPEG with EXIF GPS latitude/longitude, capture date, and, when available, `GPSImgDirection`. The still cadence is independent of traffic-sign detections and Dashcam segment boundaries. Distance mode requires movement of at least `max(configured distance, 2 × max(previous accuracy, current accuracy))`; time mode still requires enough movement to reject stationary or GPS-ambiguous duplicates.

## Platform split

`shared/` defines the capture metadata, queue-state, and post-drive upload boundary. Swift and Kotlin own the shared camera adapters, secure credential storage, local queue persistence, and platform upload transport. A single neutral camera owner fans frames out to independently enabled Dashcam, TSR, and Panoramax consumers; no Panoramax uploader participates in the active camera pipeline.
