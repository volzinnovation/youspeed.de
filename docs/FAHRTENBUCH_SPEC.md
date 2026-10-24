# Fahrtenbuch — automatic trips, app counters and media exploration

Status: product and implementation specification; partial runtime implementation
is tracked in [FAHRTENBUCH_IMPLEMENTATION.md](FAHRTENBUCH_IMPLEMENTATION.md).
Date: 22 October 2026. Applies equally to iPhone and Android.

## 1. Product decisions and promise

YouSpeed records each driving use of the app as a private, local trip containing
its timestamped **GPS log, GPS track and TSR event log**, together with direct
links to captured Panoramax photos and related dashcam video sessions. Start,
end, measured distance and elapsed time are the summary of that recording.
**Fahrten** makes the underlying logs, route and linked media easy to find,
replay and export. The app also owns a persistent kilometre counter and
usage-time counter, independent of the car's odometer.

GPS and TSR logs are first-class trip data retained for the recorded session,
not temporary diagnostics or just a list of start/end coordinates. The TSR log
preserves emitted recognition and runtime events when TSR is active; an
aggregated traffic-sign discovery list is a separate view of that evidence.
When GPS or TSR is unavailable, preserve explicit coverage states and gaps.

The owner's latest requirements take precedence over the initial request for a
formal German Fahrtenbuch:

| Owner decision | Requirement |
| --- | --- |
| Every driving use is recorded | Automatic trip creation and recovery; no separate Record Track action |
| Each trip contains GPS and TSR logs | Persist time-ordered GPS fixes and emitted TSR events throughout the recorded session, alongside the filtered track and sign-discovery view |
| Each trip links its captures | Direct access to its captured Panoramax photos and related dashcam video sessions, with durable local/remote identities and availability |
| Own kilometre counter | Persist measured YouSpeed distance, per trip and cumulatively |
| Own usage-time counter | Persist actual app-use intervals and cumulative usage time |
| No corrections | No trip edit, correction, retrospective completion, manual reconstruction, split or merge workflow |
| A trip can be deleted | Delete a trip and its private journal data without an audit-ledger retention lock |
| Car odometer is optional | Optional readings; never required to start, save, view or export a trip |
| Useful and enjoyable history | Map, timeline, media rediscovery, visualizations and portable exports |

**Compliance boundary:** these choices define a Fahrtenjournal, not a product
that can promise a tax-compliant German Fahrtenbuch. The product cannot assure
continuous vehicle records when readings are omitted, trips deleted, or driving
occurs outside the app. No editing is compatible with unaltered records; it does
not solve the completeness problem. Section 12 records the legal basis and the
limits of the initial formal-Fahrtenbuch objective.

Use **Fahrtenbuch** as the feature title and **Fahrten** as its short navigation
label. Explain its scope during setup and on export. Do not add a tax-mode
wizard, tax-readiness score, mandatory review inbox or correction history.

## 2. Existing foundations and gaps

This assessment uses the working tree on 22 October 2026, including current
uncommitted work. Source anchors are integration points, not claims that the
feature already exists. iPhone was inspected first as the behavioral reference.

| Concern | Existing foundation | Required addition |
| --- | --- | --- |
| Automatic driving use | iPhone `MainView.swift` starts driving when the dashboard is ready; Android `ConsumerAppUi.kt` does likewise | Durable, idempotent trip start independent of camera and map readiness |
| Session lifecycle | Swift `DriveSessionViewModel.startDriving/stopDriving`; Kotlin `ConsumerSessionController.startDriving/stopDriving` | Journal coordinator and explicit terminal/interruption reasons |
| GPS | Both controllers receive location fixes before asynchronous map lookup | Durable per-trip samples, segments, quality flags and distance increments |
| Current paths/logs | `RoadPathSession` has a short geometry buffer; diagnostic GPS CSVs are global and debug-gated | Dedicated TripStore; no dependency on diagnostics |
| Camera sign observations | `SignCollectionCoordinator` observes broader camera detections | Private durable sign events, independent of contribution consent and queue expiry |
| Mapped signs | Both `InventorySignRuntime` implementations keep a local encounter journal | Link encounter identities and provenance to trips; distinguish map evidence from camera sightings |
| Panoramax | Capture IDs, capture-session IDs, timestamps, location, hashes, annotations and inventory encounter IDs already exist | Durable trip/media index surviving gallery-row cleanup |
| Dashcam | Local recording models expose file identity, creation date and size; library evicts old videos above its quota | Segment sidecars with trip identity and media-clock alignment |
| Galleries | Pictures/Videos, photo filters, playback/share/delete exist | Trip filters, return links and open-at-route-position playback |
| Background | iPhone currently has When-In-Use location configuration; Android has no foreground location-recording service | Honest interruption handling; continuous background recording is a separate extension |

Relevant source files:

- [iPhone driving lifecycle and GPS](../iphone/SpeedConsumerApp/DriveSessionViewModel.swift),
  [navigation and galleries](../iphone/SpeedConsumerApp/MainView.swift),
  [camera/video](../iphone/SpeedConsumerApp/PanoramaxRecorder.swift).
- [Android lifecycle, GPS and capture](../android/app/src/main/java/de/youspeed/android/alpha/ConsumerSessionController.kt),
  [navigation](../android/app/src/main/java/de/youspeed/android/alpha/ConsumerAppUi.kt).
- [iPhone photo metadata](../iphone/SpeedConsumerApp/PanoramaxCapture.swift),
  [photo queue](../iphone/SpeedConsumerApp/PanoramaxQueueStore.swift),
  [private inventory encounters](../iphone/SpeedConsumerApp/InventorySignRuntime.swift),
  [bounded contribution queue](../iphone/SpeedConsumerApp/SignCollectionStore.swift).
