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

## OCR log repair — 17 October, 19:25 CEST

At the user's explicit request, repaired the existing production OCR log path
on volz-db: `/srv/woladen/logs` and its `onboarded-ingest` child are directories
owned by `raphael:raphael` with mode 0750; the dispatcher log is a regular file
with mode 0640. Existing path components were checked for symlinks and the log
was created exclusively without replacing an existing file. The root cron
entry and installed release were not changed. This supersedes the missing-path
blocker reported at 18:51. Actual scheduled execution remains to be verified at
the next 19:30 tick; an empty repaired log alone does not verify it.

The separate one-off production run needs interactive sudo authentication:
Docker access is denied to the SSH account and `sudo -n` requires a password.
The user has been given the bounded existing host-wrapper command with
`--max-items 30`; do not report this manual production run as completed until
there is an execution receipt. This is distinct from the completed local CPU
diagnostic described above.

At 19:25, all 3,527 photographs are prepared and all four upload sets are
completed, dispatched and ready, with zero broken/rejected items. The TSR
queue has advanced to 9,122 published and 3,110 review, with no pending state
and the same one historical dead letter. These are global queue totals,
not matched per-drive recognition counts. PostgreSQL still has 93 OCR results
and no exported jobs; the newest result remains 10:48:04 CEST. Today's ready
collections still require the scheduled corpus import before they can appear
in that OCR input corpus.

## Scheduler verification — 17 October, 19:34 CEST

The repaired root cron executed at 19:30:01 CEST. The log records dispatcher
container creation followed by `ocr_job_submitted` for batch
`e1c1902c-cb9c-445c-9167-a82fa36401eb`, Hugging Face job
`6ad3b154c662881452269e77`:
https://huggingface.co/jobs/loffenauer/6ad3b154c662881452269e77 .
The configured maximum compute cost is USD 0.0075. The cron session closed at
19:33:09, and a read-only Hugging Face API inspection confirmed `RUNNING`.
This verifies real scheduler dispatch after the log repair, not just a cron
entry or a container startup. No cron cadence or installed release changed.

The same batch committed 54 exported queue rows, 24 skipped geometry and
1,320 skipped no-white-plate rows under pipeline `40605eb8…`; uploaded-file
counts must not be treated as distinct queue-row counts. Results had not yet
been imported at the 19:33 database check (93 total remained). A subsequent
15-minute tick should reconcile the submitted job and import completed
results. This batch uses the existing corpus; it is not evidence that today's
newly ready collections have passed their overnight corpus import.

The separate manual host-wrapper invocation remains pending interactive sudo
authentication by the user. The provided `--max-items 30` command uses the
existing global lock and active-batch checks; with this job active, it should
reconcile rather than submit a duplicate. Do not claim that a manual invocation
occurred merely because this scheduled invocation succeeded. The Hugging Face
connector's inspect operation was unavailable, so the successful read-only
status inspection used the locally installed Hub API and existing credentials.
Private evidence: `server/repair-20261017/{repair-receipt.json,scheduled-run.log,
new-batches.json,db-*.json}` under the comparison evidence root.

## Imported results and contribution — 18 October, 10:48–10:51 CEST

Read-only Hub API confirms job `6ad3b154c662881452269e77` is `COMPLETED`.
The repaired scheduler log explicitly records `ocr_results_imported` for its
batch `e1c1902c-cb9c-445c-9167-a82fa36401eb`, results=54. PostgreSQL independently
contains 48 read and six no-text results, zero failures for that batch. Its
last inference result completed 17 October 19:35:25 CEST. The 48/54=88.9%
selected-input read yield is not OCR accuracy, recall, or route coverage.
Twenty-four reads are the first read for their crop IDs; the other 24 repeat
previously read crops. Those photos date from 5 September through 16 October,
so this batch must not be reported as yesterday's test-drive comparison.

