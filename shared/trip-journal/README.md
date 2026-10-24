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
measured kilometres to one decimal, and the ending car odometer. A missing ending
reading may be entered once from an existing trip's row, including after closure;
existing values stay immutable. A finite nonnegative value must be at least the
stored start reading. Its entry event belongs to that explicit trip and never
changes measured distance, timestamps, state or aggregate counters.

Optional `place` events retain fresh, stable offline matcher street/locality names
at the original GPS fix time. Endpoint labels are a read-only projection of
nearby valid endpoint fixes and place evidence, with gap/time/distance checks.
Unavailable names remain unavailable. This adds no schema fields or geocoding
network calls. Place evidence is private and excluded from masked shares.

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

Exports include trip JSON, GPX, GPS/TSR/media NDJSON, a readable PDF overview and
a file/checksum manifest. They contain private locations and are user-shared
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