- [Shared Panoramax protocol](../shared/PanoramaxUploadProtocol.md),
  [orientation and interaction gates](MANUAL_ORIENTATION.md),
  [1.4 consent and contribution boundaries](YOUSPEED_1_4_SPEC.md).

The contribution store expires or removes event bodies; it is unsuitable as the
personal trip database. Camera-session IDs and collection-session IDs are not
trip IDs. The app's installation contribution UUID is not authenticated ownership
and must not become an archive or private-track access credential.

## 3. User experience

### 3.1 Entry and history

Provide a prominent **Fahrten** entry immediately left of Settings in the parked
dashboard action row, using the existing circular button style. Recording
preferences and their disclosure belong directly in normal Settings; opening
history must not show another recording-settings screen or open automatically
to request consent. History must not require diagnostics or an export first.
The Fahrtenbuch sheet and its odometer dialog have a white background and an
explicit X close control, matching the application's other sheets.

The history screen contains only:
- A newest-first table with exactly five data columns: date/time, start location
  name, end location name, measured distance in km rounded to one decimal, and
  the car's ending odometer in km. Cells may wrap onto several lines. Decimal
  separators follow the user's locale (a comma in German). Narrow screens may
  scroll horizontally while preserving aligned headers and readable cells.
- Every trip row has share and delete controls without adding data columns.
  Sharing prepares that trip's GPS track and GPS/TSR logs for native sharing;
  deletion retains its existing confirmation. Selecting a row opens the
  compact optional end-odometer prompt. Unknown location names remain explicitly unavailable; coordinates do
  not stand in for a location name.
- A brief empty state or actionable read error when needed, and the X close
  control. No charts, counters, totals, filters, search, explanations, backup,
  restore, clear-all, new-trip or extra detail actions surround the table.

Recording remains directly in normal Settings. Existing backup/restore/clear-all
controls belong in a collapsed data-management disclosure there. The explicit
simple-table correction of 23 October 2026 supersedes the earlier history
dashboard and navigation proposals below; retained detail/export internals do
not justify adding controls to the primary trip list or odometer prompt.

Opening the app at home may yield a stationary driving-use session if the live
dashboard activates; show it honestly as zero measured km. Foreground time spent
only browsing settings/history contributes usage time, without inventing a drive.

### 3.2 Trip detail

The top of the detail screen shows date, start/end, distance, duration, track
coverage, and optional vehicle/odometer data. Below it, provide **Karte**,
**Zeitverlauf**, **Medien** and **Export**, using native views.

Provide an accessible **Protokolle** action for the trip's GPS and TSR logs,
with chronological browsing and filtering. The timeline combines these events
with the sign-discovery view. A trip's summary values must never be its only
retained or accessible recording data.

The **Medien** view lists **Panoramax-Fotos** and **Dashcam-Sitzungen** for this
trip, each with capture time, thumbnail where available, availability and a
direct open/play action. A video session groups its related file segments;
the user can open the session from its beginning or at a selected event/route
position. Photos open the local original or the known individual Panoramax
picture; show both actions when both copies exist.

The map and chronological list share one selection:

1. Scrub the track to see time, recorded speed where available, signs and media.
2. Tap a sign or photo to select its position and original capture time.
3. Choose **Video ab hier** to open the matching local clip at its mapped offset.
4. Choose **In Panoramax öffnen** for an available uploaded picture, with its
   actual server origin and remote identity.
5. Open the existing gallery filtered to **Diese Fahrt**, with a return link.

Show track gaps explicitly. A line styled as missing/unknown must not look like
observed travel. The chronological list remains usable without map tiles or
network access and serves as the accessible alternative to map interaction.

Saved measured trip facts are read-only. A missing end-odometer reading may be
entered once from its history row, including after the trip has ended. Existing
readings cannot be overwritten. There are no route dragging, sign correction
tools, or split/merge actions.
Automatic arrival of an already-owned media finalization/upload result may
update availability; it must not change recorded trip distance or timestamps.

### 3.3 Optional values during recording

The automatically started trip offers **Optionale Angaben** while parked,
before its first accepted movement: select a locally named vehicle and enter
the actual start odometer once. This is an initial entry into an active trip,
not a prerequisite to automatic start. A parked **Fahrt beenden** action may offer
an optional end reading before saving. Both sheets have a primary action that
works with all optional fields empty. Do not prompt repeatedly or create
completion tasks. An accepted initial reading is read-only; omission remains
valid if the user dismisses the sheet or starts moving before entering it.

Start readings are accepted only while the trip is active. A missing ending
reading can also be entered once from a saved trip's row; this explicit owner
revision of 23 October 2026 supersedes the previous active-only restriction.
The entry retains its actual entry time and target trip identity. It must be
finite, nonnegative, and no lower than the recorded start reading. Dismissing
the prompt leaves the value absent. Entry never changes trip distance, times,
state or lifetime counters. There is no guessing from GPS, copying the app
counter into the car's odometer, or later correction of an existing reading.
Vehicle-profile changes affect future trips; saved trips retain their snapshot.

Optional business-purpose/customer/category fields are outside the initial
release: without a later-completion workflow they would not establish a formal
tax record. A future request for them must preserve the no-corrections decision
unless the owner explicitly changes it.

### 3.4 Driving safety and accessibility

Reuse the [posture and finalization gates](MANUAL_ORIENTATION.md). The owner's
explicit 23 October 2026 desk-use revision keeps dashboard buttons, Settings and
open submenus usable whenever gravity identifies a face-up phone within ten
degrees of horizontal, regardless of reported GPS speed. Settings must not be
replaced by the driving shutter in that posture. Journal-specific zero-speed
checks must respect this override. Away from that posture, existing motion and
OS-permission gates remain in effect. History navigation must wait for successful dashcam finalization
when the existing gate requires it; stopping video does not itself end the trip.