Exact `picture.upload_set_id` joins identify five successful current reads on
five distinct crops from the four 17 October test-drive sets. Their successful
publication was checked both in the publication table and in the public source
photo metadata, including exact attempt/job/pipeline identities:

| Drive | Published reads | Crops currently failed |
| --- | ---: | ---: |
| iPhone first | 1 (`Lärmschutz`) | 0 |
| iPhone second | 2 (`gefährliche Einmündung`; `Mo-Fr 630-1730h`) | 0 |
| Android first | 2 (`Lärmschutz`, separate photos) | 0 |
| Android second | 0 | 2 |

There are nine attempt rows on these seven distinct crops: two initial iPhone
failures were followed by successful retries. The two still-failed Android
attempts at 09:33 CEST record `LocalEntryNotFoundError`; they are not valid
recognition abstentions. No new job was submitted for this status analysis.

The original temporary comparison directory is no longer present. The paired
iPhone is available, so its two original drive TSR logs were reread, hashed,
and preserved privately. They independently reproduce 17+9 accepted events,
including 11 numeric events. Android is currently disconnected, so its
original logs could not be reread today. The production current mobile-link
view has zero rows; exact per-sign server/mobile joins are unavailable.

Whitespace-normalized comparison against all 26 accepted iPhone events finds
one extra server text label: `gefährliche Einmündung`. The actual source photo
was inspected and visibly contains that plate under a 50 sign. Nearby iPhone
50-sign attempts at 17:22:29–30 CEST reported `no_separate_plate`, and neither
full drive has an accepted dangerous-junction transcription. This establishes
one added label relative to the iPhone accepted-text set; it does not establish
exact frame/physical-sign matching or an Android uplift. Noise-protection and
time text already exist in the iPhone logs. Do not describe all five public
server reads as five novel roadside signs, or infer a percentage uplift from
attempt and crop counts with different grains. Public time text derives a
conditional candidate, but its metadata still says `evaluation_enabled=false`.

The 03:30 discovery snapshot advanced to 18 October but crop completion has not:
latest completed crop snapshot remains 17 October. Exact drive scope has 3,520
items in the snapshot vs 3,527 accepted uploads, and 2,877 active crop features:
2,470 ready, 153 queued and 254 retryable (`source_revision_stale`). These
features include signs outside numeric OCR scope. The current OCR scheduler
log reports the existing eight-job daily cap. These incomplete inputs and two
still-failed crops prevent a final server-versus-phone contribution percentage.
The supported estimate is five persisted server annotations so far, including
one confirmed additional text label versus the reread iPhone logs.

Fresh evidence, query source, executed/format-validated companion notebook and
original iPhone log hashes are preserved outside the repository at
`/Users/raphaelvolz/YouSpeedDeviceBackups/2026-10-17-ocr-comparison/2026-10-18-status/`.
The notebook's Python cells were run in order against saved extracts and their
assertions passed; a notebook UI visual review was not performed. No schedule,
release, policy, application, or publication setting was changed.

## One-time scheduled follow-up — 18 October, 10:53 CEST

The scheduled follow-up was delivered at 10:52 CEST and executed once. The
immediately preceding owner-requested analysis already verified completed and
imported OCR, five exact published drive results, and the constrained
contribution estimate. No duplicate cloud job, import, publication, or repair
was started by this follow-up. The installed symlink still resolves to
`onboarded-runtime-ee35a906d5`; the latest 10:45 OCR tick reports daily cap=8.

Fresh public upload-set receipts at 08:52:57 UTC confirm all four sets are
completed, dispatched and ready, with zero broken/rejected/not-processed files.
**New discrepancy:** the current iPhone first set/collection has 787 items
against estimated 793, and the second has 903 against estimated 904. Both were
previously verified as 793 and 904 at 19:25 on 17 October. Android remains 973
and 857. The current public total is thus 3,520, seven fewer than the earlier
3,527 accepted/prepared photos. The database's 3,520 discovered items match
these current public counts; the seven-item difference must not be attributed
solely to discovery lag. Current receipts provide no reason for the reduction.
They do not establish failed uploads, automatic deduplication, or who removed
anything. Identifying the seven original item IDs and their removal/processing
history remains an actionable completeness gap for the comparison.

