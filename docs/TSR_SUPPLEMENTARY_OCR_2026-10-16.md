# Supplementary restriction text on device

Version 1.4, build 10051 collects, presents and speaks text on plates below
numeric speed signs and supported pictograms on iPhone and Android. It can
retry a read when a later view supplies substantially more native pixels.
For example, `22-6h` is displayed as `22–6 h`; `Mo-Fr / 630_1730 h` becomes
`Mo-Fr / 6:30–17:30 h` for display and a German weekday/time phrase for speech.
Weekday, weather and other clauses are retained, and collected raw text is unchanged.
The app does not evaluate the time window or other conditions, and the shared
speed-reference policy remains unchanged.

## Recognition and lifecycle

The native, upright primary-sign rectangle is extended downward by one sign
height. Both clients retain that native crop for plate detection, with a small
amount of context above the midpoint to distinguish a separate plate from the
parent board. OCR receives only a selected framed white plate below the midpoint.
A native pass and one bounded 2× interpolation pass use the same plate. Neither
searches the whole camera frame. The native lower rectangle and selected plate
must be at least 48 pixels wide and 32 pixels high. Missing native source pixels
defer reading without consuming an attempt. A completed attempt that finds no
separate complete plate records no accepted text and can retry on a larger view.

Both apps warm a reusable OCR engine asynchronously at startup using synthetic
text. Warm-up output is discarded. Numeric tracks use the existing primary
confirmation; pictograms use two distinct accepted display frames. The read can
start on a later frame. Up to six actual attempts per physical association are
allowed, at least 300 ms apart and only after at least 1.8× native ROI area growth.
Successful text remains available if a closer read returns empty or fails; each
actual attempt retains separate provenance. Serious iPhone heat permits OCR;
critical heat defers it, with the existing critical camera scheduler unchanged.
Capture/session/context invalidation clears the association.

OCR follows the currently selected sign group, as approved on 16 October 2026.
The existing primary/display selection chooses one group at a time; the numeric
group takes priority for OCR when it is present. Co-visible groups are not
independently queued for reading. This selected-group scope applies to both apps.

A confirmed speed sign may be presented while its first eligible OCR attempt
runs; its publication boundary waits for that completion. Deferred small/hot
views do not hold a speed sign indefinitely. Later retries update supplementary
evidence only, without replaying primary fusion, passages or speed authority.
Normal primary fusion and passage processing retain their existing semantics.

The annotation contains the complete recognized text block, an optional parsed
time window, read status, engine/model version, physical track, source frame and
timestamp, and primary/OCR boxes. Later matching frames may refresh presentation
freshness without changing that source provenance. Text expires from presentation
after three seconds without matching sign evidence. Disabling recognition,
backgrounding, context changes and shutdown invalidate presentation evidence.

The private evaluation crop is not bundled in the application or committed as a
test asset. Optional device tests receive it through the isolated test app.

## Display, speech and collection

Restriction text appears in a white label below its matching camera speed sign.
The label supports two lines. A complete time expression receives normalized
formatting; other text retains all clauses with whitespace normalized for display.
Supported other-sign pictograms show their matching supplementary text too.

Speech requires the existing combined speed-and-signs feedback mode. A fresh
restriction is appended to the speed announcement where possible; a late result
may receive one fresh, matching follow-up. Speech yields to primary speed feedback
and voice capture, and is deduplicated. English, German, French and Dutch time
phrases preserve minute fields; Italian time phrases are supported too. Compact
three/four-digit time pairs followed by `h`, including superscript digits, can
be formatted without extracting or discarding the surrounding conditions.