Support portrait and both landscape orientations, large text, screen readers,
non-color status labels and existing 48 dp control targets. Localize feature copy
to the app's English, German, French and Dutch languages.

## 4. Recording lifecycle

### 4.1 Identity and boundaries

Use three distinct identities:

- `app_session_id`: an execution/foreground-use identity for usage accounting.
- `trip_id`: one app driving-use session, persisted before its first sample.
- Existing camera/capture/collection identities: child associations, retaining
  their separate lifetimes and public-sharing privacy boundaries.

The initial product records **app driving-use sessions**, not a certified
segmentation of every physical vehicle journey. One session may contain a fuel
stop or several destinations. The trip starts when driving use activates and
ends on an explicit stop or terminal interruption. Red lights, congestion,
standing still, camera toggles and video-file rotation do not end it. Do not
infer arrival from a fixed stationary timeout or silently join separate sessions.

Automatic journaling is enabled through its disclosed preference directly in
normal Settings; a previously unconfigured installation remains off until the
owner chooses to enable it. Existing opt-ins and opt-outs are preserved.
Location authorization is a separate OS permission. Accepted journal recording
with denied GPS still creates timed, unlocated sessions. Declined journal
recording creates no saved trips. Preserve explicit opt-outs on upgrade. The user
can disable future trip/track saving; measured counters continue without retaining
the track when authorized driving-location samples exist. Label that setting
clearly. Disabling journaling during a trip finalizes the saved portion with a
recording-disabled reason; reenabling creates a new trip. No later backfill occurs.

The journal must not wait for a road bundle, matcher, camera, TSR model,
Panoramax account, contribution consent or debug-logging setting. It can record
GPS-only use even where driving-assistance data is unavailable. This requires
an independent journal-start path where existing dashboard startup waits for maps.

### 4.2 States and recovery

| Event | Required result |
| --- | --- |
| Driving use activates | Persist active trip header and start time immediately; request/use permitted location independently |
| Duplicate start callback | Reuse active trip; do not double-count samples or usage |
| Good location arrives | Append sample and accepted distance increment transactionally |
| No location / denied permission | Preserve timed session, show missing-location state; measured km do not advance |
| Bad fix, tunnel or long sampling gap | Break track segment; record gap and reason; continue usage timing where app is active |
| Camera or dashcam stops | Finalize/link its media; trip continues |
| User explicitly ends driving | Capture end-intent timestamp, finish owned media through existing gates, optionally accept end odometer while parked, save endpoint and close |
| App leaves foreground | Persist lifecycle/checkpoint; mark unavailable capture intervals truthfully; do not assume background location/video continues |
| App resumes with same live trip owner | Continue same trip with a new segment after any capture gap |
| Process killed, reboot or abandoned owner | On recovery finalize old trip as interrupted at last durable observation/checkpoint; new use creates a new trip |
| Storage cannot accept a checkpoint | Show recording failure, stop claiming complete recording, preserve already committed material |

Use a 300-second foreground-interruption resume window in the initial journal
policy. Returning within that window with the same live trip owner continues
the trip and exposes the gap. Returning later finalizes the old trip at its last
checkpoint and starts a new driving-use session, even if the old process survived.
A new process or boot never silently resumes the old trip. This timeout applies
to unavailable foreground recording, not stationary driving or a fuel stop while
the app remains active. Transient OS permission-sheet inactivity alone is not
entry into the background.

Explicit stop/deletion sets an ended latch for the current driving-use activation.
Dashboard recomposition, returning from an internal sheet or delayed callbacks
cannot immediately create another trip. A new foreground driving-use activation
or parked **Neue Fahrt** action releases that latch. Starting/stopping video never
releases it.

The end-intent timestamp closes measured travel; time spent entering an optional
end reading or waiting for video finalization is not added to trip duration.
Commit that endpoint only if the existing stop/finalization gate succeeds; a
failed gate leaves the trip active and discards the pending stop action.
Enter a bounded finalizing state and drain already-owned sign-encounter callbacks
for up to five seconds before closing the read-only trip. Only events captured
inside its recording interval qualify. On timeout, save a sign-coverage failure;
do not append delayed sign facts to a closed trip. Later owned media-finalization
results may update availability while the trip still exists. Deletion cancels
that ownership too.

Record `started_at`, `last_observed_at`, `ended_at` and `end_reason` separately.
For an abnormal ending, `ended_at` is the last supported observation/checkpoint,
not the later launch at which the app discovers the interruption. Mark the true
end as unknown. Never manufacture the missing destination or intervening route.

Capture start/end locations from actual fixes with their age and accuracy. An
address is an optional derived label with geocoder provenance. Use cached/local
place data by default; remote lookup requires an explicitly enabled online
lookup action. Failure to resolve an address must not prevent saving or exporting
coordinates. A delayed derived label can update its provenance/cache, without
rewriting observed locations, clocks or counters.

Background recording is not promised by this release. Suspension can create
gaps, and force-quit can end recording. A later background-location extension
requires explicit permissions, iPhone/Android capability work and its own parity
acceptance. It must remain independent of background camera availability.

## 5. App-owned distance and time counters

### 5.1 Definitions

| Value | Definition and presentation |
| --- | --- |
| Trip measured distance | Sum of accepted movement increments during this driving-use session; display km |
| YouSpeed-Kilometer | Cumulative measured app-driving distance since displayed counter origin, including deleted trips and driving use with track saving disabled |
| Trip duration | Continuous-monotonic end anchor minus start anchor within the same boot, including stops and flagged suspension gaps |
| Nutzungsdauer | Union of foreground app-use intervals and any genuinely active, authorized background-recording intervals; overlapping intervals count once |
| Observed recording time | Duration of active recorder intervals; distinguish it from gaps inside trip duration |
| Saved-history totals | Totals computed from currently retained trips for the selected date/vehicle period |
| Optional car distance | End odometer minus start odometer, only when both valid readings exist; show separately |

