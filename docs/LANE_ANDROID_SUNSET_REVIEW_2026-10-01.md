# Android evening drive review — 2026-10-01

The attached Moto g86 5G, build 10027, contains a complete dashcam recording from approximately 18:32:05 to 18:41:25 CEST. The encoded movie is 559.026 seconds long and 619,433,104 bytes. The local copy matches the phone's SHA-256 (`df520e672db85d24c432612a029611a517833aea56f8ae79b37ead9d32848051`). Runtime, matcher and GPS logs were copied as bounded, hash-verified snapshots while the app was running. Device originals were retained.

Sampled footage shows wet roads, windshield droplets, urban road lettering, curves and dashed/solid paint in evening light. No astronomical sunset time is inferred. The recording decodes successfully at sampled points throughout its duration; this is not a complete frame-by-frame integrity scan.

The independent lane worker processed 3,980 logged exposures, approximately 7.12 Hz. Preparation p50/p95 were 14.016/27.761 ms, with a maximum of 299.147 ms. Twenty-four frames (0.60%) exceeded the 50 ms engineering target, with no geometry-budget rejection; the target remains telemetry rather than a cutoff. Exposure intervals p50/p95 were 133.387/233.427 ms, maximum 533.548 ms.

The preview accepted no border in 2,918 exposures, one in 867 and two in 195. There were 650 changes in the visible identity set and 161 distinct visible IDs. These are logged stability/availability observations, not manually labelled correctness, paint-supported duration or motion-compensated jitter. Every guide-trust result remained weak: 3,289 reported insufficient independent paint and 691 an observed-border conflict. Saved guidance cannot be treated as a reliable mounted-camera constraint for this drive.

The device process-exit history has no recorded app exit during this drive. The most recent entries before it are hourly manufacturer background-process kills, not lane-workload OOM events. This run does not establish that earlier Android memory failures are resolved; exact peak drive memory was not measured. Runtime diagnostics also report road-context invalidation and rejected context events, which require separate matcher/GPS review before attributing them to the image detector.

The useful next evidence is labelled rainy-road dashed paint, road lettering/merge negatives and an updated mount calibration. The observed identity churn supports keeping preview experiments opt-in. At the user's request, build 10029 moves the lane switch to the bottom of Diagnostics and resets existing selections to off once; later explicit opt-ins persist.

Evidence was collected under `inspector/logs/2026-10-01-android-sunset/`. Copied recordings and logs are being archived to the private Hugging Face dataset `loffenauer/youspeed.de`; the dated manifest maps the original paths to exact remote objects. Source analysis, sampled frames and this report remain local.
