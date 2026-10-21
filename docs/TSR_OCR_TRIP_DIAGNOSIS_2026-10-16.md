# Restriction OCR trip diagnosis, 16 October 2026

This investigation used read-only copies of the attached devices' logs,
collection databases, preferences and selected Panoramax photos. The iPhone's
ongoing upload was left running. The sources are retained outside the repository
in `/private/tmp/youspeed-ocr-trip-diagnosis-2026-10-16/` and
`/private/tmp/youspeed-cross-device-trip-diagnosis-2026-10-16/`.

## Confirmed causes

The iPhone's stored feedback preference was absent, which selects the existing
sound-only default. Restriction speech requires the combined speed-and-signs
mode. No preference was changed during this investigation.

Build 10048's iPhone OCR integration skipped a read at serious or critical
thermal state, then permanently cached that failure for the encounter. Of 25
first confirmed numeric frames that could be joined to the post-installation QA
records, 15 were serious, seven fair and three nominal. Their lower-ROI geometry
was valid. This explains an important failure path, but is not a measured count
of OCR outcomes: ordinary trip logs did not contain those outcomes. Build 10049
allows bounded OCR at serious heat and defers critical heat without consuming
an attempt. The existing critical recognition scheduler is unchanged.

The supplied [public Motorola photo](https://panoramax.youspeed.de/api/collections/71750bfd-17df-4a62-b11a-ee5e35c8ce36/items/8e0020b0-b22b-490f-a287-cbcf4ad0b6c6)
was captured at 10:44:04.439 UTC (12:44 local time). Its clear 384×377 lower
rectangle reads `Mo-Fr` and `6³⁰–17³⁰ h`. The matching Android physical track
first confirmed 3.896 seconds earlier, when the analysis image supplied only a
21×24-pixel lower rectangle. Build 10048 rejected dimensions below 32 pixels
before invoking ML Kit and permanently cached failure. This is a deterministic
code-path explanation under the installed source, rather than proof from an
OCR outcome log. Build 10049 defers undersized views and admits improving later
views. See [implementation and benchmark notes](TSR_SUPPLEMENTARY_OCR_2026-10-16.md).

## Cross-device and capture evidence

Both devices recognized the primary School/Children class in Gernsbach around
08:38:26 UTC and 08:43:33 UTC. These encounters preceded installation of build
10048, so they cannot establish whether supplementary OCR worked in that build.
The label came from primary sign classification, not a demonstrated white-plate
OCR read.

Android requested infinity focus (`AF_MODE_OFF`, focus distance 0) for preview,
analysis and still capture. That code already existed in HEAD. No recorded
CaptureResult lens telemetry proves the Motorola honored those requests, so
dashboard focus is not yet independently confirmed or ruled out. Its negotiated
analysis input was 1600×1200, compared with the iPhone's 3840×2160; still photos
were 4096×3072. The smaller live input helps explain early tiny sign crops.

The claim that all Android morning photos failed to upload is contradicted by
three public EXIF-verified Motorola samples, including the Gernsbach school
encounter. They were captured during the morning and created on the Panoramax
server around 10:59–11:01 UTC. The catalogue contained 43 collections with the
same morning batch prefix. This proves those samples uploaded, not that every
original photo is accounted for. Automatic deletion after successful upload was
enabled; unlimited storage was enabled, so the historical 1000 MB eviction
theory does not fit the current settings. The midday public example uploaded
too, at 11:12:56 UTC.

Android analysis frames continued during the recorded active intervals, with
approximately 50 ms delivery spacing. Two observed interruptions aligned with
background/inactive lifecycle intervals at stationary GPS fixes. No recorded
camera-failure state establishes a whole-camera stall. A lost still-capture
callback could stop photos while analysis continues because there is no capture
watchdog, but missing per-photo request/save audit prevents proving that theory.

The iPhone has a roughly 20-minute recognition/QA gap around the supplied
midday scene, with GPS logging also stopping. Heat was recorded around the gap;
no explicit critical transition establishes its cause. A log message containing
`thermal_paused` also covers serious heat in a separate subpipeline and must not
be treated as proof that the global critical scheduler stopped the trip.

## Limits of the evidence

The production management tunnel was unavailable and the read-only SSH attempt
timed out. Today's uploaded `supplementary_ocr` records were therefore not queried
directly from production PostgreSQL. Sent device queues prune their payloads,
so local absence does not prove an OCR attempt never happened. Legacy log
`restrictions=0` describes a separate policy array, not OCR output.

Build 10049 adds per-attempt outcome diagnostics and immutable OCR attempt
events. A separate synthetic round-trip verified that the deployed opaque
transport preserves those payloads through capture/archive/import into actual
temporary PostgreSQL JSONB, without creating human corrections. This is a
transport/storage proof, not a retrospective measurement of today's reads.