New raw receipts and their SHA-256 values are preserved as
`heartbeat-upload-*.json` and `heartbeat-upload-receipt.json` in the durable
private evidence directory named above. The comparison's existing incomplete
crop and OCR failure limitations still apply. The heartbeat
`compare-test-drive-ocr-after-upload` was explicitly updated to `PAUSED` after
this run, preserving its name, prompt, one-time schedule and target chat.
Production cron and all unrelated automations were unchanged.

## Overnight new-footage OCR count — 18 October, 11:03 CEST

A fresh read-only query restricted to the four 17 October upload sets confirms
five published OCR child annotations on five photos; all 17 October footage
in the current corpus also totals five published annotations. Three were
published at approximately 05:37 CEST and two at 06:07 CEST. Texts are three
`Lärmschutz`, one `Mo-Fr 630-1730h`, and one `gefährliche Einmündung`.
The successful inference batches completed at 05:16 and 05:46 CEST.
Result batches are grouped by immutable `results.batch_id`, not the mutable
job row's batch ID, which changes on retry. The initial 03:46 failure of two
iPhone inputs was followed by their successful 05:16 retry. Two Android crops
failed at 09:33; a new retry batch `413828a0-cdff-4f59-b560-bce33d509e76`, HF job
`6ad48a9c5ccb47ba0f7c2d64`, was submitted at the 11:00 tick. Those two rows are
exported; no new result or annotation from that retry exists at this check.
The previously reported 54-result batch is historical footage and is excluded
from the overnight new-footage count. Exact query/result receipt:
`/private/tmp/youspeed-ocr-status-20261018/overnight-current.json`.

## Why only five overnight OCR annotations — 18 October, 11:08–11:12 CEST

The exact production ee35 selector, dispatcher and worker sources were read
from the installed release and hashed; no deployment, submission or queue write
was made by this investigation. Deployed worker SHA-256 remains
`0b5723ea89f3dfdac5d5d1e03bed3dac5522708a315ede0f88a4d828959d2ee1`, pipeline
`40605eb8a7e17aba24014f97a396aeef4cfdaf8545feadf290d728282d0fdb60`.

A read-only audit of all 2,877 active drive features uses the exact deployed
`numeric_eligibility` function and current mapping/fingerprint, visibility and
suppression checks. It identifies 439 eligible numeric crop features on
396 photos, partitioned as follows:

| Selector/processing outcome | Numeric crop features |
| --- | ---: |
| White-plate selector rejected | 390 |
| Supplementary geometry too small (`ocr_plate_too_small`) | 6 |
| Passed to OCR worker | 7 |
| Blocked before crop generation (`source_revision_stale`) | 36 |

Thus all 403 READY numeric crops have been screened, but not all 439 known
numeric features have reached screening. The 390 gate outcomes are not a
visual ground-truth assessment of plate absence; possible false negatives were
not exhaustively audited. The exact deployed waiting-candidate SQL returns
zero rows globally, so there is currently no ready eligible OCR backlog that
would run merely by raising the submission cap. Overall feature states at
11:08 are 2,472 ready, 150 queued and 255 retryable; the 150 queued feature
labels are unmapped and do not currently qualify for numeric OCR.

All 36 unvisited numeric features are on 33 photos in Android's first-drive
collection `80064e15-f3ff-4716-a85c-846accf0af65`. Every one has collection-level
`updated_at` drift between its stored source snapshot and current public
metadata. In three sampled photos, their picture timestamp and full annotation
list remained unchanged, while the collection timestamp advanced from
17 October 22:54:20 CEST to 18 October 06:07:03 CEST. The latter coincides with
OCR publication in that collection. The installed renderer's `check_source`
hashes the entire source record, including `collections[].sequence.updated_at`,
and rejects the changed timestamp before reading the image. A timestamp-only
change reproduces its rejection condition offline. Exact source history beyond
the public metadata was not queried; no stronger claim about unrelated field
changes is needed to establish this sufficient blocking difference.

