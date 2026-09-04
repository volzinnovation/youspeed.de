# Panoramax capture foundation

Issue #3 uses the shared Drive Recorder camera lifecycle and a durable local Panoramax queue. Panoramax is one consumer of the camera, not the owner of a second camera session. Its queue contains only cadence-selected full-scene JPEGs, review thumbnails, and capture metadata; it has no dependency on traffic-sign detections, diagnostic bundles, or Dashcam video files.

## Shared camera session

One feature-neutral camera session owns rear-camera permission, configuration, start, interruption handling, and stop. An explicit drive start opens it once and an explicit drive stop closes it once. The session timestamps frames against the same drive-session ID and location stream, then fans them out to three independently enabled processing consumers plus one display-only consumer:

- **Dashcam:** encodes a local video recording when the user has separately enabled and consented to video retention. Its segments and retention policy are not Panoramax queue items.
- **Traffic-sign recognition (TSR):** analyzes the latest frame under its own throttle and backpressure rules. It does not persist the shared frame stream.
- **Panoramax still capture:** selects full-scene stills by distance or time cadence, adds EXIF location metadata, and writes them to the local review queue. A traffic-sign detection never triggers a Panoramax still.
- **Confidence preview:** presents the already-running session through an `AVCaptureVideoPreviewLayer`. It neither retains frames nor adds another camera output, and it can replace the speed/location workspace without hiding the speed-limit sign.

The consumers share camera frames and drive start/stop events, but not feature state. During a recording, the Dashcam and TSR controls may start or pause only their consumer; they do not restart or reconfigure the shared camera session. Disabling, throttling, or failing one consumer must not implicitly disable, enable, or trigger another. No consumer may open a competing camera session. Slow TSR inference drops stale TSR work rather than blocking Dashcam encoding or Panoramax capture.

### Current implementation slice

The iPhone app now has this neutral coordinator and uses one `AVCaptureSession` for the enabled outputs. The capture graph is fixed before the session starts so the active-recorder chips can safely start or stop Dashcam encoding and gate TSR delivery without camera reconfiguration. It records bounded, uniquely named local Dashcam segments, exposes a latest-frame consumer hook for TSR, captures cadence-selected Panoramax JPEGs, and provides a display-only confidence preview. Enabling Dashcam opens that preview; tapping the preview or the speed/location workspace switches between the two presentations. Camera interruption/runtime errors seal the local batch, all start/stop transitions have bounded timeouts, and JPEG metadata/thumbnail/queue work runs off the speed UI actor. The production TSR detector and fusion engine are not part of this slice: the user can select its chip, but until a validated country model is attached it remains visibly “selected, unavailable” and never publishes fabricated detections.

Android currently enforces the same durable queue invariants, including atomic sealing and rejection of late writes to a closed batch. Its shared CameraX owner and camera consumers remain the next platform implementation slice.

## Capture contract

`PanoramaxCapturePolicy` remains independent of the traffic-sign pipeline. Distance mode requires movement of at least the configured distance and at least twice the relevant GPS accuracy. Time mode requires the configured interval while still rejecting stationary or GPS-ambiguous duplicates. Both modes reject stale or inaccurate fixes.

`PanoramaxCaptureMetadata.validate()` blocks reviewable records without valid WGS84 coordinates, shutter time, location association, byte size, SHA-256, and software provenance. Panoramax retains only cadence-selected stills, not every camera frame.

## Process-later boundary

Panoramax capture and Panoramax upload are deliberately separate lifecycles:

1. While the drive is preparing, recording, interrupted, or finalizing, Panoramax may only add local stills to the current `capturing` batch. No upload-set or file-upload request may start.
2. Stopping the shared drive session stops new frame delivery, finalizes local Dashcam state, stops TSR analysis, and transitions the Panoramax batch to `awaiting_review`.
3. Later, with no active or finalizing drive, the user reviews stills, explicitly includes or excludes them, and approves the batch.
4. Only that explicit post-drive action may create a Panoramax upload set. Upload never starts automatically when a drive stops, connectivity returns, an account is connected, or a batch is restored after app launch.

“Process later” may happen immediately after the drive or in a later app session. Partial upload retries remain post-drive operations and must not reopen the camera.

## Storage and protection

- Android stores the queue below `Context.noBackupFilesDir/panoramax`. The Android app sandbox protects files at rest and `noBackupFilesDir` excludes originals, thumbnails, metadata, and queue manifests from Auto Backup/device transfer.
- iOS stores the queue below Application Support/`YouSpeed/Panoramax`, marks the root and descendants as excluded from backup, and applies `NSFileProtectionCompleteUntilFirstUserAuthentication` so later processing remains possible after the first unlock.
- Queue manifests are written through a temporary file and atomic replacement/move. Originals are retained until explicit deletion or until the post-drive upload worker confirms server readiness.
- Dashcam video uses its own protected local storage, consent, capacity, and retention policy. It is never treated as a Panoramax original.
- The current iPhone safeguard caps one Dashcam file at 5 GB and the local Dashcam library at 10 GB, evicting the oldest completed recordings. Dashcam retention is opt-in and its files can also be shared or deleted from the local library.

CameraX and AVFoundation adapters should implement the shared camera owner and attach Dashcam, TSR, Panoramax, and display-only preview consumers to it. Panoramax-specific code continues to own cadence, JPEG/EXIF creation, queue persistence, review, authentication, and the post-drive upload transport.
