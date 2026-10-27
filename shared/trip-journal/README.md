# Private trip journal — storage/export contract v1

Both clients keep private SQLite `trips`, `events`, `bindings` and `counters`
tables. They do not share this data through the sign-contribution protocol.
Trip and capture identities are separate. Event sequence numbers are local to
one database; trip IDs are UUIDs.

Times in the outer exported event envelope are Unix seconds UTC. Distances in
storage/export are metres, durations seconds; UI converts to kilometres/hours.
A `gps` payload contains the original fix, quality/eligibility, reason and
accepted distance increment. A `tsr` payload preserves runtime/recognition
metadata, including original frame timing when provided. `gap` marks capture
interruption. A `media` payload identifies the capture and session, type and
local locator or explicit remote Panoramax URL. Missing local files are not
silently regenerated. Logs are independent of diagnostic logging settings.

The 23 October 2026 history revision moves recording consent directly into normal
Settings. The five-column history shows date/time, start/end location names,
measured kilometres to one decimal, and the ending car odometer. The odometer
is headed **Auto (km)** in German; distance uses **Distanz (km)** on both
clients. Each row has a share icon before date/time and a delete icon after the
odometer, both aligned with the top of the row text.
Android's column widths adapt to the available screen width; dates and place
names wrap vertically so all five columns and both actions remain visible
without horizontal scrolling. A missing ending
reading may be entered once from an existing trip's row, including after closure;
existing values stay immutable. A finite nonnegative value must be at least the
stored start reading. Its entry event belongs to that explicit trip and never
changes measured distance, timestamps, state or aggregate counters.

A **Stop trip** button is available at zero displayed speed with a fresh,
accurate stationary fix while recording is enabled. Stop durably ends the trip
and freezes its measured distance before opening the six-digit car-odometer
editor. New GPS/map results cannot dismiss or reset that editor, and odometer
saving no longer requires another stationary fix. Later/dismiss leaves a saved
trip with a missing optional ending reading. Recording stays enabled and the
next trip begins on movement.

On closure (including interrupted-session recovery), automatically discard a
trip whose first and last usable GPS fixes are **less than 100 m apart in a
straight line**. A loop ending near its start is discarded even if its recorded
driven distance exceeds 100 m. Both clients use the same haversine calculation
with mean Earth radius 6,371,008.8 m; exactly 100 m is retained. Stationary usable
fixes count as endpoints; duplicate, out-of-order, network-only and invalid fixes
do not. Empty zero-distance sessions are discarded too. Missing endpoint
evidence on a nonzero-distance trip does not establish a short trip.
While the current start/end separation is below 100 m (or endpoints are not yet
known), buffer the active session's evidence without showing it in **Fahrten**
or offering the stop button. Reaching 100 m enables that history row and the
ordinary stationary stop control; returning below 100 m hides both again.
This visibility check uses cached usable endpoints and never replays event logs
from the dashboard or history view. The normal speed display still shows zero
when stopped before the threshold. When the stop button is shown, it replaces
the zero on both platforms, using the same 17 pt/sp semibold label, 18 pt/dp stop
symbol and 48 pt/dp minimum height.

Cleanup removes the trip's events, bindings and temporary exports, preserves
lifetime counters and independent media, and prevents late callbacks from
recreating the discarded trip. A finished short trip has no odometer editor;
stale stop actions for an active short trip are rejected. Existing completed history and explicit
backup restores are not retrospectively filtered.

Optional `place` events retain offline matcher street/locality names at the
original GPS fix time. SQLite schema 3 stores `start_place`, `end_place` and
`history_version` with the trip. Closure resolves the endpoints once from nearby
valid fixes and captured place evidence, with gap/time/distance checks. Where a
five-second finalizer is used, names are resolved after that window so delayed
map callbacks for the original fixes are included. Metadata version 2 repairs
missing version-1 names once from existing local evidence, preserving every
already saved name. Trips without nearby captured names still show an unknown
location. A background one-time migration also handles legacy completed or
interrupted trips; version-2 metadata, including an unavailable name, is never
recomputed.
No history screen calls map/geocoding services or replays event payloads. iPhone
publishes a ready-to-display trip-table cache; Android history reads only the
trip table. Distance remains the incrementally recorded value. Optional stored
names survive backup/restore and unmasked exports; masked shares exclude them.