The 20-minute retry service only calls `retry`, which retries stored metadata
without running discovery. It therefore repeats the mismatch and backs off;
the 10:40 and 11:00 services exit status 2 with `crop_complete=false`. The known
first-drive clock still `4c9f7f92-0722-4b38-9a2d-b1ccb3ac9e39.jpg` is among
these unvisited crops. Its positive isolated native-photo diagnostic must not
be counted as a production OCR annotation.

The two previously failed worker inputs have `LocalEntryNotFoundError`, a
Hub download/cache-resolution failure, rather than a no-text OCR outcome.
Both exact PNGs remain downloadable from the failed batch's pinned revision
`0ae67a6ef2b8515fe80a5baa1cdb973421937206` and match manifest hashes. The worker
suppresses the underlying exception detail, so the precise HTTP/network or
cache cause cannot be established from its logged class alone. Model downloads
completed in the job logs. A transient fetch/cache issue is consistent with
successful processing of the same hashes on the next scheduled retry.

The 11:00 retry completed at 11:01 with one accepted
`Mo-Fr 630-1730h Kindergarten` read and one valid `small_text_disagreement`
abstention (native `Mo-Fr 6-17h` vs 2x `Mo-Fr 6-17`). These immutable results
were fetched read-only. At 11:11 they are not imported or published yet, so
published count remains five; the next reconciliation can import the sixth
read. No new paid job was created by this investigation.

The cap is exactly eight batch submission intents over the previous 86,400
seconds, not a calendar-day or per-image limit. The authenticated HF inventory
confirms eight matching submissions in that window: three historical/other
batches and five new-drive batches, including failed/retried inputs. Several
batches contain only two or three crops despite the maximum of 200. HF marks
the whole worker job `COMPLETED` even when individual input attempts fail,
because the worker captures those failures into result rows and exits normally.
These batches still consume slots. Existing active-result reconciliation runs
before the cap check and is therefore allowed at the cap. The next slot should
age out around 19:30 CEST (submission intent precedes the 19:33 HF creation).

Recommended remediation order: refresh source discovery and render the 33
blocked photos with validation intact; repair stale-source handling for proven
owned publication/sequence metadata changes; add bounded input-download retries
and stage-specific failure evidence; then size/batch the rolling cost budget.
Increasing the cap alone does not resolve stale crop inputs. No source proof,
OCR quality threshold, speed-reference policy or cap was altered here.

Full private evidence, exact SQL/parameters, immutable retry outputs, input
hash verification and deployed source snapshots are in the durable
`2026-10-18-eligibility-audit` evidence directory under the private backup root.

## OCR crop and transport repair — 18 October, 11:54 CEST

The user requested removal of batch quotas and a production recovery of the
36 blocked numeric crops. Backend commit
`55f7c153286a032796ea6a636521a22760c11cae` implements that repair. It removes both
the eight-submissions-per-rolling-day quota and the sixteen-staged-batches quota.
The dispatcher still reconciles an existing job before submitting another;
input chunks retain memory/byte bounds and worker runtime deadlines.

Crop rendering no longer compares the full discovery source record. It checks
image dimensions, the target sign geometry/classification and current permitted
visibility, with the actual JPEG checksum checked before and after rendering.
Collection counters/timestamps and unrelated annotations cannot trigger the old
`source_revision_stale` failure. Context annotations come from the current source
read. Explicit `retry --crop-id` arguments allow the exact 36 crops to be retried
without resetting unrelated work. Temporary model, manifest and input downloads
retry up to four times with 1/2/4-second waits before inference; permanent access
errors fail immediately. The model and pipeline identity remain unchanged.
The focused test suite passed **170 tests**, with **14 skipped** because their
separate PostGIS environment was unavailable. A real PostgreSQL test verifies
that scoped retries leave unrelated backed-off crops untouched.