Usage includes foreground settings, gallery and history browsing. A suspended app,
queued upload, stale process, screen-off period without active authorized
recording, or merely installed app does not accrue usage. Camera time is not a
substitute for usage time. The clock works without GPS or camera permission.

When continuous-monotonic anchors are unavailable or cross a boot boundary,
`duration_ms` is null/uncertain rather than a fabricated exact value; show the
known recorded interval total separately. For a same-boot trip from 10:00 to
10:12 with a two-minute suspension gap, duration is twelve minutes, observed
recording time is ten minutes, and foreground-only usage is ten minutes.
Trip-span duration is not a claim of twelve minutes of continuous observation
or motion. Times spent in optional end-entry/finalization UI accrue app usage,
not additional trip duration.

Store counters in integer millimetres/milliseconds; convert to km/hours only for
display and export. Never add rounded display values. Persist the counter's
origin date and measurement-policy version. The distance counter does not claim
vehicle mileage, personal-driver mileage, or a legal odometer measurement.

### 5.2 Distance quality policy

Implement a dedicated, shared-versioned journal measurement policy, separate from
the protected speed-limit-reference policy. Both clients run the same fixtures.

- Use time-ordered GNSS fixes, geodesic distance, accuracy and movement evidence.
  Reject duplicate, stale, invalid, out-of-order and impossible-jump samples.
- Suppress stationary jitter with an accuracy-aware movement filter; do not sum
  every raw point-to-point wobble. Preserve accepted geometry independently of
  any lower-resolution map rendering.
- Never bridge a missing interval with a straight-line distance and call it
  measured. A gap starts a new segment. Map matching/smoothing is optional
  presentation metadata and cannot inflate the measured counter.
- Distinguish measured zero from unknown coverage. A no-GPS trip has zero accepted
  distance and unknown actual distance, displayed as **Keine Distanzmessung**.
- Do not derive distance from speed-limit values, camera detection cadence or
  existing speed-reference distance timers. Those have different semantics.
- Record algorithm version and rejection/gap summaries. A later algorithm update
  applies prospectively; it does not rewrite saved facts or lifetime counters.

Sampling/filter thresholds must be fixed in a shared contract before coding and
validated on low-speed, stationary, urban, tunnel and motorway fixtures. A proposed
baseline is the existing location delivery cadence, with no additional high-rate
GPS request for visualization alone. Thresholds are measurement decisions, not
changes to the protected driving-rule state machine.

### 5.3 Persistence, deletion and reset

Use monotonic clocks for in-process/within-boot durations and UTC plus timezone
snapshots for presentation. Do not add time when the wall clock jumps or count
an entire crash/reboot gap as active use.

Persist counter deltas and input sequence high-water marks atomically with their
related journal checkpoint, so a retried callback or crash recovery counts once.
When journaling is off, keep only minimal aggregate/checkpoint state, without a
stored route. Counter checkpoints must not retain deleted trip identities or
coordinates as a hidden history.

Trip deletion does not roll back either lifetime counter: the app was still used.
History totals fall because the saved trip is gone. Explain this in the deletion
preview and counter help. Lifetime counters survive normal app updates and
ordinary history/media cleanup. They start at zero when the feature is introduced;
do not extrapolate old diagnostic logs into historical lifetime totals.

The initial release offers no reset of the lifetime counter. **Alle lokalen
Fahrtdaten und Zähler löschen** is a separate explicit data-clear action. A later
resettable tripmeter may start a new baseline without changing lifetime totals.
Reinstallation without a restored backup starts a new dated counter epoch.

## 6. Local data contract and architecture

Use a dedicated app-private transactional SQLite TripStore with schema migrations.
Native Swift/Kotlin adapters own platform I/O. Document the platform-neutral
entities, null semantics, measurement policy and export schema in a future
`shared/trip-journal/` contract; this specification does not modify runtime files.

| Entity | Minimum fields |
| --- | --- |
| `Trip` | `trip_id`, schema/app version, start/last/end timestamps, timezone offsets, state/end reason, optional vehicle snapshot, measured distance, supported duration, coverage/gap summary, nullable odometer start/end with unit and entry time |
| `TripGPSFix` | trip ID, stable fix ID/sequence, source and received timestamps, available monotonic/boot reference, coordinates, accuracy, speed/course/altitude, validity flags, track/distance eligibility, distance increment and rejection/gap reason |
| `TrackSegment` | ID, trip ID, ordered segment number, start/end sample references, boundary reason |
| `TrackPoint` | trip/segment ID, sequence, UTC, monotonic/boot reference where available, WGS84 coordinates, accuracy, nullable speed/course/altitude and source/quality flags |
| `TripTSREvent` | trip ID, stable event ID/sequence, original frame/event and received timestamps, event kind, frame/track/encounter identities, related GPS fix, location/accuracy where available, raw and normalized classes, emitted scores, model version, outcome/reason and versioned runtime payload |
| `TripSignEvent` | local event ID, trip ID, original encounter/track identity, event time/location, evidence source, country/class/value, model/bundle provenance, confidence and media links |
| `MediaReference` | media ID, trip ID, capture-session ID, type, capture interval, availability, local opaque locator, content hash, optional remote origin/IDs and clock alignment |
| `UsageInterval` | session/sequence, clock anchors, interval type, duration and committed high-water mark; compact after accounting |
| `AppCounters` | counter epoch/origin, measured-distance and usage totals, policy versions, minimal idempotency/checkpoint state |