`TripMeasurement` version 1 is mirrored in Swift/Kotlin: accept an increment only
for increasing time within 15 seconds, travel at most 70 m/s, displacement at
least max(3 m, both accuracy radii), and reported speed above 0.5 m/s. Round
accepted increments to millimetres. Keep the movement anchor across jitter/slow
fixes so valid slow movement can accumulate. Gaps reset the anchor. Rejected
fixes remain in the GPS log. These are journal measurement gates, not changes
to the protected speed-reference policy.

Trip deletion removes events/bindings, preserves independent lifetime counters,
and cannot be undone by a late callback for the deleted capture session. A new
process marks previously active trips interrupted. GPS/TSR are not enabled by
journal consent. Logging location use still requires existing OS permission.

Exports contain one canonical event representation in `journal.json`, GPX,
a readable PDF overview and a file/checksum manifest. Per-kind event JSON, CSV
and NDJSON copies are no longer written. They contain private locations and are user-shared
snapshots, not tax-compliance certification. Media bytes remain in the existing
libraries and are not included automatically.

`measurement-policy-v1.json` fixes measurement/foreground/media tolerances.
Existing SQLite REAL metre/second storage stays in place; an integer-unit
migration and representation optimization are separate work.

Every archive additionally includes `journal.json` conforming to
`export-v1.schema.json`: normalized trip fields, object-valued timestamped event
payloads, media index, units and masking/raw-log declarations. Unknown event
kinds remain intact in unmasked exports and backups. GPX segments split on
coverage gaps or unusable fixes, not on intervening TSR/media events.

Backup envelope v1 uses AES-256-GCM with a random 16-byte salt, 12-byte nonce and
PBKDF2-HMAC-SHA256 (100,000 iterations). `sealed` is base64 of nonce+ciphertext+
16-byte authentication tag; its SHA-256 is an integrity check additional to
authenticated encryption. Restoring replaces the local journal/counter epoch
transactionally; it never replays samples into counters. Encryption protects
the user-created backup, not pixels retained in their existing media libraries.
Local private stores remain in each platform's app sandbox, with iOS protected
files; normal OS device-backup policy still applies. Passwords are never saved.

Native recorder callbacks currently provide an explicitly estimated media-clock
anchor (up to 2 s). Sidecars preserve monotonic/UTC origin, duration and detected
alignment error. Uncertain or out-of-interval moments have no seek action.
`presentation_clock` may be used only for a measured frame-to-presentation mapping
within 250 ms; callback-time estimates never acquire that label.

## Compact export profile

Both clients default to `export_profile: "compact"`. Normal sharing and the
export-options sheet keep verbose diagnostics off. Compact exports preserve
original event sequence IDs/timestamps and all payloads except message-only TSR
rows: `kind == "tsr"`, string `payload.message`, and payload keys limited to
`message` and optional `received_at`. A TSR row containing any other field is
retained, including structured recognition frames, model lineage, road context,
candidates, bounding boxes, tracked signs, restrictions and supplementary OCR.
GPS (including rejected fixes), signs, gaps, media references and unknown event
kinds remain intact. Recorded source events and encrypted backups are unchanged.

The explicit diagnostic option retains the complete event stream once in
`journal.json`, sets `export_profile: "diagnostic"` and `raw_logs_included: true`.
The default compact profile sets `raw_logs_included: false`; this now means the
verbose prose diagnostics are excluded, not that typed GPS/frame evidence is
missing. `omitted_verbose_message_events` records the omitted count in journal
and manifest. Both fields are optional additions to portable schema v1. Masked
exports retain their existing sanitization and use `export_profile: "masked"`.

Text entries use standard ZIP DEFLATE, including on iPhone; media bytes are not
re-encoded except under the existing masked-photo option. Media selection stays
explicit: a media metadata record is not proof that its original image/video
bytes were included. Small reports/tracks and the media index remain useful
alternative views; the full raw event stream is no longer repeated in several
sidecars. The web importer and its upload limits are unchanged.