OCR and supplementary speech use the fresh location-derived country, separately
from the UI language or retained model pack. Switzerland allows German, French,
Italian and Romansh; Belgium allows Dutch, French and German. The app has no
precise language-area map for those countries. Clear lexical evidence and
confident unconditioned language hypotheses select among local candidates;
short clocks, ambiguous weekday abbreviations and detected mixed-language text
remain visible without a guessed voice. Missing matching voices also suppress
that readout. Raw text is never translated. Apple language support is queried
at runtime; build 10051 uses accurate recognition for the plate passes, including
Dutch. Unsupported
languages such as Romansh remain a platform limitation. Android uses bundled
ML Kit Latin OCR and bundled language identification; neither downloads a model
during a drive. Confidence thresholds are provisional, not calibrated accuracy
guarantees.

The consented collection path stores an optional `supplementary_ocr` object in
both sighting payloads and crop metadata. Raw text and the original OCR frame
remain separate from the primary classifier label. No-text and failure statuses
record that an attempt completed without inventing a restriction. `no_text`
means no accepted presentation text: a quality-rejected raw read may still be
present for audit. Rejected text never becomes a parsed window, display label or
speech. Trip diagnostics also retain each bounded pass, confidence, scale and
admission decision.
The optional field is covered by the pinned collection schemas on both clients.
Existing sightings committed before that sign became the selected numeric
candidate are immutable; later crops can retain its OCR annotation and link to
the existing sighting, but do not rewrite the earlier sighting payload. Every
actual attempt also creates an immutable `media_status` event with status
`supplementary_ocr_observed`, an attempt identity and full OCR provenance. This
works with metadata-only consent even when a crop is not retained. A verified
source-frame association links `observation_id`; otherwise it is explicitly
unresolved, rather than borrowing a nearby sign. Duplicate completions do not
add support frames, sightings or human corrections. The deployed opaque
`best_effort_v2` route preserves these events; canonical contract changes are
local in the sibling checkout and do not require a server deployment for that
route. A dedicated OCR summary in Inspector is still separate work.

## Validation and packaging

Tests cover confirmation, improving-view retries, tiny-ROI and thermal handling,
pictogram support, raw clauses, geometry, source provenance, collection contracts,
multilingual ambiguity and speech admission. Device suites use isolated application containers; normal
installed app containers must not be used for instrumentation/unit suites.

Android uses `com.google.mlkit:text-recognition:16.0.1` and
`com.google.mlkit:language-id:17.0.6`;
recognition requires no model download. This dependency must be considered in
any future F-Droid packaging review; the historical 1.0.x review does not certify
the current dependency set.

The original crop read correctly in prior attached-device measurements: warm OCR
averaged about 4 ms on iPhone 14 Pro (Vision fast) and 25 ms on Moto g86 5G
(bundled ML Kit). These are fixture measurements, not road-driving accuracy or
latency guarantees. Startup warm-up avoids the roughly 1.15-second Android cold
initialization measured in that experiment.

The preceding build 10048 passed 40 focused tests on the attached iPhone 14 Pro, including
actual runtime provisional → OCR pending → OCR completed delivery, the private
crop, raw presentation/speech, collection gating and annotation contracts.
The signed app was installed and launched, and device metadata confirmed
version 1.4/build 10048.

A separate synthetic backend proof passed 11 tests through the capture API,
signed archive and management import into an isolated PostgreSQL database.
The exact multiline annotation survived in sighting JSONB and the linked crop
manifest, including duplicate-import idempotency. A test-only JSONB domain stood
in for the spatial type; this proves annotation storage/import, not spatial
behavior. Read-only deployed capabilities report `best_effort_v2`, matching the
opaque payload path that accepts these optional fields without a server deploy.
No production database records were written by that test.

The Android build passed 78 focused unit tests (one existing repeat-crop test
was skipped) and the revised isolated Motorola device OCR test. The device test
reads the externally supplied crop through the post-confirmation native ROI path
and checks copied-pixel lifetime after source recycling. Temporary isolated test
packages were removed on both phones before handing back the normal apps.

The preceding version 1.4/build 10048 was installed and launched on both attached
phones; Android then reported `1.4-debug`/10048. Installed package metadata was
checked after that deployment. Source changes to the canonical backend contracts and
their tests are local in the sibling `Woladen.de-analytics` checkout; they were not
deployed. The existing Inspector raw view preserves the optional annotation in
the full sighting payload and crop manifest.

