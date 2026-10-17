# Side-by-side OCR drives, 17 October 2026

Both attached phones ran version 1.4/build 10051. Read-only copies of their
traffic-sign logs, QA events and Panoramax queue metadata are retained outside
the repository at `/private/tmp/youspeed-ocr-comparison-2026-10-17/`.
The private evidence directory contains source hashes, reproducible analysis
scripts, journal-replayed queues and selected original iPhone photographs whose
hashes match the capture metadata. Raw photographs and precise locations are
not repository fixtures.

## Measured on-device outcomes

| Device | Drive | Completed pipeline attempts | Accepted read events | Numeric read events | Attempts with OCR-engine pass evidence | Panoramax originals |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| iPhone | First | 347 | 17 | 8 | 31 | 793 |
| Android | First | 299 | 7 | 4 | 12 | 973 |
| iPhone | Second | 307 | 9 | 3 | 25 | 904 |
| Android | Second | 278 | 1 | 0 | 6 | 857 |

These are diagnostic events, not independently surveyed signs, correct
transcriptions, or guaranteed visible labels. Retries can read the same sign
more than once. Sixteen of the iPhone's 26 accepted events occurred on retries.
Android accepted text on six scoped tracker associations; tracker fragmentation
and revisits prevent treating that as six surveyed roadside signs.

The pipeline first selects a separate supplementary plate. It recorded
`no_separate_plate` on 598 iPhone and 548 Android attempts; those events have no
engine pass. A primary sign without a supplementary plate correctly takes that
path. These counts cannot be used as OCR accuracy, precision or recall, and do
not establish how many readable plates were missed. One native and one 2× pass
belong to one attempt.

The first Android drive was active from 14:18:21 to 15:06:14 CEST, and the
second from 16:46:30 to 17:28:56 CEST. iPhone recognition logs cover both drives,
but its first Panoramax batch only starts at 14:31:16 CEST. Its earlier clock
read therefore has no corresponding still in that iPhone batch. Queue counts
above include journal replay; checkpoint files alone undercounted captures.

## Examples and demonstrated failure paths

iPhone accepted `Mo-Fr\n630-1730 h` at 14:25:31.637 and 17:23:06.509 CEST.
It also read `Kindergarten`, `Lärmschutz`, `Schulweg\nkreuzt`,
`Straßen-\nschäden` and other plates. Partial-looking accepted outputs such as
`Larmsc` and `trei bis\nHaus Nc` still require photographic ground truth;
an accepted diagnostic is not a correctness certification.

For Android's 14:25:24.500 CEST source frame, the native pass read
`Mo-Fr\n630-1730 h` and the 2× pass read `Mo-Fr\n630-1730h`, but admission of the transcription failed with
`insufficient_native_detail`. A subsequent closer attempt lost the numeric
clause. This is a measured quality-gate outcome, not proof that ML Kit could
not transcribe the text. Other Android accepted events include `Lärmschutz`,
`STOP\n100m` and `2 Std.\n-\nwerktags\n8-18h`.

Eleven Android events reported `failed` without engine passes. Exact-frame
geometry reconstruction finds a 47-pixel crop in all eleven. Admission rounded
the crop edges differently from bitmap extraction, allowing an apparently
48-pixel view to consume an attempt before extraction rejected it. The narrow
fix uses the same native context rectangle for admission and extraction,
following the iPhone geometry semantics. OCR quality thresholds are unchanged.

Android's recorded analysis input is 1600×1200, versus the iPhone's raw
3840×2160 (2160×3840 upright when rotated). Panoramax stills are separate
captures at different timestamps and resolutions. Android camera delivery
snapshots show approximately 30 frames/second; inference samples were around
340 ms, with intentional busy/cadence drops. These are different measurements.
The observed iPhone `thermal_paused` path diagnostic covers the lane/path
pipeline and cannot establish that all recognition stopped: six accepted OCR
events have an exact QA-frame join at serious thermal state.

## Presentation fixes and validation

The iPhone view model cleared accepted OCR on a later textless primary result,
even though the OCR tracker retained its successful read. Presentation now
retains fresh text only for the matching physical sign. A replacement clears
it; a visual miss does not extend its existing three-second expiry. Original
OCR frame, timestamp and geometry provenance remain intact.

The speed-circle layout previously changed its height budget when a label
appeared. A stable supplementary-label slot now keeps the circle and telemetry
geometry constant. Android numeric and pictogram labels now use black semibold
text on bordered white plates, matching the preferred iPhone treatment.

Validation passed 39 focused iPhone logic tests with one optional private-fixture
skip, a final 17-test retention rerun, and a portrait/landscape UI regression
comparing circle and metric frames with and without OCR text within 0.5 points.
Screenshots were visually inspected. Android presentation compilation passed.
The Android crop fix passed full Kotlin compilation and 22 focused tests in an
isolated build directory, including the recorded 47-to-48-pixel boundary.
Changes have
not been installed on either phone. The protected speed-reference policy and
its interpreter semantics were not changed.

