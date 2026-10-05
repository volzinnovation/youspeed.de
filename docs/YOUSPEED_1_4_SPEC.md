# YouSpeed 1.4 app specification

Status: implementation proposal, revised 4 October 2026. This document owns the
iPhone and Android requirements for version 1.4: controls, local capture and
state, evidence schemas, durable buffered uploads, privacy actions and future
access behavior. Released builds do not gain these features from this document. Branch implementation progress and acceptance evidence are recorded in [YOUSPEED_1_4_APP_IMPLEMENTATION.md](YOUSPEED_1_4_APP_IMPLEMENTATION.md).

The separate [server specification](https://github.com/volzinnovation/Woladen.de-analytics/blob/main/docs/youspeed/YOUSPEED_1_4_SERVER_SPEC.md)
owns intake, archives, processing, analytics, retention and deployment. Its local
checkout is [YOUSPEED_1_4_SERVER_SPEC.md](../../Woladen.de-analytics/docs/youspeed/YOUSPEED_1_4_SERVER_SPEC.md).
Both documents must agree on the versioned mobile API and shared fixtures before
implementation. Neither authorizes deployment or publication.

## Confirmed scope and implementation boundary

The owner requests global sign collection attributed to a random installation
UUID without a YouSpeed account; class, GPS, time and original model scores;
automatic and manual observations; corrections including Wrong/Falsch; durable
offline buffering; a Panoramax recognized-sign capture setting and gallery
filter; optional downward-expanded sign crops for server-side online LLM
interpretation; and reviewed bundle enrichment or proposed OSM contributions.
Metadata collection and on-device TSR are on by default in the disclosed
contribution configuration. Future normal app access is funded by payment or
sufficient qualifying contributions; paid access permits collection and TSR to
remain off. Prices, qualification quotas and grace durations are not approved.

Global intake is not a promise of global model coverage. Preserve unknown
country, language, units and classes; report unavailable models separately.
Do not restrict admission to Germany or fabricate national sign mappings.

iPhone remains the behavioral reference. Android provides equivalent settings,
defaults, outputs, queue states, corrections and important runtime states, with
documented OS limitations. Both apps consume the shared official pictogram bytes
in [shared/tsr/sign-pictograms/](../shared/tsr/sign-pictograms/); numeric
speed-limit presentation remains the existing schematic exception.

Add an independent encounter observer after recognition/tracking and before
speed-applicability filtering. It sees non-speed signs and rejected or unknown
applicability without changing model thresholds, passage finalizers, camera
ownership or existing local corrections. Actionable speed passages and the local
speed-observation database cannot substitute for this observer.

The [protected speed-reference policy](../shared/speed-limit-reference/AGENTS.md)
and its Swift/Kotlin interpreter semantics remain unchanged. No upload response,
LLM output, contribution credit or access decision changes an active speed
reference. Applying a new restriction overlay to speed selection requires its
own explicit owner command and version/approval-lock process. Developer
state-machine diagrams stay in developer documentation.

The contribution channel is one-way: the app sends buffered evidence to the
server. It does not download observations, other installations' evidence or
the server sign catalog, and does not reconcile an observation database back
onto devices. Acknowledgments, limits, deletion progress and future access
receipts are control responses. Existing separate offline road/model bundle
downloads retain their own contract; reviewed enrichment may enter a future
published bundle, never an observation-return feed.

## Current behavior, installation and migration

Current source defaults TSR and independent TSR off
([Swift defaults](../iphone/SpeedConsumerApp/DriveSessionViewModel.swift),
[Android defaults](../android/app/src/main/java/de/youspeed/android/alpha/ConsumerSessionController.kt)).
The existing StoreKit use requests app ratings; neither app implements the
proposed paid entitlement flow. Existing ordinary recognition frames, local
observations and voice audio are not automatically contributed.

Generate one cryptographically random UUIDv4 using the platform system random
source at first app initialization, before onboarding at the earliest practical
point, and atomically persist it in app-private storage excluded from backup.
Local initialization requires no contribution opt-in or separate identifier
permission. It grants no camera, location, network or processor permission.
The UUID identifies an installation, not a person, physical phone, IMEI,
advertising ID, vendor identifier or hardware fingerprint.

Normal launches and updates retain the UUID. A genuine reinstall or restored
data without the installation marker initializes a new UUID; orphaned queued
data from another installation is not relabeled. Do not use a surviving iOS
Keychain entry to reconnect a fresh installation silently. Test backup/device
migration on both platforms. Copied app state can share an ID.

There is no installation registration, device key, challenge, proof of
possession, installation bearer token or ownership validation. Send the UUID
directly as attribution in the API envelope. It is not a secret or authenticated
identity. The server cannot establish that a submitter owns it; anyone who knows
it can submit or request deletion under it. Analytics say distinct
installations, not unique people or guaranteed distinct hardware. No YouSpeed
account, password, email or third-party sign-in is required.

Retain the UUID after contribution shutdown or server deletion. Do not provide
identity reset/rotation to avoid a deletion barrier. Use a separate random
collection-session ID for each drive; do not upload the shared recorder session
ID. Service/processor credentials and independently verified platform purchases
remain separate concerns and do not become device keys.

Fresh-install 1.4 metadata contribution and TSR preferences default on.
Upgrade preserves explicit off preferences and denied permissions. Revised
contribution authorization is required before sending new data; do not
retroactively upload old local observations or logs. An update or preselected
switch is not authorization. TSR-on does not silently enable independent
camera mode, Dashcam, optional crops, external processing or Panoramax upload.
Preserve their existing defaults unless separately approved. Purchase/restore
preserves privacy preferences.

## First camera-use authorization and permissions

Tie contribution opt-in to the first camera/TSR-use flow, not UUID creation.
The first-use setup explains on-device recognition and separately discloses
which sign metadata, installation UUID, GPS/time and model evidence go to
live-eu.woladen.de, for what purpose and retention/deletion terms. Obtain an
affirmative contribution decision before creating/uploading contribution
records. The native camera/location dialogs are still required for sensor use;
an OS camera grant alone does not authorize server uploads.

Offer an ordinary product choice to start TSR with metadata contribution, use
local TSR without contribution, or cancel/defer. Choosing local TSR disables
new contribution for the current session; it persists across sessions only when
Don't ask again is selected. The default cannot override that decision. Before
the future commercial gate is enabled, declining contribution does not restrict
local TSR; the future
paid route permits local camera/TSR without required contribution. Crops and
online third-party AI each retain separate affirmative choices, initially off.
The product consent stage and native OS permission prompt are distinct within
the same first-camera-use flow. Do not imitate an OS alert; if an OS permission
pre-alert is used, follow its Continue/Next convention.
[Apple permission guidance](https://developer.apple.com/design/human-interface-guidelines/privacy/).

A refused/revoked permission is honored; show denied/unavailable rather than
claiming that the default-on camera is running. Contribution capture occurs
only while an authorized drive/camera session is active; no background or
unrelated collection follows from a local identifier or a metadata preference.
Manual metadata recording still requires contribution authorization.
Existing app inactivity, thermal, camera/runtime and stationary speech-permission
checks remain authoritative. Settings permit accessible withdrawal at any time.

### Once-per-session prompt and Don't ask again

The owner's requested contribution consent UI includes an explicitly selectable,
initially unchecked **Don't ask again** checkbox. The affirmative contribution
and local-TSR-without-contribution choices remain clear. The checkbox changes
how long the selected decision is remembered; checking it alone, cancelling or
dismissing the sheet never grants consent. This is the app's contribution choice,
not an extra checkbox added to the native OS permission dialog.

Without the checkbox, acceptance or refusal applies to the current camera/drive
session only. Show the automatic contribution prompt at most once in that
session, even after refusal, cancellation or dismissal. A cancelled/dismissed
prompt grants nothing and creates/uploads no contribution evidence from that
session. At the next genuine session, offer the choice again.

With the checkbox, persist either the selected acceptance or refusal across
sessions. Remembered acceptance applies only to its disclosed scope/version
and still requires current OS permissions and independently authorized optional
media/processor use. Remembered refusal keeps contribution off and suppresses
automatic prompts until the user explicitly changes it in contribution settings.
Do not turn a remembered refusal into an invitation repeated on every launch.
Withdrawal immediately invalidates remembered acceptance and honors the existing
off/cancellation/cleanup behavior.

Use a stable local consent-session marker for the existing camera/drive run,
allocated on first deliberate camera-use entry before a drive necessarily
starts. Persist whether its prompt was shown before presenting it. Foreground
resumption, temporary camera interruption, thermal pause, retry or process
recovery of that run retains the marker and cannot re-prompt. If first-use entry
is refused or cancelled before a drive starts, its marker prevents a prompt
loop during that entry/recovery; a later genuine user-initiated new camera/drive
start creates a new session. Backgrounding alone never starts one.
This local bookkeeping is separate from the protected driving policy and does
not create/upload a contribution-session record without authorization.

Session-only acceptance authorizes collection during that session and delayed
buffered delivery of its saved evidence after the drive is inactive. Session end
prevents new collection under that acceptance, rather than silently revoking
already authorized pending uploads. A session-only refusal/cancellation creates
no new evidence in that session and does not withdraw earlier authorized buffered
evidence. Settings Off is a persistent withdrawal, independent of the checkbox,
that cancels delivery and clears pending private evidence; it remains off until
explicitly changed. Delete my observations also cancels/clears as specified.
Capture each event's applicable authorization snapshot before persistence.

Within existing contribution settings, show the current decision and whether
it is remembered; allow changing/withdrawing it or forgetting its remembered
state to restore future session prompts. Forgetting does not grant permission.
Do not automatically reopen a sheet already shown in the current session;
explicitly opening settings remains possible. A material purpose, recipient or
data-scope/disclosure change invalidates affected remembered acceptance. Notify
the user and require a fresh targeted decision at camera use before changed-scope
collection; if this session already showed the prompt, defer automatic re-prompt
until the next session or explicit settings review. A remembered refusal stays
off without renewed prompts merely because the disclosure changed.

## Controls, defaults and status

The same controls and state meanings ship in both apps and supported UI
languages. Defaults other than confirmed metadata/TSR preferences are proposals
to validate before release.

| Control or display | Requirement |
| --- | --- |
| Contribute sign observations and corrections | On by default after camera-use disclosure/authorization; session-only or explicitly remembered choice governs. Existing settings allow changing/forgetting the remembered choice. Authorized evidence is buffered and delivered automatically. Off always takes effect immediately. |
| Traffic-sign recognition | On by default after required permissions; retain unavailable, denied, thermal-paused and interrupted states. Independent of contribution permission. |
| Contribute sign crops | Separate opt-in, initially off; explains bounded image segments, location/time, destination and retention. Requires metadata contribution. |
| Allow online vision-LLM processing | Separate opt-in, initially off; identifies configured processor, purpose and retention/transfer terms. Requires crop contribution. |
| Capture a sign manually | Explicit user-sourced evidence without a detector hit; detailed classification/box editing occurs during safe review. |
| Panoramax: Capture recognized traffic signs only | Separate future-capture setting, initially off; existing distance/time behavior remains when off. |
| Panoramax: Show traffic-sign captures only | Gallery visibility filter, initially off; no approval, exclusion or deletion of hidden originals. |
| Automatic upload connectivity | Upload whenever internet is available, including metered/mobile connections and while the camera is active. No separate network or camera-idle toggle. |
| Buffered upload status | Pending count/bytes/oldest age, last durable acceptance, waiting reason, rejected/lost count and deletion progress. Accepted is separate from analytics/credit. |
| Delete my observations | Always available; clears pending private evidence, pauses contribution, requests deletion directly by UUID and shows progress. UUID retained. |
| Future access and Restore purchases | Paid/contribution/grace state and verified progress; purchase/restore and privacy actions remain available when ordinary use is restricted. |

Buffered upload scheduling belongs to the contribution contract, with no
separate toggle or manual send button. Show waiting reasons and deliver when
conditions are satisfied. A pending-data clearing action exists only in
developer diagnostics at the same level as log clearing, not ordinary user
settings; it reports unsent-data loss and does not claim server deletion.
Contribution off and Delete my observations perform their necessary cleanup
directly.

Turning contribution off atomically closes admission, cancels private upload
work, invalidates callbacks and removes pending private observations,
corrections, crops and manual working images. Accepted data may remain until
server deletion. It does not silently disable local TSR or modify approved
Panoramax batches. Turning TSR off does not grant or revoke media permissions.

Turning crops off deletes unuploaded private crops/working images and prevents
new media dispatch; preserve authorized metadata and append unavailable-media
status instead of rewriting a sighting. Turning processor permission off
immediately stops local dispatch and durably sends the withdrawal control.
Show pending server propagation or already dispatched processing honestly.

Waiting reasons distinguish permission required/denied, unsupported model,
inactive app, drive active/finalizing, costly network, offline, backoff, server
unavailable, schema update required, queue/storage failure, media expired,
processor withdrawal pending and deletion in progress. Preference, authorized
capture, local save and server acceptance are distinct states.

## Encounter lifecycle and observation payload

A frame detection is transient model output. A sighting is a consolidated
encounter with one visual sign panel, or a labeled manual observation. A
physical sign is a server hypothesis, not an app-generated rounded GPS/class
key. Panels in one assembly have separate sightings and an assembly link.

Proposed observer parameters: persist a provisional encounter after two analyzed
detections spanning at least 100 ms; checkpoint bounded best evidence at most
once per second; finalize after 2 seconds without detection, clean drive stop
or recovered interruption. These collection parameters require fixtures/field
validation and do not change recognition or speed thresholds. Missing
inference/thermal pause/shutdown are interruptions. Optional single detections
are `single_frame_uncertain`, not confirmed observations.

Allocate a UUIDv4 event ID before provisional persistence. Recovery retains it
and finalizes once as interrupted; retry/rebatching never creates another
identity. Track fragmentation remains traceable; do not globally suppress return
journeys/opposite carriageways by class/radius. Disk work runs outside the camera
thread with bounded queues and visible failures.

The additive `traffic-sign-sighting-v1` contract contains:

| Field group | Meaning and nullability |
| --- | --- |
| Identity | Schema/event/observer versions, collection-session ID, app platform/version/build, source kind detector or manual capture. Envelope carries installation UUID, public collection epoch and contribution-authorization scope/version claim. |
| Time | First/last seen UTC, representative frame UTC, duration from monotonic time, clock quality, GNSS fix UTC/alignment. Server assigns receipt time. |
| Position | Optional WGS84 vehicle latitude/longitude, horizontal accuracy metres, source/course/accuracy and alignment method. Sign position null unless independently estimated with method/uncertainty. |
| Classification | Country or unknown, original label, mapped national code/family, typed value/unit, panel role, mapping revision/digest, bounded alternatives and unknown reason. |
| Scores | Separate original detector/classifier scores and declared domains/ranges. Calibrated confidence nullable with calibration lineage. Track support separately named. |
| Model | Pack ID/version/digest, invoked component role/artifact SHA-256/preprocessing/calibration lineage. Manual evidence declares no model and null scores. |
| Evidence | Track/assembly IDs where present, analyzed-frame count, finalization reason, quality flags and optional full-upright normalized sign box. |
| Road context | Optional road ID, bundle revision, matching quality/travel direction; absence does not prevent saving. Vehicle course is not sign-face orientation. |
| Media | Empty array or typed crop references with explicit pending/available/expired state. No image bytes or device file paths in JSON. |

Unlocated sightings remain valid. Larger uncertainty, stale fixes and unknown
clocks retain flags, not invented positions or long-gap interpolation. Proposed
spatial-quality limits are horizontal accuracy at most 25 m and frame/fix
alignment within 1 second; quality labels do not block uncertain/manual
evidence. Nonfinite scores, invalid coordinates and negative accuracy fail
validation. UTC clock skew remains explicit; monotonic ordering is separate.

Use shared national catalogs/mappings. Ordinary 50 and zone-50 are different,
with value/unit separate from class. Background/`bad:*` outputs are bounded
quality counters, not sign sightings. Supplementary recognition distinguishes
unreadable, not observed and not supported; do not infer absence from an
unsupported model.

## Corrections and voice ownership

Preserve existing manual spoken-speed capture and immediate numeric-camera
dismissal. Wrong/Falsch currently clears local camera evidence and restores the
underlying road/local limit; it does not assert that a physical sign is absent.
The observer records a collection amendment without changing that effect.

Reuse the on-device recognizer/audio arbitration through one dispatcher.
No parallel microphone listener or cloud speech fallback. Preserve whole-command
matching DE `falsch`, EN `wrong`, FR `faux`, NL `fout`.
Existing numeric timing remains maximum start delay 3 seconds, listening
4 seconds and result drain 0.35 seconds. Repeated frames/passage commitment/
camera restart do not reopen the same physical sign within the drive. Retain
token/generation validation and stationary permission preparation.

General sign correction is new behavior. Proposed association window is
4 seconds after encounter presentation, separate from numeric timing. Freeze
the sighting/panel ID, original attribution, presentation token and snapshot
at attempt start, before local dismissal or a later sign replaces it. A late
callback cannot target the currently nearest sign. Numeric local dismissal
retains existing authoritative-reference checks; the amendment independently
retains its frozen original target.

Bare Wrong/Falsch yields `unspecified_wrong`, with no replacement invented.
Other proposed intents: `not_a_sign`, `wrong_class`, `wrong_value`,
`wrong_location`, `wrong_applicability`,
`supplementary_condition_missing`, `retract_correction`.
Road/lane disagreement is distinct from false positive. Ambiguity retains
`target_ambiguous` and bounded local candidate IDs for post-drive selection;
no eligible target stays unresolved with an honest acknowledgment.

The correction schema carries correction UUID/time, input modality/locale,
normalized intent, frozen target type/ID, association evidence/status, optional
replacement fields/crop and retracted correction ID. No audio/raw transcript.
Edits/undo append records; original scores/evidence remain unchanged.
Corrections may arrive before targets and receive durable
`target_resolution=pending`; missing targets are not retargeted.
This channel has no cross-installation evidence browsing/feedback UI.

## Manual sign capture

Provide a lightweight explicit action integrated with existing camera ownership.
It works without a detector hit, AR, supported pack, road match, speed passage
or GPS. Unavailable camera/denied permission can still produce explicitly
unclassified metadata-only evidence with `media_unavailable`, when the user
chooses that authorized action; show what was saved.

An explicit manual action can save one protected local working frame under
disclosed OS/app capture permission, proposed maximum 24 hours, for post-drive
box selection. It does not authorize private upload, external processing or
Panoramax publication. Remove the working frame after crop finalization,
cancellation, expiry or crop-permission withdrawal. Never upload a full working
frame to the private service.

Manual sightings use `manual_capture`, camera time and optional vehicle fix;
scores/model/track are null. Safe review provides upright box and optional
class/value/condition edits. Private manual crop upload needs crop permission
and a user-confirmed box; optional model/LLM results are separate derived
evidence. An explicit request to retain an original in Panoramax uses its own
gallery/review/retention contract.

## Panoramax recognized-sign capture

`Capture recognized traffic signs only` changes future Panoramax stills.
Off preserves distance/time cadence. On allows stable observer candidates to
trigger one representative still per encounter/assembly, including non-speed
and supported uncertain signs; no active numeric override required. Proposed
stability is two analyzed frames over 100 ms with admitted pack-specific score
rules and a 2-second global minimum interval. Shadow/evaluation evidence retains
its label and needs an explicit admitted capture policy. Background is ineligible.

Choose the clearest representative within bounded resources. Deduplicate by
track/encounter, not class alone; multiple signs retain separate boxes. Missing
TSR yields a waiting reason, not silent continuous capture under this setting.
Manual capture remains explicit. Existing storage caps/errors do not authorize
discarding user images or replacing approved/uploaded originals.

`Show traffic-sign captures only` filters by capture reason or linked evidence.
Indicate the active filter; clearing restores all originals. Hidden selection/
exclusion/approval is unchanged. No silent historical reclassification.

Preserve [the Panoramax post-drive gate](../shared/PanoramaxUploadProtocol.md):
inactive drive, reviewable batch, explicit inclusion, explicit batch approval
and valid separately connected Panoramax credentials. Drive stop, reconnect,
private contribution permission and sign-triggered capture never automatically
upload Panoramax originals. Its external account remains separate.

## Optional crop geometry and media ownership

Private crops and reviewed Panoramax originals have distinct permissions,
queues, retention and destinations. An actual-sign annotation on a Panoramax
original is not a private crop-upload contract. No public URL is created.

Use the exact analyzed frame or a separately validated spatial transform.
Nearest Panoramax still annotation within five seconds is insufficient for an
unverified small OCR crop. Map detector/user coordinates through rotation,
mirroring, resizing and calibration into the full upright source; honor existing
inference-left-crop remapping. Preview coordinates are not source pixels.

For `W × H`, outward-round supplied coordinates, clamp the original sign box
to image bounds and reject zero area. Resolved top-left-origin half-open box
`[x0,y0,x1,y1)` gives:

```text
w = x1 - x0
h = y1 - y0
requested_crop = [x0, y0, x1, y1 + h)
actual_crop    = [x0, y0, x1, min(H, y1 + h))
actual_width  = w
actual_height = min(2*h, H-y0)
```

Add one original sign-height downwards with the same width/top: no margin
above/beside and no synthetic missing pixels. For `640 × 330`, sign
`[120,200,200,280)` requests `[120,200,200,360)`, producing
`80 × 130` with 50 extra pixels below the original `80 × 80`.
Preserve both boxes; halving a clipped crop cannot recover the original.

Crop metadata includes UUID, target sighting/panel/assembly, source kind,
exact frame token/time/dimensions, original supplied coordinates, transform/
version, resolved sign/requested/actual crop boxes, extra-height/truncation,
orientation/redaction/encoding versions, optional upright-source pixel SHA-256,
encoded SHA-256/byte length and decoded dimensions. Missing source hash is null;
the full source need not be retained/uploaded. Define pixel hashing color
space/row layout in fixtures. Edited boxes create new crop/supersession records.

Use bounded JPEG/PNG with orientation applied; remove EXIF/XMP/GPS/device
identifiers from bytes. Location/time is in structured metadata. Privacy
preflight/redaction or review holds suspected people/plates/unrelated sensitive
text; cropping is not anonymization. Never invent removed/unreadable text.
Proposed bounds: 5 MiB encoded, 16 megapixels decoded. Provider resize is a
separately identified derivative with transform/hash, not silent geometry change.

Temporary write, flush, atomic rename and required directory synchronization
precede durable queue-reference commit. Missing referenced files fail visibly.
Keep one bounded best crop, not a stream; unavailable/expired optional media
does not block metadata. Server online LLM extraction uses a server-held key
absent from apps/bundles/events/logs. White supplementary text, temporary limits
and French lane arrows may remain unresolved; output never activates a limit.

## Durable buffers and automatic delivery

Dedicated SQLite queues use app-private storage excluded from backup. Commit
immutable finalized payload, UUID, semantic digest, collection epoch and pending
state atomically before displaying saved. Verify WAL/`synchronous=FULL` and
platform durability, migrations/corruption recovery. No camera-thread disk wait.

Proposed metadata/correction limits: 20,000 events or 50 MiB, whichever first,
30 days from local commit; reserve 1,000 events/5 MiB within totals for
corrections. Never evict deletion/permission-withdrawal controls. Crops:
separate 1 GiB/7-day local queue; manual working frames: maximum 24 hours.

At caps, transactionally evict oldest unleased ordinary pending sightings and
persist loss count/reason/time. Never evict owned in-flight requests; refuse
new data visibly if leased data exhausts capacity. Exhausted correction reserve
visibly refuses persistence. Crop overflow/expiry removes unleased bytes and
appends unavailable status, preserving sighting. Count spool/temporary bytes;
no unlimited memory fallback or false uploaded state.

States: `provisional → pending → leased → accepted`, plus
`retry_wait`, `quarantined`, `expired`, `cleared`.
Leases have expiry/generation; startup returns orphans to retry. Persist exact
request bytes before transport. Remove rows/spool only after durable accepted/
identical-duplicate reconciliation. Unknown/missing response IDs clear nothing.

After drive fully inactive, automatically attempt work on launch/resume,
eligible connectivity and best-effort OS opportunities. Deliver small batches
without waiting to fill; do not open camera/run inference to upload.
Proposed limits: 100 events/batch, 512 KiB uncompressed, 16 KiB/event, one
in-flight batch per UUID. Starting a drive cancels/suspends transfers and fences
callbacks; reconcile already accepted responses idempotently and start no
further private transfer until inactive.

Persistent exponential backoff/full jitter: proposed 5-second initial, 6-hour
cap, honoring longer Retry-After. Network changes cannot create parallel workers.
Privacy controls/corrections have priority; target arrival order is not assumed.

| Outcome | Client action |
| --- | --- |
| Loss/timeout/lost response | Retry unchanged IDs/content; acceptance may already have occurred. |
| Per-event accepted/duplicate | Atomically clear only acknowledged identical records. |
| Retry later/429/transient 5xx | Retain work, honor backoff/Retry-After. |
| 413 | Split into new batch IDs with same events; quarantine single oversized record. |
| Unsupported schema/permanent rejection | Quarantine affected events; valid siblings continue. |
| Changed content under same batch/event ID | Quarantine conflict, never hide it with a fresh event ID. |
| Old epoch 410 | Reject old work permanently; never relabel it into a newer epoch. |
| New epoch 409 while deletion pending | Keep contribution paused until active-data-removal acknowledgment. |
| Withdrawal/cancellation | Clear pending private data, invalidate callbacks; accepted data requires deletion. |
| Invalid control response/configuration | Pause visibly; no invented device-authentication refresh. |

iPhone uses file-backed background URLSession tasks, durable task mapping and
foreground delivery. Android uses unique bounded WorkManager work with network
constraints. Neither replaces SQLite. Force-quit/force-stop/OS constraints may
postpone delivery until resume; no guaranteed stopped-app flushing. Test network
cost/constraint adapters on supported versions and document OS differences.

## Mobile API and shared schemas

Proposed HTTPS base: `https://live-eu.woladen.de/youspeed/v1`.
Freeze schemas, endpoint names, digests, maximum sizes and examples jointly.
Contribution envelopes include installation UUID, `collection_epoch` initially
0, and `collection_authorization`: `scope`, `disclosure_version`, `decided_at`,
`consent_generation`, `state` and `origin=client_claim`. These are client claims,
not ownership proof; the server cannot verify who made that authorization.
The epoch orders deletion and is public, not a credential.
Session lifetime, the prompt-shown marker and Don't ask again are local consent
bookkeeping. They do not change the agreed collection_authorization fields or
create a server ownership-verification claim. Buffered events retain their
captured authorization snapshot across delayed delivery.

| Interface | App use |
| --- | --- |
| POST /sighting-batches | Immutable consolidated detector/manual evidence; durable per-event outcomes. |
| POST /correction-batches | Append-only correction/retraction, unresolved target allowed. |
| POST /media-uploads | Idempotent crop reservation by UUID/epoch/crop ID/digest/length; opaque handle. |
| PUT /media-uploads/{handle}/content | Bounded crop bytes and separate durable media acknowledgment. |
| POST /media-status-batches | Immutable unavailable/superseded/link status, no sighting rewrite. |
| POST /consent-events | Durable crop/processor permission generations and withdrawal. |
| POST /observation-deletions | Body installation_id, collection_epoch, deletion_request_id; returns deletion_id, operation_receipt, next_collection_epoch and deletion_pending. |
| POST /operation-status | Opaque receipt in body; returns operation counts/state only, including accepted/media/deletion progress; no observation/media/catalog download. |
| GET /capabilities | Schema versions/limits only; cannot enable sensors/consent/access gate. |
| Future access-policy/status/store-proof/entitlement interfaces | Bounded credit/access status and verified purchases; finalize for future release, no contribution-data download. |

Illustrative manual batch; synthetic IDs, not release data:

```json
{
  "schema_version": 1,
  "batch_id": "b467e55e-0f44-45fa-93db-0b0839c47228",
  "installation_id": "d3e3c09c-2fc6-4f05-9698-67b8c3c30212",
  "collection_epoch": 0,
  "collection_authorization": {
    "scope": "sign_metadata",
    "disclosure_version": "camera-contribution-1",
    "decided_at": "2026-10-04T09:55:00.000Z",
    "consent_generation": 1,
    "state": "granted",
    "origin": "client_claim"
  },
  "events": [{
    "schema_version": 1,
    "event_id": "15e77710-981b-4db4-9c65-a35b4b21b60a",
    "collection_session_id": "348e8edc-e5ae-45a8-a59b-b03f9c15c973",
    "observer_version": "sighting-observer-1",
    "source_kind": "manual_capture",
    "app": {"platform": "ios", "version": "1.4", "build": "example"},
    "first_seen_at": "2026-10-04T10:00:00.000Z",
    "last_seen_at": "2026-10-04T10:00:00.000Z",
    "representative_frame_at": "2026-10-04T10:00:00.000Z",
    "duration_ms": 0,
    "clock_quality": "device_unverified",
    "vehicle_position": null,
    "sign_position": null,
    "classification": {
      "country": null, "model_label": null, "canonical_code": null,
      "family": null, "value": null, "unit": null, "role": "unknown",
      "mapping_revision": null, "mapping_sha256": null,
      "alternatives": [], "unknown_reason": "manual_unclassified"
    },
    "scores": null,
    "model": null,
    "evidence": {
      "track_id": null, "assembly_id": null, "analyzed_frames": 0,
      "finalization_reason": "manual_action",
      "quality_flags": ["unlocated", "media_unavailable"]
    },
    "road_context": null,
    "media_refs": []
  }]
}
```

Detector fixtures include original detector/classifier scores and invoked
components with domains/calibration lineage. Null classifier score means not
invoked/unavailable, never zero; raw 0–1 scores are not probabilities.

ACK includes schema/batch/opaque operation receipt, time/durability/epoch and one
result per recoverable input: `accepted`, `duplicate`, bounded
`rejected` code, or `retry_later`. Acceptance is separate from analytics/
credit. Invalid envelopes cause no effects; partial-valid effects are explicit.
Frozen batch conflict returns 409. Lost responses retry exact bytes; receipt
status contains counts/state, not source observations. No receipt proves UUID
ownership.

Additive schemas cover sighting, correction, crop, media status, authorization/
permission event, deletion request/receipt, batch ACK/error and future access.
Canonical semantic JSON digests exclude delivery time/transport whitespace and
share cross-language number/null fixtures. Pin agreed hashes across repositories.
Existing recognition/passage and protected speed-policy bytes stay unchanged.

## Delete my observations and epoch barrier

No account/payment/device key/ownership proof is required. Before sending,
atomically pause contribution, fence callback/work generations, clear pending
private observations/corrections/crops/working frames, cancel transports and
persist a UUIDv4 deletion_request_id. Retain installation UUID/request/status
across restart. Offline deletion queues independently without re-enabling capture.

Server deletion atomically records the idempotent request, tombstones all epochs
through current, and advances the next accepted epoch. Repeating the same request
returns the same operation receipt/new epoch without advancing again. Uploads
accepted before that barrier fall within deletion; old-epoch retries after it
return 410. Next-epoch uploads return 409 while deletion is pending.

Ordinary uploads remain blocked until operation-status acknowledges active data
removed. Do not create contribution records in this gap. After acknowledgment,
later explicit contribution authorization may resume newly created evidence
under next_collection_epoch with the same UUID. Never relabel or resend old
queued content. Archive, backup/provider and derived-data removal may remain
pending; show separate progress and do not call active removal full completion.

Persist highest accepted epoch/receipt atomically; ignore stale progress/ACKs.
Lost deletion response retries the same request. No identity reset, secret
deletion credential or re-registration. Reinstall can lose the UUID needed to
name old data; no account/hardware recovery promise. Anyone knowing the UUID
can request deletion in this unverified model; epoch prevents retry resurrection,
not unauthorized attribution/deletion.

Deletion does not cancel a purchase or remove separately published Panoramax/
OSM contributions. Show these boundaries before separately authorized publication.

## Reviewed bundle and OSM boundary

No private observation/catalog/extracted-text return feed exists. Reviewed
server results may later enter a separately versioned/published offline bundle;
no online answer overrides local speed behavior. Current staging preserves raw/
conditional tags, but compact v3/v4 schemas/readers lack full conditional/
directional/lane evaluation. Extensions need deliberate shared contracts/parity.

A future reviewed restriction overlay preserves original OSM tags/revision/
attribution separately from YouSpeed evidence: stable restriction ID, original
text/language/unit, condition tree, jurisdiction, road/bundle binding, direction/
lane vector, valid-from/to/expiry, uncertainty, rights/provenance/review and
supersession/revocation. Readers preserve unknown predicates and expire temporary
records; never flatten conditional into unconditional maxspeed.

Lane order follows the specified travel direction; OSM forward/backward follows
way geometry. An image arrow alone does not establish current lane or turn
instruction. Informational display requires parity design; speed activation
requires separate protected-policy approval.

Preserve local spoken-maxspeed and reviewed OSC export. Proposals show fresh
source object/version and tag diff with conditional syntax/units/lane scope and
rights review. Final authenticated editor upload is explicit. Wrong/Falsch,
private observations and LLM output never automatically write OSM. No OSM account
is needed to contribute.

## Future pay-or-contribute access

Confirmed direction, disabled release gate: paid access permits contribution/
TSR off; unpaid normal use is intended to need sufficient qualifying metadata.
Off, denied permissions, deletion, help and purchase/restore/status remain
available without payment. Honor privacy actions immediately; any later
normal-use restriction starts only at an inactive-drive boundary after approved
notice/grace. Paid camera/TSR works without granting contribution-data access.

Independently verify native platform purchases and provide Restore purchases
without a YouSpeed account. Pending purchase, cancellation of renewal, validation
outage, expiry and confirmed refund/revocation are distinct. Reinstall can restore
an eligible purchase onto the new UUID without restoring old observations/
credit. Do not promise cross-store portability, invented device locks, prices
or product IDs.

Display separately accepted events, qualifying credit and catalog counts.
Credit is not frames/bytes/classifier confidence/novel signs/model agreement.
Proposed base unit is one bounded genuine metadata encounter with published
source weights/repeat/daily caps/window. Manual/unknown evidence has explicit
rules. Honest Wrong/Falsch/undo neither earns another base unit nor automatically
penalizes participation. Optional crops, LLM/Panoramax/OSM are never required
for ordinary credit. No incentives for extra driving or moving interactions.

Receive only bounded future credit/access summaries, not observations/catalog.
Show confirmed/pending units, requirement/window, assessment/policy version,
expiry/grace/review and exclusion reasons. UUID attribution does not establish
independent contributors; abuse/fairness limitations remain release decisions.

States: `gate_not_enabled`, `onboarding_grace`,
`contribution_pending`, `contribution_eligible`, `paid_active`,
`offline_grace`, `service_grace`, `action_needed_next_session`,
`restricted`. An authorized drive completes without access-related
interruption, blocking purchase UI, camera/audio seizure or speed-reference
change. Permission revocation still stops the sensor. Apply business restrictions
only after recording/finalization fully settles.

Approve initial earning, qualification-lag, sparse/unsupported coverage, offline,
service/store-validation, clock/reboot and policy-transition grace before
enforcement. Pending local evidence supports bounded provisional progress/grace,
not confirmed credit. OS/thermal/network/review delays are visible reasons,
not refusal/fraud. If service-signed access leases are adopted, their issuer keys
are independent of UUID attribution and require no installation signing key.
Preserve result/epoch watermarks and approved clock handling; unknown policy
does not enable enforcement and offline use is not promised indefinitely.

Fresh Apple-policy review: camera-linked opt-in improves context, but camera
permission does not authorize server sharing. Paid features must not depend on
collection permission; third-party AI needs explicit disclosure/permission.
GPS-qualified compulsory contribution still presents a release-policy conflict.
This first-use design is a product inference, not App Review approval. Keep
enforcement disabled until the actual commercial/privacy model, paid alternative,
restore and fairness/grace rules are reviewed and activation explicitly approved.
[Apple data collection](https://developer.apple.com/app-store/review/guidelines/#data-collection-and-storage),
[Apple data use](https://developer.apple.com/app-store/review/guidelines/#data-use-and-sharing),
[Apple location rules](https://developer.apple.com/app-store/review/guidelines/#location-services).
Google sensitive-data disclosure and EU consent feasibility also need review:
[Google User Data](https://support.google.com/googleplay/android-developer/answer/10144311),
[EDPB consent guidance](https://www.edpb.europa.eu/system/files/documents/files/file1/edpb_guidelines_202005_consent_en.pdf).
Any materially different commercial model needs an owner decision.

## Privacy wording and release declarations

Explain approximate vehicle GPS/time, original classification/scores, installation
attribution, destination/purpose, buffers, retention/deletion and UUID ownership
limitations at first camera use. No account is not anonymity. Local UUID creation
is separate from capture/sending and optional crop/processor decisions.

No full-frame stream/audio/arbitrary logs/device paths/continuous GPS trace/raw
transcript is uploaded. Operational diagnostics contain bounded counts/reasons/
schema/app versions/aggregate losses without UUID/location labels. Authorized
crop references/text use dedicated evidence contracts, not operational logs.
Processor withdrawal/deletion cannot undo a completed call; status is explicit.
Panoramax keeps separate public-upload disclosure.

Local-only UUID/location processing is not collection for Apple's labels;
persistent UUID/GPS/time server observations are collection. No account or image
is required for that classification. Review linkage and purposes rather than
assuming anonymity.
[Apple App Privacy details](https://developer.apple.com/app-store/app-privacy-details/).

Update localized in-app/public/store wording for the actual binary. Existing
1.3 drafts claiming TSR initially off/no automatic analytics cannot be reused
unchanged. Required contribution is not automatically optional because future
paid users may disable it. Permission denial/model coverage/offline statements
must match actual behavior.

## Required validation and implementation order

| Area | Required iPhone/Android evidence |
| --- | --- |
| Initialization/migration | UUID at first initialization with no own opt-in; update/reinstall/backup ownership; first-camera-use disclosure; fresh defaults and preserved explicit off/denial; no historical upload. |
| Consent sessions | At most one automatic prompt per session across resume/interruption/thermal/restart and pre-drive cancellation; unchecked accept/refusal applies to session, checked accept/refusal persists; checkbox alone/cancel grants nothing; remembered refusal stays off; settings change/forget and material-scope reauthorization; delayed authorized delivery versus explicit withdrawal. |
| Scope/policy | Speed/non-speed/unknown/unlocated/unsupported/unreadable fixtures; observer before applicability; protected bytes/semantics unchanged. |
| Correction | Frozen ID/token/ambiguous panels/late callback/repeat deduplication; unchanged local numeric dismissal; four languages/timings/arbitration; out-of-order target/undo. |
| Manual/crops | No detector/model/GPS; metadata-only failure; safe review/null scores; exact-frame/calibration/rotation/downward clipping/redaction/hash; working-frame expiry/no full upload. |
| Panoramax | Separate setting/filter, no hidden approval; representative deduplication/caps; explicit existing post-drive review/upload. |
| Queue/delivery | Crash at commit/send/response/ACK; duplicate/content conflict/split; limits/reserve/disk/expiry/corruption; costly/offline networks; one worker; force-stop/quit/resume; no manual upload-control UI. |
| Withdrawal/deletion | During-request cancellation, same UUID, epoch 0→next, 410 old/409 pending, lost response/restart/offline; active-removal gate, stale ACK/no relabeled old events. |
| Future access | Verified/pending/restore/refund; immediate unpaid privacy actions; approved offline/outage/review/clock grace; no drive interruption; no optional-media quota; gate off. |
| Bundle/OSM | Both readers preserve conditional/unknown/expiry/provenance; no policy change/automatic publication. |

Implementation order: freeze additive schemas/API/digest/epoch fixtures; build
observer/durable buffers without transport; integrate voice/manual/Panoramax/
crop settings using iPhone reference; add automatic delivery/deletion/OS
adapters and Android parity; validate disclosure/default migration; implement
future access in non-enforcing shadow mode. Bundle enrichment and future paid
enforcement retain their separate release gates.

Numeric observer/queue/media parameters above are proposals. Processor terms,
field-quality benchmarks, manual permissions/retention, network/privacy copy,
purchase products/restore and credit/grace fairness remain release decisions.
Saving this specification changes no implementation, policy, collection
authorization, purchase, service, deployment or publication.