Odometer values are optional decimal km with original unit retained where a
vehicle displays miles. Null is absent, never zero. Negative or decreasing paired
readings are rejected before save, with **Wert weglassen** always available.
Never block trip saving because an optional reading was invalid or missing.

Snapshot trip facts at finalization. Internal recovery, media availability and
derived place labels may update with provenance; user edits to saved facts are
not supported. Do not implement a shadow immutable legal ledger or retain deleted
trip content under an audit requirement.

Recommended components: `TripJournalCoordinator`, `TripStore`,
`TripDistanceAccumulator`, `AppUsageCounter`, `TripMediaIndex`, and
`TripExportService`. They subscribe to existing location/camera/encounter events
without taking over camera ownership, model inference or the map matcher.
Journal writes must be asynchronous/bounded and must not block driving UI or
camera work; overflow/storage failures become visible coverage failures.

### 6.1 GPS log and derived track

Retain each delivered location fix for the recorded trip with its original
timestamp, receipt time, quality and eligibility result. A fix rejected for
distance accumulation remains in the GPS log with the reason; it does not
become a route segment or add kilometres. Represent invalid/missing numeric
fields safely as null with flags. The rendered/exported track is the filtered
geographic view of this log, not a replacement for it.

Keep logs trip-scoped and independent of the global debug-log switch. No log
events may be silently discarded to retain only the summary: storage/queue
loss must create an explicit coverage-gap record. Deleting the trip deletes
both logs as well as its derived track and discovery view.

## 7. TSR log and traffic-sign discovery view

Retain a timestamped TSR runtime event stream throughout the recorded session:
emitted recognition results and scores, track/encounter updates, passage
confirmation or rejection, applicability outcomes and available decision
reasons. Link events to their source frame/encounter and GPS fix where possible.
Preserve event time separately from callback receipt time so delayed results
remain correctly aligned with the route and media. Keep detector and classifier
scores distinct, retain model/mapping versions, and log camera/model/thermal
interruptions when those events are available.

This event log is distinct from deduplicated sign encounters: recognition
updates and rejected/uncertain outcomes must not disappear just because no
actionable sign was ultimately confirmed. Record TSR start/stop, unavailable
states and dropped-event gaps. Logging metadata does not enable camera/TSR
when disabled, retain a raw camera-frame stream, or change speed-reference
interpretation. Every inference result/event emitted to the journal is retained;
frames never processed by the existing pipeline have no invented result.

Persist a private trip observation stream after existing encounter aggregation,
before filtering for actionable speed-limit behavior. It must work even when
sign contribution is disabled. If TSR/camera is disabled or unavailable, record
that coverage state rather than claiming no signs existed.

Keep these evidence sources explicit:

| Source | Meaning |
| --- | --- |
| `camera_observation` | A sign was observed by the camera; retain raw class, confidence, model and encounter identity |
| `inventory_encounter` | The app passed a mapped sign candidate; not proof it was physically present or seen |
| `inventory_camera_confirmation` | Existing runtime evidence links a mapped encounter to camera support; preserve that exact association |

Log non-speed and unknown signs, supplementary relationships and uncertain
applicability. Preserve country, raw and normalized class, numeric value/unit
when actually available, location accuracy, original timestamps and available
support/capture IDs. A database sign position and the phone's observation position
are different fields. Predicted speed-limit states are not discovered physical
signs.

Deduplicate per encounter using stable tracker/source identities, not by dropping
all signs of the same class or all nearby observations. Repeated passes remain
separate encounters. Inventory and camera evidence may be linked without losing
their separate provenance. There is no claim of globally new sign discovery:
the existing contribution channel does not return a global novelty catalogue.

There is no new manual correction/reclassification UI. Events retain the evidence
available at capture. Render display-eligible signs using shared official
[pictograms](../shared/tsr/sign-pictograms/); numeric speed-limit rendering keeps
its existing schematic exception. Do not introduce hand-drawn substitutes.

## 8. Finding pictures and video again

### 8.1 Stable associations

Attach `trip_id` to local capture indexing at capture start; preserve capture IDs
and original camera-session identities. The private trip ID must not be added to
public Panoramax metadata or contribution payloads without a separate approved
protocol/privacy change. Use a local relation table where existing schemas cannot
carry it safely.

For Panoramax, retain the selected instance origin, upload-set ID and per-image
remote ID as they become known. Persist a minimal durable reference before
successful-upload cleanup removes the gallery record. Only show an individual
remote picture link when its ID is known; an upload-set link is labelled as such.
Remote links are not proof of remote availability and require network to open.

For dashcam, create a sidecar for each finalized segment: media ID, trip ID,
capture-session ID, UTC/monotonic start/end anchors, actual presentation-time
origin, duration, orientation, checksum and sparse location/time anchors.
Video seeking must map capture time to media presentation time, accounting for
gaps and segment boundaries. File modification time is not a sufficient anchor.

An exact encounter/capture ID can assert a relationship. Time/location proximity
alone is labelled **In der Nähe aufgenommen** and cannot claim that a picture
contains the selected sign. Legacy files without reliable anchors may appear in
the existing gallery; do not silently assign them to new trips or lifetime totals.

### 8.2 Availability

Distinguish local original, local missing/deleted/evicted, upload pending,
uploaded/remote reference, and remote unavailable. An unrecorded moment says
**Keine Aufnahme vorhanden**. Do not fabricate media or imply every metre has
video. A route and its counters survive ordinary media-quota eviction.

When local pixels are deleted, remove related thumbnails according to the user's
choice and existing protocol; retain only the minimal reference needed to show
availability while the trip exists. Deleting the trip removes that private
reference too. Existing [Panoramax ownership and finalization
rules](../shared/PanoramaxUploadProtocol.md) still govern in-flight/accepted
images; do not make them deletable early through the trip view.

## 9. Exports