## Upload and server comparison status

The owner started the uploads through both apps. A live queue snapshot confirms
all four drive batches are uploading, without sequence gaps:

| Device | Drive | Originals | Remote upload set |
| --- | --- | ---: | --- |
| iPhone | First | 793 | `0f72241c-3e90-4848-a713-dfe885b8fbdb` |
| iPhone | Second | 904 | `ef256f62-ff4a-4920-9cff-52405940f58b` |
| Android | First | 973 | `e36ccacb-8197-4a14-99a2-56f47b73d612` |
| Android | Second | 857 | `c9e35269-9e9c-4639-8707-d6ba8409490b` |

At 17:53:53 CEST, direct server receipts showed 51, 50, 36 and 47 accepted
files respectively, with zero broken or rejected files. All four sets were
still incomplete, undispatched and not ready; none had associated collections.
These are progress counts, not completed-upload totals.
The later 18:03:29 CEST receipt confirms continued progress: 226/793 and
227/904 iPhone files, 238/973 and 270/857 Android files. All four sets remain
incomplete, with zero broken or rejected files.

Transfer acceptance, upload-set completion, public photo processing, corpus
import and server OCR completion are separate states. The server publishes
positive OCR into Panoramax annotations tagged
`youspeed|ocr_source=plate-ocr-v1`, with raw text, parent annotation, attempt and
pipeline provenance. The known
[16 October Motorola example](https://panoramax.youspeed.de/api/collections/71750bfd-17df-4a62-b11a-ee5e35c8ce36/items/8e0020b0-b22b-490f-a287-cbcf4ad0b6c6)
still exposes `Mo-Fr\n630-1730h`, proving this path is live; it is not a result
from today's drives.

Server OCR is limited to white supplementary plates beneath positive numeric
maximum-speed or zone-start signs. The iPhone's 15 pictogram read events are
outside that comparison scope. Missing public OCR annotations cannot
distinguish processing delay, excluded geometry, rejected text, no-text or
failure. The documented corpus job imports the previous day's images at
03:30 Europe/Berlin, with OCR scanning every 15 minutes; new uploads may await
that import. Direct management SSH was unavailable during this investigation,
so the configured live schedule could not be freshly attested.

The owner requested a one-time follow-up for 18 October at 04:30 Europe/Berlin;
it is saved as the heartbeat **Compare test-drive OCR after upload** in this
chat. The separate existing overnight deployment audit remains unchanged.

Today's production server-versus-device comparison remains pending transfer and processing.
Join exact source-frame/track provenance when available; nearby capture time,
location or identical text alone must not be presented as an exact sign match.
The private metadata fetch helper and result receipts will retain current item
IDs and source hashes once those results are available.

## Manual investigation while transfers run

The owner also requested one manual investigation now. Management access still
times out, and incomplete upload sets cannot supply their public collections
yet. A local diagnostic uses the unmodified server worker and selector from
recorded deployed revision `ee35a906d5f68a0c0dbb6065344acad910ef73ce`, pipeline
`40605eb8a7e17aba24014f97a396aeef4cfdaf8545feadf290d728282d0fdb60`.
Its source hashes match the recorded successful 17 October 08:48:20 UTC
deployment receipt. This is not fresh attestation of the running hosts.
Pinned dependencies run on macOS ARM CPU, rather than the production Linux
runtime. No photographs were uploaded to a separate compute service.

The diagnostic preserves 31 hash-verified native originals: 15 iPhone and
16 Android stills selected around numeric OCR events. Twenty-one app-declared
numeric boxes are present across 20 of those photos. Independent visual
inspection finds all 21 boxes misaligned with the pictured numeric sign;
some cover roofs, foliage or a different sign. The unchanged server plate
selector rejects all 21 before OCR. These are geometry/association failures in
this selected sample, not 21 OCR-engine failures or a population error rate.

Source inspection explains an unsafe association path on both clients: still
metadata records capture-request time; queued annotations select a nearby still
within five seconds, then multiply the live-frame normalized box by the still's
upright dimensions. There is no motion reprojection or still re-detection.
For iPhone photo `8C45FFAD-F08A-4D64-9D50-F84FCF9AF6B4`, retained EXIF shutter
time is 15:23:03.461 UTC while the attached annotation is from 15:23:06 UTC;
its declared box covers a roof. The Android clock example also has a shutter
delay relative to capture-request metadata. Its rewritten `DateTimeOriginal`
must not be treated as independent precise shutter evidence. EXIF upright
dimensions agree with the clients' interpretation; the variable offsets and
scales do not support correcting this with one constant coordinate offset.
Field-of-view differences remain unquantified. This capture-annotation issue
is documented for further repair; current uploaded evidence was not rewritten.

An independent assistant visual review supplies primary-sign boxes
for 11 selected stills, preserving native pixels and running the same selector
and worker. Those boxes are assistant-reviewed diagnostic inputs, not production
server detector output. This separates wrong source pixels from the ability
to transcribe a real plate. Final worker outcomes are retained under
`server-local/` in the private evidence directory.

The completed batch retains all 32 preprocessing outcomes. In the reviewed-box
arm, six examples have no selected complete plate, one is below the geometry
floor, and four reach OCR. Three reads are accepted and one abstains:

| Native still | Plate pixels | Server-code diagnostic outcome |
| --- | --- | --- |
| Android `4c9f7f92-0722-4b38-9a2d-b1ccb3ac9e39`, 14:25:23.656 CEST | 146×86 | `Mo-Fr\n630-1730h` |
| iPhone `9DAF6BB3-9BDF-4517-AEAC-F7BF7887A72D`, 14:48:13 CEST | 155×86 | `Lärmschutz` |
| Android `444a7c69-7408-4b48-934d-ffb5d8067713`, 14:51:19.660 CEST | 83×45 | `Lärmschutz` |
| Android `49d03175-924d-4513-a7c8-98c1f2e8cf90`, 17:23:12.671 CEST | 76×45 | Abstained: `small_text_disagreement` |

The last example's native pass reads `Mo-Fr\n6=-17h`, while its 2× pass reads
`Mo-Fr\n6-17`; they do not provide one consistent complete transcription.
Both pass outputs remain available despite the no-text final decision.
The three accepted outputs agree with the preceding visual review.

For the first Android clock encounter, the phone's explicitly associated
84×48 live plate produced the same complete time expression but was rejected
as `insufficient_native_detail`; the larger 146×86 still crop was accepted by
the server code. This compares two different native inputs and their engines
and quality gates, rather than proving that changing engines alone fixes the
phone. iPhone live frames also accepted the time expression and `Lärmschutz`.
Its historical OCR log lacks the physical OCR association identity, so the
nearby noise-protection still must not be promoted to an exact OCR-frame join.

The manual run did not import observations or publish annotations. It used
original camera JPEGs and assistant-reviewed boxes, not the final privacy-
processed Panoramax pixels and production detector output. The production
comparison remains the scheduled follow-up. Evidence includes model artifact
hashes, package freeze, exact source/ROI hashes, selector decisions and both
recognition passes in `server-local/results.json` and `server-local/summary.json`.

## Live queue check — 17 October, 18:51 CEST

Management SSH access recovered. Fresh server upload receipts confirm all
3,527/3,527 files accepted and all four upload sets completed. Server preparation
has 2,669 prepared, one preparing and 858 not yet processed, with zero broken
or rejected files. None of the four sets is dispatched/ready yet. Completion
of transfer therefore does not mean completion of server processing.

The TSR classifier and its health service are running, and `/healthz` reports
`ok`. Its read-only SQLite queue has no pending/in-progress jobs: 6,852 are
published, 2,516 are held in `review`, and one historical job is in
`dead_letter` (7 September). Review reasons are 1,951 unmapped classes,
562 below threshold and three existing detailed classifications. Discovery
runs every 15 seconds after the preceding run finishes; the latest checked
execution succeeded. Today's still-processing upload sets must not be counted
as already classified because the classifier currently has no pending jobs.

The live prior-day corpus timer is active for 18 October at 03:30 CEST. The
20-minute retry timer is active, last succeeded at 18:40 and next runs at 19:00.
The corpus checkpoint is still 17 October 03:30:03 CEST, with 9,214 ready crops
and one missing geometry.

**OCR scheduling has a confirmed operational fault.** `YOUSPEED_OCR_ENABLED`
is true and cron invokes the ee35 dispatcher command every 15 minutes, most
recently at 18:45. Its output redirection targets
`/srv/woladen/logs/onboarded-ingest/youspeed-plate-ocr.log`, but `namei -l`
confirms `/srv/woladen/logs` does not exist. The shell therefore fails before
starting the dispatcher. The cron journal immediately closes that session and
discards output because no MTA is installed. A configured/firing cron entry is
not evidence that OCR is executing successfully.

Read-only PostgreSQL confirms zero exported/in-flight OCR jobs. It retains
93 result rows: 84 reads, eight no-text and one historical failure, with latest
result at 10:48:04 CEST. No scheduler repair or production change was made by
this status check. Repair of the log path is required for automatic OCR ticks
to execute. Fresh receipts are under
`server/check-20261017T1647/` in the private evidence directory.