The older snapshots are discovery metadata/history, not replacement camera
images. All 33 affected photos came from discovery run
`b7443200-89cb-4fc5-b330-2c2eee8579fd`, at **18 October 03:30:03 CEST**, selecting
17 October footage. The 20-minute retry does not refresh that checkpoint. Own
OCR publication subsequently changed collection timestamps, which was enough
to make the old whole-record comparison fail. Earlier discovery runs exist for
previous footage; they were not the source run used for these 36 crops.

At **11:49 CEST**, read-only production verification shows **six published OCR
annotations** from the four drive upload sets. The 11:00 retry's Kindergarten
read was imported and published at 11:22; its other result was a no-text
abstention. All **36 recovery crops remain retryable with no OCR job** at this
baseline. The repair archive and exact recovery scope are staged and verified
on volz-db, but activation and processing still require the user's interactive
administrator authentication. **No new annotations from the 36 crops have been
claimed or published by this recovery yet.**

The prepared local launcher is
`tmp/ocr-side-by-side-2026-10-17/RUN_OCR_RECOVERY.command`. It activates the
complete shared runtime release using the existing static seed, activates the
management services, updates existing cron release references without changing
schedules, retries the exact scope, uses the production OCR dispatcher until
that scope has no ready backlog, and publishes accepted results. Final counts
must be verified from current job/result/publication rows and public Panoramax
metadata after execution; an empty OCR export alone does not prove all crops
were rendered or transcribed.

### Recovery deployment blocked by an active newer rollout — 18 October, 12:10 CEST

The user's launcher stopped before its sudo step because a newer, already
active release transaction existed. It was not a stale transaction:
`1b7ec787f850f8ebd405caeb881b6a93567fe8bb` descends from the OCR repair commit
and adds the separately authorized OCR job/publication identity repair. That
release is now activated on live-eu. The older launcher's deployment steps have
been removed to prevent a downgrade; the prepared recovery now only retries
the 36 crops, invokes production OCR, and publishes accepted results after the
existing management rollout completes. It changes no schedules or releases.

Management remains at `waiting_live_acceptance` with the source lock held and
OCR/publication schedules temporarily paused by that active rollout. Its core
backend checks passed, but ORS routing is unavailable. Automatic approval
review rejected issuing an acceptance receipt with that failed check without
explicit user approval of the exception. A decision is pending whether to
continue OCR activation while recording the separate routing outage. No
transaction, health gate or other rollout lock was bypassed here.

At **12:09:53 CEST**, all **36 crops remain retryable**, with no OCR jobs or
published results. At **12:10:07 CEST**, all **six existing drive OCR
annotations** were independently fetched anonymously from Panoramax and matched
the ledger's annotation UUID, picture UUID and expected semantics/transcript.
Recovery counts remain pending; no additional annotations are attributed to
these 36 crops. Private dated receipts and the revised scoped recovery helper
are retained in the private evidence directory.

### Why the routing gate blocked OCR

OCR has no runtime dependency on ORS. The deployment-only verification script
includes a route request in its required HTTP checks and requires route distance
before issuing the acceptance receipt awaited by management activation. That
couples OCR activation to unrelated routing availability; the shared backend
revision requirement does not itself create an OCR routing dependency.

Read-only checks on 18 October confirm that the separate ORS service on wingki01
has no running Java/ORS process or listener on port8082. Its retained log ends
with an explicit shutdown at **30 June 2026 11:03:34 UTC** and no later startup.
The log does not establish who stopped it or why. The live-eu proxy on8188 still
listens, but its reverse-tunnel endpoint18188 is absent; routing therefore
returns `route_provider_timeout`/504. Routing code/configuration was unchanged
by the OCR release. The user's question about this coupling is not approval to
bypass the activation hold; no exception or cross-chat decision was sent.