Build 10049 passed 50 isolated iOS simulator tests with no failures or skips,
including actual fixture OCR, serious thermal operation, pictogram reads,
improving-view retries, multilingual selection and immutable collection events.
An additional Mac core suite passed 16 tests. The current service read the
public Panoramax example six times: raw `Mo-Fr\n630_1730 h`, display
`Mo-Fr 6:30–17:30 h`, spoken German `Montag bis Freitag von 6 Uhr 30 bis
17 Uhr 30`. Mac warm median was 7.30 ms after startup warm-up; this is not an
iPhone timing measurement. The updated backend proof passed 13 tests through
capture, signed archive and real temporary PostgreSQL JSONB, including ignored
OCR media-status events in human correction counts. Shared contract validation
checked 25 exact files plus backend Pydantic semantics.

Both normal apps were installed and launched as build 10049. Before installation,
the iPhone Panoramax upload was independently confirmed complete through the
server's read-only upload-set endpoint. Installed metadata confirms iPhone bundle
`de.youspeed.SpeedConsumer`, version `1.4`/10049, and Android package
`de.youspeed.android.debug`, version `1.4-debug`/10049. Android's original
24 September first-install timestamp remains unchanged, confirming an upgrade.
The iPhone installation was not used to run the isolated test suite.

The final Android suite reports 74 tests, zero failures/errors and one existing
skip (73 passed). It includes late-completion collection retention after track
replacement and confirmed numeric OCR below the separate pictogram display
threshold. The normal Android 10049 APK built successfully, has the expected
`de.youspeed.android.debug` identity, and passed APK signature verification.
The reconnected Motorola passed both isolated physical-device OCR tests. The
private native 136×115 lower rectangle returned raw `22-6h`, displayed as
`22–6 h`, in 107.1 ms. The public native 384×377 plate returned raw
`Mo-Fr\n630-1730h`, displayed as `Mo-Fr 6:30–17:30 h`, in 88.1 ms. These are
two individual fixture completion wall times, not p95 or road-driving latency.
The public-plate test also checked local French and Italian text preparation.
After the isolated tests, temporary test packages and the two injected fixture
copies were removed. The normal Android app was installed successfully and
launched into `MainActivity`. The staged APK is
`/private/tmp/youspeed-android-10049.apk`. Verification results, install evidence
paths and the staged/source hash inventory are recorded separately under
`/private/tmp/youspeed-10049-device-verification/`.

## Public Panoramax server benchmark

