# YouSpeed 1.4 app specification

Status: implementation proposal, revised 6 October 2026. This document owns the
iPhone and Android requirements for version 1.4: controls, local capture and
state, evidence schemas, bounded best-effort uploads, privacy actions and future
access behavior. Released builds do not gain these features from this document. Branch implementation progress and acceptance evidence are recorded in [YOUSPEED_1_4_APP_IMPLEMENTATION.md](YOUSPEED_1_4_APP_IMPLEMENTATION.md).

The separate [server specification](https://github.com/volzinnovation/Woladen.de-analytics/blob/main/docs/youspeed/YOUSPEED_1_4_SERVER_SPEC.md)
owns intake, archives, processing, analytics, retention and deployment. Its local
checkout is [YOUSPEED_1_4_SERVER_SPEC.md](../../Woladen.de-analytics/docs/youspeed/YOUSPEED_1_4_SERVER_SPEC.md).
Both documents must agree on the versioned mobile API and shared fixtures before
implementation. Neither authorizes deployment or publication.

## Confirmed scope and implementation boundary

The owner requests global sign collection attributed to a random installation
UUID without a YouSpeed account; class, GPS, time and original model scores;
automatic observations; corrections including Wrong/Falsch; bounded
offline buffering; a Panoramax recognized-sign capture setting and gallery
filter; automatic downward-expanded sign crops for server-side online LLM
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
camera mode, Dashcam, external processing or Panoramax upload. Sign sharing
includes every automatically captured crop, as explicitly directed by the owner
on 5 October 2026.
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
paid route permits local camera/TSR without required contribution. Sign sharing
includes automatic crop upload without a separate choice. Online third-party AI
retains its separate affirmative choice, initially off.
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
buffered delivery of its saved evidence whenever internet is available. Session end
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
| Automatic sign photos | Every captured crop accompanies sign sharing. No separate toggle, consent prompt, approval or manual entry. Explain destination, location/time and offline retention in the sharing disclosure. |
| Allow online vision-LLM processing | Separate opt-in, initially off; identifies configured processor, purpose and retention/transfer terms. Requires crop contribution. |
| Panoramax: Capture recognized traffic signs only | Separate future-capture setting, initially off; existing distance/time behavior remains when off. |
| Panoramax: Show traffic-sign captures only | Gallery visibility filter, initially off; no approval, exclusion or deletion of hidden originals. |
| Automatic upload connectivity | Upload whenever internet is available, including metered/mobile connections and while the camera is active. No separate network or camera-idle toggle. |
| Buffered upload status | Pending count/bytes/oldest age, last send, waiting reason, dropped count and deletion progress. Sent is separate from durable storage, analytics and credit. |
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
corrections and crops. Accepted data may remain until
server deletion. It does not silently disable local TSR or modify approved
Panoramax batches. Turning TSR off does not grant or revoke media permissions.

There is no separate crop-off setting. Turning processor permission off
immediately stops local dispatch and durably sends the withdrawal control.
Show pending server propagation or already dispatched processing honestly.

Waiting reasons distinguish permission required/denied, unsupported model,
inactive app, offline, backoff, server
unavailable, schema update required, queue/storage failure, media expired,
processor withdrawal pending and deletion in progress. Preference, authorized
capture, local save and server acceptance are distinct states.

## Encounter lifecycle and observation payload

A frame detection is transient model output. A sighting is a consolidated
encounter with one visual sign panel. A
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
Corrections may arrive before targets; background processing retains unresolved
targets as pending rather than retargeting them.
This channel has no cross-installation evidence browsing/feedback UI.

## Automatic sign capture

Ordinary detections create sightings and their exact representative crops
automatically. No manual entry, box selection or review action is offered.
The app does not create manual observations.

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

## Automatic crop geometry and media ownership

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
identifiers from bytes. Location/time is in structured metadata. The product owner requires automatic upload of every captured crop, with no
separate crop setting, consent prompt, manual entry or user review (5 October
2026). The capture encoder applies geometry and strips embedded metadata. Queue
insertion trusts its output without decoding or hashing it again; this does
not assert face/plate anonymization or user review.
Never invent removed/unreadable text.
Proposed bounds: 5 MiB encoded, 16 megapixels decoded. Provider resize is a
separately identified derivative with transform/hash, not silent geometry change.

Temporary write, flush, atomic rename and required directory synchronization
precede durable queue-reference commit. Missing referenced files fail visibly.
Keep one bounded best crop, not a stream; unavailable/expired optional media
does not block metadata. Server online LLM extraction uses a server-held key
absent from apps/bundles/events/logs. White supplementary text, temporary limits
and French lane arrows may remain unresolved; output never activates a limit.

## Bounded buffers and fast automatic delivery

The owner replaced lossless contribution delivery with best-effort upload on
6 October 2026. [The shared v2 upload contract](../shared/tsr/collection-upload-v2.md)
is authoritative for both clients and the server.

Keep collection off the camera thread. Preserve existing bounded local queues
and retention limits, but allow ordinary signs/crops to be lost. Each item gets
at most three attempts. A successful HTTP status is enough to release local
bytes; it is not a durable-storage or analytics guarantee. Respect temporary
server retry deadlines directly and discard permanent failures promptly.

Every automatically captured crop travels in one request with its metadata.
Remove reservations, upload handles, per-crop receipt validation/polling,
client-side linked-status requests and repeated encoded-image hash checks.
Transfer bounded groups of eight crops; sightings/corrections remain batches
of up to 100. Cache capabilities for five minutes. Use available internet,
including cellular, while recognition continues. Both platforms share this
behavior. Sharing withdrawal and deletion continue to clear/cancel private work.

## Mobile API and shared schemas

Use the v2 single-request endpoints and empty HTTP 204 success described in the
shared contract. The server accepts ordinary evidence without comprehensive
per-event/provenance/geometry checks. It stores opaque images and links them
internally, then interprets images and calculates archive identities in
background work. The ordinary capture burst limit is 120 requests per minute.

The existing evidence fields remain available. The old ordinary upload routes,
reservation protocol and client fallback are removed from this v1.4 development
branch. Permission/deletion controls, bundle activation and speed-reference
semantics retain their respective existing contracts.

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