All exports work offline for locally available data. Use the native share/save
flow and a clear preview of trip count, date range, coordinates, media inclusion,
missing data and optional odometer disclosure. Empty history, cancellation,
insufficient storage and an active trip have explicit outcomes. An active-trip
export is an **in-progress snapshot**, never a finalized record.

| Preset | Required output | Rules |
| --- | --- | --- |
| **Track exportieren** | GPX 1.1; GeoJSON option | Separate segments at gaps, preserve UTC timestamps; include only actually available elevation/speed metadata |
| **GPS-/TSR-Protokolle** | GPS CSV plus lossless versioned GPS/TSR NDJSON/JSON | Full retained fix/event streams, original timestamps, quality/outcomes, related identities, GPS eligibility and explicit sequence gaps/loss ranges in a completeness manifest |
| **Verkehrszeichen-Protokoll** | UTF-8 CSV and versioned JSON | Aggregated discovery view with original event IDs/provenance, coordinates/accuracy, classes, confidence, values/units, linked media, coverage and unknowns |
| **Fahrtenübersicht** | Readable PDF plus CSV | Start/end, km, duration, state, optional vehicle/odometer; measured km and car readings in separate columns; explicit journal-scope statement |
| **Fahrtarchiv** | ZIP with manifest, trip JSON, GPS log, TSR event log, filtered track, discovery log and media index | Logs included by default; optional selected local photos/videos; relative portable names, file sizes, SHA-256 checksums, omitted/unavailable-item report |
| **Zählerstände** | CSV/JSON within the overview/archive | Counter origin, lifetime distance/usage and retained-trip totals separately; selected date range must not imply a lifetime-counter reset |

The machine-readable schema must define units, coordinate order, nulls, clock and
timezone meanings, evidence enums and measurement-policy version. CSV uses stable
column names, ISO 8601 timestamps and decimal points; readable reports localize
numbers/dates. GeoJSON coordinates are longitude/latitude. Include a schema
version and export generation time. Sanitize spreadsheet formula-like text in
CSV without losing original values in the JSON counterpart.

GPX track alone cannot hold all sign provenance: include the JSON/CSV sidecar
when that preset is selected. Keep missing coordinates as null in event JSON/CSV;
do not invent coordinates to produce a map pin. No media bytes are included
unless selected. A remote reference is labelled as a link, not an archived image.

Offer **Privat teilen** with optional endpoint/home-area masking and stripped
photo GPS metadata for selected media. Preview exactly what remains, including
sign/media pins that could reveal a masked area. This creates a derived sharing
copy; original trip facts and app counters do not change. A masked track's
geometric length can differ from the original measured distance; label both.
The masked preset excludes raw GPS/TSR logs by default. If included, apply the
same masking to every fix/event, including rejected GPS fixes, and remove road,
place and media references that reveal the hidden area; never bundle unredacted
source logs with a masked track.
Videos and remote links can reveal location visually or through remote metadata;
exclude them from the masked preset by default and state the limitation.

Export filenames are portable, for example `youspeed-trip-2026-10-22-<id>.zip`.
Exports are snapshots: subsequent trip deletion cannot recall files a user has
already saved or shared. Do not silently email, publish or upload an export.

## 10. Deletion, privacy, storage and recovery

### 10.1 Deletion contract

**Fahrt löschen** is available for every saved trip, including interrupted and
stationary sessions. Require a normal destructive-action confirmation showing:

- Trip, GPS/TSR logs, track, optional odometer values, private sign timeline, private media
  associations and derived trip caches will be removed.
- Existing library photos/videos remain unless **Lokale Medien ebenfalls
  löschen** is selected; show their count and any protocol-owned items that
  cannot yet be deleted. Never claim those files were removed if cleanup fails.
- Cumulative YouSpeed km and usage remain. Saved-history totals decrease.
- Already shared exports, contributed sign data and published Panoramax images
  are separate copies, with links to their existing deletion controls.

Do not retain a reconstructable trip tombstone, coordinates, odometer record or
hidden correction/audit copy. Minimal content-free job IDs may survive briefly
to complete physical cleanup; remove them afterward. Stop/cancel active journal
writers before deleting an active trip, or offer **Beenden und löschen** while
parked. A late media callback must not recreate deleted trip data.

Delete trip-owned local data in a recoverable transaction/job, invalidate map
and search caches, remove temporary exports still owned by the app, and prevent
automatic legacy import or stale local backup reconciliation from resurrecting it.
Remove private trip links from retained media sidecars/local relation metadata;
keeping a picture in the library must not keep a hidden trip record.
Use the platform's database/file protections and account for SQLite/WAL/free-page
cleanup; do not promise forensic erasure of flash storage. Restoring an older,
user-selected external backup is an explicit restore of that older snapshot.

### 10.2 Privacy and retention

Keep journal, counters and media index on device by default, with no account.
Disclose automatic local location history before first recording; denied
permissions remain respected. Enabling this feature does not enable dashcam,
Panoramax, independent TSR, sign contribution or new network traffic.

Never send continuous tracks, app counters, vehicle labels or optional odometer
readings through the existing sign-contribution channel. Keep contribution session
identities separate. Live driving/rule interpretation does not consume private
trip history or export responses.

Trip history is retained until the user deletes it or clears local data. Display
its storage size; do not silently delete trips to make room for video. Existing
media quotas and explicit Panoramax cleanup choices continue separately. At low
space, prioritize journal commits over optional rich thumbnails; if saving is
impossible, expose the gap/failure rather than showing successful recording.

Provide a user-triggered local backup/restore archive containing trips, counters,
schemas and the media index, with media optional. Treat export files as sensitive.
Backup protection/encryption and OS-backup inclusion must be documented before
release. Restoring is an explicit whole-journal replacement, with preview and
matching counter epoch; initial release has no merge/import-and-add operation.
Restore must not count imported samples as newly driven kilometres or usage.

