# Panoramax capture foundation

Issue #3 starts with a platform-independent capture contract and a durable local queue. The queue intentionally contains only full-scene JPEGs, review thumbnails, and capture metadata; it has no dependency on TSR frames, detections, or diagnostic bundles.

## Storage and protection

- Android stores the queue below `Context.noBackupFilesDir/panoramax`. The Android app sandbox protects files at rest and `noBackupFilesDir` excludes originals, thumbnails, metadata, and queue manifests from Auto Backup/device transfer.
- iOS stores the queue below Application Support/`YouSpeed/Panoramax`, marks the root and descendants as excluded from backup, and applies `NSFileProtectionCompleteUntilFirstUserAuthentication` so background work remains possible after the first unlock.
- Queue manifests are written through a temporary file and atomic replacement/move. Originals are retained until an explicit deletion or a later upload worker confirms server readiness.

## Capture contract

`PanoramaxCapturePolicy` is deliberately independent of the traffic-sign pipeline. It uses a 25 m distance cadence with a five-second moving fallback, rejects stale or inaccurate fixes, and rejects stationary duplicate captures. `PanoramaxCaptureMetadata.validate()` blocks uploadable records without valid WGS84 coordinates, shutter time, location association, byte size, SHA-256, and software provenance.

CameraX/`ImageCapture`, `AVCapturePhotoOutput`, EXIF writing, instance selection/authentication, review UI, and background upload workers will attach to this contract in subsequent implementation slices.