The bounded [Hugging Face job](https://huggingface.co/jobs/loffenauer/6ad212ab5ccb47ba0f7b215b)
completed using PP-OCRv6 medium detection and recognition with PaddleOCR 3.7.0
and Paddle 3.3.1. It downloaded only the supplied public Motorola photograph and
read its native 384×377 lower rectangle. All five runs returned `Mo-Fr` and
`630-1730h`. The first read took 1,874 ms; four warmed reads had a median of
1,583 ms on CPU Upgrade, with two OCR threads and MKLDNN disabled. Model
initialization was another 1.86 seconds, excluding downloads. These are one-image
measurements, not production throughput or accuracy guarantees.

Results are saved in the existing private Hugging Face dataset under
`ocr-benchmarks/2026-10-16/public-moto-g86-8e0020b0-ppocrv6-medium-cpu.json`.
The job had a 15-minute timeout and a maximum compute charge of $0.0075; it
completed in about 70 seconds. No persistent endpoint or private trip upload was
created. Its raw result does not demonstrate an accuracy improvement over Vision
on this clear sample: both flatten the superscript minutes. Server processing
remains useful for later full-resolution Panoramax views and backfilling missed
device reads within the server scope below. A batch worker should retain original
device results and attach versioned derived OCR evidence. Unlimited-OCR has been
researched but has not been benchmarked or deployed; this result does not justify
claiming it superior for these lower speed-sign plates.

## Build 10050: complete raw text in trip diagnostics

Both attached phones were upgraded, launched and verified as build 10050 on
16 October. Android emits `supplementary_ocr_attempt` JSON with `rawText`; iPhone
emits `ocr_attempt_v1` JSON with `raw_text`. Embedded newlines, quotes and control
characters are escaped inside one physical log record. Consented records retain
the unchanged `supplementary_ocr.raw_text`, including multiline text and clauses
through the existing 4096 Unicode-scalar limit.

Android's 77 focused tests, iOS's 30 focused simulator tests and 18 Swift core
tests completed with zero failures and one existing skip in each suite. Device
metadata, signed artifacts and install logs are recorded under
`/private/tmp/youspeed-mobile-deployment-10050/`. Read-only inspection after
installation found no new real OCR attempt to quote. Android already uses
`SPOKEN_SPEED_AND_SIGNS`; the iPhone retains its existing sound-only default.
Spoken restriction text requires the combined speech setting on either phone.

## Panoramax server scope and deployment

The approved scope for Panoramax server OCR is numeric speed-limit
signs only: mapped maximum-speed signs or zone-start signs carrying a positive
numeric speed in km/h. OCR must use that eligible sign's lower supplementary
plate rectangle. Existing device text and source provenance must remain intact;
server results are separate, versioned derived evidence.

The owner explicitly requested production deployment on 16 October. The sibling
backend now implements native white-plate isolation, a bounded HF dispatcher,
immutable OCR results and current crop/source-sighting joins. The final-worker
[canary](https://huggingface.co/jobs/loffenauer/6ad22d585ccb47ba0f7b271f) read
`Mo-Fr\n630-1730h` from the actual 335×175 white plate in 1.09 seconds, plus
3.69 seconds model initialization. Its result passed real temporary PostgreSQL
import, crop/source-sighting joins and identical replay checks. The final combined
backend suite passed 54 tests.

Complete backend release `db27a048e8f147d7170a0bf61d906521122afb4b` is deployed on
live-eu, including collection intake. All nine running service images match the
release, and six public health/functional checks pass. The independently versioned
85fa static seed remains unchanged and read-only. Administrator preparation on
volz-db completed; migration 011 and the actual OCR role grants are verified.

Management activation at that revision completed after administrator authentication.
The first production job attempted one native 21×18 input. Its recovered result
is `failed` with `LocalEntryNotFoundError` and no transcription; the earlier
no-text characterization was inaccurate. Result import exposed an inherited
read-only Hugging Face cache path
and normal SDK snapshot symlinks rejected by the strict staging reader. The
completion helper stopped; the OCR schedule remains disabled. A follow-up release
adds a 48×32 native plate minimum, scans up to 2,000 candidates independently of
batch size, explicitly places the SDK caches on the writable result volume, and
accepts bounded SDK-managed result symlinks while keeping staging inputs strict.
The prior paid job retains its durable identity and must be imported without
resubmission before a new production canary. Current evidence is under
`/private/tmp/youspeed-server-ocr-deployment/`.

This server boundary does not change selected-group OCR on the phones, which
continues to support numeric signs and supported pictograms. Neither path
evaluates restriction applicability or changes the protected speed-reference
policy. Asynchronous server reads are stored on the backend; build 10050's trip
diagnostics record the phone's own reads and do not claim a server-result sync.

## Safe stop at owner request

Work stopped on16October before disconnect. Both phones remain onbuild10050.
Both backend hosts remain ondb27a048e8; the old completion unit is inactive and
its paid job is complete. OCR scheduling remains disabled. Recovery release
9ecbb6fbb6 is staged only. Before deploying it, the conservative white-plate
gate needs further correction: it rejected four visually readable examples
among20 independently hash-verified production crops. The incomplete local
prototype must not be deployed. Full resumable evidence and next steps are in
`/private/tmp/youspeed-server-ocr-deployment/SAFE_STOP_2026-10-16.md`.

## Resumed server deployment

On16October the plate gate was corrected and committed as backend release
`790a8f75fdc5e8b5aa2e546120f063e619a74019`. All87 focused backend, worker
and activation tests pass. Twenty source/crop hashes were independently verified;
the revised gate selects the four clearly readable white-plate examples, including
aligned stacks, without changing native pixels. Other sampled views defer. This
sample does not establish general accuracy. The exact candidate image reproduces
all20 selections as its non-root user.

The full release is staged and checksummed on both servers. Running servers
remain ondb27a048e8, with OCR scheduling disabled, pending interactive volz-db
sudo authentication. The reviewed bounded helper requires acceptance of the live
revision and a separate review of actual imported production text before cron
activation. Current persistent evidence, the Terminal launcher and next steps are
in `tmp/ocr-resume-2026-10-16/RESUME_CHECKPOINT.md` in this checkout.

## Activated runtime and legacy recovery

Both backend hosts now run release `790a8f75fdc5e8b5aa2e546120f063e619a74019`.
All nine live services and collection intake match. Public functional checks
pass; queue readiness recovered normally after startup, with existing failure
counts unchanged. The independent 85fa static seed and durable state are retained.
Management health reports `ok` and fresh controls.

The exact prior batch `b987f077-7d01-4f38-ac0a-768d673cc0f7` is imported. Its
actual outcome is failed with `LocalEntryNotFoundError`, rather than a no-text
OCR inference. Payload, original model/worker identity and crop/source-sighting
binding were independently verified. The recovery helper initially stopped
because it incorrectly required no-text; the corrected helper accepts the exact
immutable failed record without resubmission. Twenty local helper tests pass.
A fresh-cache production SDK 2.2 loader test can download the original private
manifest and native PNG; no persistent path or authorization problem was reproduced.
Scheduling remains disabled until a fresh production read is imported and reviewed.

## Completion deadline recovery

The original 45-minute administrator process expired at 17:26:09 UTC before
the corrected helper could restart. The next launch correctly refused to reset
that deadline. A later read-only audit found no fresh final-pipeline job or result;
OCR scheduling remains disabled. Both deployed backends remain healthy at 790a8f75fd.

An explicit renewal now audits the locked dispatcher and original false submission
intent, archives the expired run and receipts, and starts one new bounded window
only after interactive administrator authentication. It requires fresh live
acceptance and actual imported-text review before scheduling. It preserves the
old failed result and cannot renew after a fresh batch or submission intent.

## Separate deployment follow-up

The owner requested keeping the chats separate. The renewed completion never
received live acceptance during the later live deployment, and its deadline
passed at 20:34 CEST. At 21:10 CEST, direct SSH to both backend hosts times out,
although public API/queue health response bodies pass. Current deployment and
OCR scheduling state cannot be freshly attested until access returns.

A local immutable-source comparison confirms fourteen OCR-critical files are
identical between790a8f75fd and40a856c090, including worker, dispatcher, gate,
migration011 and deployment contracts. Country remapping changes source
fingerprints, so its completion still needs direct verification before a new
OCR batch. The old790 acceptance must not be used to attest a different release.

## Completed production deployment — 21:51 CEST

Both hosts are healthy on40a856c09038afdf637046158c9206a0515b105e. After source/image
attestation, canonical management activation, fresh live checks and actual
read review, the bounded15-minute OCR schedule is active. The completion unit
is inactive/dead and its crop-snapshot lock is released. The chats were kept
separate as requested. No speed-reference policy or applicability evaluation changed.

The production [HF job](https://huggingface.co/jobs/loffenauer/6ad27f12c662881452260959)
processed30 native plate regions. All30 raw results are durably joined to current
Panoramax crops/source sightings. No exact mobile association was available, so
all30 remain unresolved rather than attached to nearby phone observations.
Device build10050's own OCR remains in trip logs and consented events; this does
not add a server-result synchronization path into historical phone logs.

Five exact native-pixel text checks passed, including the requested
8e0020b0-b22b-490f-a287-cbcf4ad0b6c6 image: `Mo-Fr\n630-1730h`. Other verified
reads include `Lärmschutz\n22-6h`, `↑5km↑\nUnfall-\nstrecke`, `22-6h` and
`↑2,3km↑`. Input hashes, immutable payload hashes and current source bindings
were checked read-only for every result. PNG byte encoding differed from the
earlier diagnostic files, while all four shared examples had identical decoded pixels.

Recognition took299–1168ms per plate (median323ms;13.98s across30), with4.34s
one-time model initialization. Cloud/package provisioning is additional.
The41 helper safety tests pass; source/model/pipeline pins remain unchanged.

The batch is not an accuracy certification. A60×32 plate misread1730 as1720
and reversed line order; arrow-only artwork becameR. Two zone-start selections
included primaryZONE/artwork, with one red circle becomingO. Raw attempts and
confidence remain intact as derived evidence. Primary-zone exclusion and
small-text/symbol filtering remain known limitations of automatic collection.
Full evidence is in `tmp/ocr-followup-2026-10-16/deployment-completed-proof.json`
and neighboring quality/native-input proofs. The prior failed legacy job was
preserved without resubmission.


## App plate OCR rollout — 17 October 2026, build 10051

Both apps now use matching native plate-frame detection, primary-artwork and
symbol rejection, numeric agreement checks and a missing-upper-ink-row check.
Open-bottom plates abstain because a cut-off clause can change the restriction.
Native diacritics actually read by an engine are retained when interpolation only
loses that mark; no characters are inserted from expected text. Vision uses its
accurate recognizer; Android retains the bundled Latin ML Kit recognizer. Both
perform at most two recognition passes per admitted frame and keep the existing
six-attempt, larger-view retry budget. OCR still follows the selected sign group,
including pictograms. Restriction applicability evaluation remains disabled.

The same 32 public Panoramax source crops are pinned by SHA-256 in
`tests/fixtures/tsr-ocr-32/manifest.json`. They are resources of the XCTest and
Android instrumentation targets only. Production app contents were inspected
and contain neither these fixtures nor test bundles. Expected labels are used
only by assertions, never as recognition hints.

| Simulator, real local OCR engine | Old lower-half exact reads | Updated exact accepted reads | Abstentions | Incorrect accepted reads |
| --- | ---: | ---: | ---: | ---: |
| iPhone 17 Pro, iOS 26.5, Vision | 12 | 20 | 12 | 0 |
| Pixel API 36, bundled ML Kit | 18 | 20 | 12 | 0 |

The corpus contains 28 expected readable text cases, three non-text false
positives and one ambiguous small-text case. Both clients recover the two
reported `22–6 h` plates and abstain on all four negative/ambiguous cases. Eight
other text cases abstain rather than supply uncertain or partial text. In
particular the app-sized `bei Nässe` crop cuts off its second line; it cannot
reproduce the complete server plate from pixels it does not have. Android also
abstains when the distance row on a stacked plate is omitted. These are measured
corpus results, not a guarantee of road-driving accuracy. Exact comparison ignores
case, whitespace and punctuation, while retaining letters, digits and diacritics.
Both clients selected identical native rectangles on all 32 inputs.

End-to-end attempt wall times in this simulator run (including detection and both
passes) were iPhone median 357 ms / p95 991 ms / maximum 1,051 ms and Android
median 39 ms / p95 92 ms / maximum 101 ms. These are debug simulator timings on
this Mac, partly concurrent with builds; they do not predict physical handset
latency. Earlier build-10049 handset measurements above used the older pipeline.

Validation: 51 focused XCTest tests, no failures, one optional private-fixture
skip; 706 Android JVM tests, no failures, one existing skip; one Android
instrumentation test exercising all 32 crops through source-independent runtime
crop copying, no failures. The corpus assertions reject every incorrect accepted
read, require both reported plates, reject false positives/clipped clauses and
retain at least 18 accepted reads. Tests also cover rejected raw text in consent
records, speech/presentation exclusion, numeric disagreement, diacritics, complete
clauses, track lifetime and disabled applicability behavior.

Build 10051 was installed and launched on the iPhone 17 Pro simulator
`E6D05F95-EEB0-4DA4-B60D-D56271088A71` (`de.youspeed.SpeedConsumer`) and Pixel API
36 emulator `emulator-5554` (`de.youspeed.android.debug`). Both reached onboarding;
this was a startup smoke check, not a simulated road trip. The user selected
simulators only; physical phones were not updated. Raw per-crop results, timings,
fixture hashes, test logs, artifact hashes and deployment evidence are in
`tmp/app-ocr-improvement-2026-10-17/`.

Reproduce with `TrafficSignPlateRegressionTests` in the `SpeedConsumer` XCTest
scheme and `TrafficSignPlateRegressionTest` in Android instrumentation. Android
instrumentation must use `-PyouspeedIsolatedTests=true`; the normal debug package
is for the installed app. iPhone tests use `YOUSPEED_TEST_BUNDLE_SUFFIX=.TestHost`.


### Physical iPhone follow-up — 17 October 2026

After the user connected the phones and requested iPhone first, the iPhone 14 Pro
(iOS 26.6.2) passed the same 51 focused tests (one optional private-fixture skip,
zero failures). An initial Xcode launch resolved an obsolete production-app test
path; explicit `build-for-testing` followed by `test-without-building` used the
isolated `.TestHost` correctly. No application source changes were needed.

The physical 32-crop run produced 19 exact accepted reads, 13 abstentions and no
incorrect accepted reads, compared with 12 exact reads from the old lower-half
pipeline. Both reported `22–6 h` plates were recovered and all four
negative/ambiguous cases abstained. Compared with the simulator, one additional
arrow/distance case (`d33dceeb…`) abstained on numeric disagreement (`150 m 1`).
Attempt times were median 36 ms, p95 173 ms and maximum 296 ms; these exclude
primary detection/tracking time and are not road-driving latency measurements.

The signed production bundle `de.youspeed.SpeedConsumer`, version 1.4 build 10051,
was installed in place and launched. Installed device metadata confirmed 10051;
QuickTime's iPhone screen preview confirmed the existing driving screen and map
were available. The temporary isolated test app was removed after collecting its
results. Restriction evaluation remains disabled. Evidence:
`tmp/app-ocr-improvement-2026-10-17/iphone14pro-32-results.json`,
`iphone14pro-validation.json`, `iphone-physical-tests-retry.log` and
`iphone-physical-deployment.log` in the same folder.


### Physical Android follow-up — 17 October 2026

After completing the iPhone, the attached Moto g86 5G (Android 16) passed the
same 32-crop instrumentation test through the real bundled ML Kit engine and
source-independent runtime crop copying. It produced 20 exact accepted reads,
12 abstentions and no incorrect accepted reads, compared with 18 exact old
lower-half reads. Both reported plates were recovered; the false positives and
ambiguous tiny text abstained. Native plate rectangles matched the simulator on
all 32 cases. Median attempt time was 75 ms, p95 172 ms and maximum 198 ms.

The normal `de.youspeed.android.debug` app was updated in place to version
1.4-debug / code 10051 and launched. Package metadata and the foreground activity
confirmed the installation. The existing startup prompt reports more than
100 MB of saved logs; no logs were deleted. The phone subsequently auto-locked
while opening Android Studio's device preview, so the remaining manual startup
step is to unlock it and choose **Logs behalten und fortfahren**. This does not
block the verified OCR regression or installation. Both temporary test packages
created for this run were removed after collecting results. Restriction evaluation
remains disabled.

Evidence is in `tmp/app-ocr-improvement-2026-10-17/`: `motog86-32-results.json`,
`motog86-validation.json`, `android-physical-32-run.log`,
`android-physical-deployment.log`, `android-physical-installed-package.txt` and
`deployment-artifacts.json`. Phone measurements replace simulator timings when
assessing this fixture workload; neither is a measured road-driving success rate.