## 11. Visualizations and enjoyment

The first release includes a route map, synchronized event timeline, media pins,
trip distance/duration summaries and simple weekly/monthly saved-trip charts.
Charts distinguish lifetime app counters from retained-history totals and show
missing coverage instead of extrapolating it.

Follow-on experiences use the same private index:

- Animated route replay with time scrubber and optional speed/elevation chart.
- Personal route overlays showing revisits and traveled areas.
- Compare repeated recorded routes by elapsed time and available coverage.
- A photo story with signs and pictures encountered along one drive.
- Personal observed-sign collection by country/class, with uncertainty and
  camera-versus-inventory provenance.
- A shareable route image or short locally generated replay, with privacy preview.

These are retrospective features used while parked. Do not introduce competitive
speed scores, incentives to drive farther, public leaderboards, fabricated CO2
savings or an assertion that a detected sign is globally new.

## 12. German formal-Fahrtenbuch assessment

Research date: 22 October 2026. This section explains a product-scope conflict;
it does not impose a mandatory odometer, corrections, archival locks or a hidden
formal mode contrary to the owner's later instructions.

| Formal requirement / distinction | Consequence for this feature | Official basis |
| --- | --- | --- |
| Timely, closed, complete vehicle records; business trips require destinations, purpose/partner and vehicle kilometre particulars. Private trips and commuting have simplified particulars | The product cannot assure continuity when readings are omitted, trips deleted, or driving occurs outside the app | [BFH VI R 50/15, reasons II.1.b](https://www.bundesfinanzhof.de/de/entscheidung/entscheidungen-online/detail/STRE201750158/); [LStH 2026 R 8.1(9) no. 2](https://ao.bundesfinanzministerium.de/lsth/2026/A-Einkommensteuergesetz/II-Einkommen-2-24b/4-Ueberschuss-d-Einnahmen-ueber-die-Werbungsk-8-9a/Paragraf-8/r-8-1-9.html?nn=456694) |
| Electronic changes must be excluded or visibly documented in the record itself | Read-only saved trips help, but free removal of original entries is not an audit-complete formal book; a checksum alone does not cure missing trips | [BFH VI B 37/23, 12 January 2024](https://www.bundesfinanzhof.de/de/entscheidung/entscheidungen-online/detail/pdf/STRE202450011?type=1646225765) |
| The seven-calendar-day concession concerns later purpose/partner entry when all trips already record date, odometer and destination automatically at trip end | It is not a general seven-day reconstruction allowance and does not validate an incomplete GPS journal; no such workflow is offered here | [LStH 2026 Anhang 24 IV.1, Rz. 28–29](https://lsth.bundesfinanzministerium.de/lsth/2026/B-Anhaenge/Anhang-24/IV/IV-1/inhalt.html) |
| Fahrtenbuch-method tax valuation also requires actual vehicle-cost evidence | Distance/time exports do not calculate or establish the taxable private-use benefit | [§6(1) no. 4 EStG](https://www.gesetze-im-internet.de/estg/__6.html), [§8(2) EStG](https://www.gesetze-im-internet.de/estg/__8.html) |
| Electronic retention requires continued availability, readability and machine evaluation; retention periods depend on document type and tax context | Do not sell the journal's deletable history or PDF export as a legally complete archive, or promise a universal ten-year rule | [§147(2)–(6) AO](https://www.gesetze-im-internet.de/ao_1977/__147.html) |
| An authority-ordered Fahrtenbuch under §31a StVZO is a different obligation, including pre-drive driver details and an immediate post-drive signed entry | This automatic journal does not implement an authority's Fahrtenbuchauflage | [§31a StVZO](https://www.gesetze-im-internet.de/stvzo_2012/__31a.html) |

Required German explanation in setup/help and the Fahrtenübersicht export:

> YouSpeed zeichnet Ihre App-Fahrten auf. Fahrten können gelöscht werden;
> Fahrzeug-Kilometerstände sind freiwillig. Dies ist ein privates Fahrtenjournal.
> Eine steuerliche Anerkennung als ordnungsgemäßes Fahrtenbuch wird nicht
> zugesichert. Die Funktion erfüllt keine behördliche Fahrtenbuchauflage nach
> § 31a StVZO.

Use **Fahrtenübersicht** for the PDF, not **Finanzamt-Nachweis**. Do not display
**finanzamtkonform**, **GoBD-zertifiziert**, **lückenloses Fahrzeugfahrtenbuch** or
a tax-compliance badge. Users may give exports to an accountant as supporting
material; the app cannot assert the acceptability of their whole record.

If a formal tax product is requested again, first resolve complete vehicle
coverage, mandatory vehicle-distance evidence for relevant entries, business
particulars, retention and treatment of deleted originals with the owner and a
German tax professional. That is a separate product decision, not deferred
implementation silently included in this scope.

## 13. Delivery sequence and acceptance

### 13.1 Implementation sequence

| Phase | Deliverables | Completion evidence |
| --- | --- | --- |
| 1 — durable recording | Shared contract/fixtures, TripStore, per-trip GPS/TSR logs and filtered track, GPS-only sessions, distance/usage counters, optional active-trip odometer, recovery and deletion | Both clients produce equivalent logs, facts and counters for replay fixtures; no duplicate increments or silent data gaps |
| 2 — usable Fahrtenbuch | Prominent history/detail, track map/list, private sign log, photo/video index and seeking, GPX/CSV/JSON/PDF/ZIP exports, backup/restore, basic period charts | Full parked workflow on both clients, portable export inspection and deletion/retention checks |
| 3 — richer exploration | Animated replay, route comparison, photo stories and private sharing visuals | Performance/accessibility/privacy review with real recordings |

Phases 1 and 2 together are the initial feature release. Continuous background
tracking, cloud synchronization, fleet administration, vehicle/OBD integration,
tax accounting and a formal legal Fahrtenbuch are outside this release.

### 13.2 Required acceptance cases

These are product acceptance criteria. The
[implementation record](FAHRTENBUCH_IMPLEMENTATION.md) and
[continuation receipt](V1_5_IMPLEMENTATION_CONTINUATION_2026-10-23.md) distinguish
automated native/fixture coverage from physical and sustained-load acceptance
that has not been performed.

| ID | Scenario | Expected result |
| --- | --- | --- |
| FB-01 | Drive with camera, TSR, Panoramax and diagnostic logging off | Trip, GPS track, km and usage record normally; media/sign coverage shows disabled |
| FB-02 | Maps/models unavailable or no network | Journal still starts; local track/list and export work; no fake road/address |
| FB-03 | Foreground history/settings only; stationary driving session with GPS jitter | Usage grows; history-only use creates no trip; stationary driving session has zero false km |
| FB-04 | Known accepted fixture distance 12,345 m across three checkpoints | Trip and app counter add 12.345 km before display rounding; callback retry adds nothing twice |
| FB-05 | Ten foreground minutes, four overlapping active-recorder minutes, then three suspended minutes | Usage adds ten minutes, not fourteen or thirteen; no authorized active recording means suspension adds zero |
| FB-06 | No GPS permission, poor accuracy, tunnel and impossible jump | Usage persists; no fabricated km/route; gaps and measurement unavailability are visible in UI/export |
| FB-07 | Traffic lights, fuel stop, repeated start callback, camera toggle and video rotation | Same trip; no artificial split or duplicate distance/time |
| FB-08 | Foreground loss/resume, force-quit and reboot | Correct gap/interrupted states; last durable endpoint retained; recovery does not extend old trip to next launch |
| FB-09 | Wall-clock/timezone/DST changes | UTC evidence retained; monotonic usage unaffected; local labels/offsets and uncertain durations remain honest |
| FB-10 | Optional odometer omitted or only one reading supplied | Start/save/export succeed; missing reading stays null; GPS/app counter is never substituted |
| FB-11 | End odometer less than start | Optional value rejected before save with omit option; automatic trip save remains available |
| FB-12 | Inspect any saved trip | Read-only facts; no edit, correction, completion, split or merge workflow |
| FB-13 | Same sign class seen twice; nearby mapped sign not camera-confirmed | Distinct encounters/provenance retained; map presence does not become camera discovery |
| FB-14 | Tap sign/photo then open matching dashcam moment across a file boundary | Correct trip/clip and presentation-time offset; approximate legacy relationship labelled |
| FB-15 | Video quota eviction or completed Panoramax local cleanup | Trip/track persists; availability updates; known remote picture opens on its actual instance |
| FB-16 | Delete trip with/without local-media option; late media callback arrives | Private trip/route/sign/index/caches removed; requested eligible media cleanup truthful; no resurrection |
| FB-17 | Delete a 12.345-km trip | Saved-history total falls by 12.345 km; lifetime km and usage stay unchanged; preview explains difference |
| FB-18 | Clear all trip data and counters | Explicit confirmation; new empty counter epoch; no hidden trip/audit retention |
| FB-19 | Track saving disabled with authorized driving use | Minimal counters advance; no private route/trip history is stored; enabling later does not backfill |
| FB-20 | Export interrupted/active/no-GPS trips with unknown sign classes and Unicode labels | Valid versioned data, honest nulls/gaps/state, safe CSV text, portable archive and matching totals |
| FB-21 | Masked sharing copy with sign/photo pins, embedded GPS and remote links | Preview reveals residual disclosure; masked positions/media metadata removed as promised; original/counters unchanged |
| FB-22 | Backup/restore same archive or crash around a database commit | Restored epoch/totals match backup once; atomic save/recovery; no imported-distance inflation |
| FB-23 | Low storage or unreadable store | Existing data preserved, failure visible, no success indicator for unwritten facts |
| FB-24 | Fresh install/update and declined recording permissions | Disclosure and explicit choices respected; no new contribution, camera or public upload enablement |
| FB-25 | Large text, screen reader, portrait/landscapes, existing stationary/finalization gates | History/export/media workflow usable; no new moving interaction or recording-order regression |
| FB-26 | Read app copy and representative PDF/CSV exports | Scope/units explicit, optional odometer distinct, no promise of formal tax or §31a compliance |
| FB-27 | Resume after two minutes versus six minutes of unavailable foreground recording | Same live trip plus gap within 300 seconds; later return closes old checkpoint and creates new trip; no overnight joining |
| FB-28 | End/delete trip and then trigger dashboard recomposition or a late sign callback | Ended latch prevents immediate restart; drained initial events are bounded; closed/deleted facts do not reappear |
| FB-29 | Recorded drive has multiple GPS fixes, TSR updates and rejected/uncertain observations | Trip retains browsable/exportable GPS and TSR logs throughout its coverage, beyond summary values and deduplicated discoveries; rejected distance fixes remain labelled in the GPS log |
| FB-30 | Open a trip with captured Panoramax photos and a dashcam session split across files | Its media view directly opens each available photo and the related video session; route/event selection seeks the matching segment/time; missing media has an honest availability state |

Before implementation, turn the unresolved numerical measurement thresholds,
backup protection and media-clock tolerance into shared, versioned contracts.
Validate iPhone behavior first, then Android parity. Physical-device validation
is required when installation/deployment is explicitly requested; this spec does
not authorize either. No change to the protected speed-limit-reference policy,
its interpreter semantics, sign artwork policy or contribution network gating
is required by this feature.
