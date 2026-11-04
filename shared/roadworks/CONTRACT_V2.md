# Reported road advisories, version 2

Implementation scope: BEMaS, BW incidents and Autobahn short/long-term works.
Deployment and activation are postponed. This adds no speed-reference policy,
route avoidance, audio alert, camera observation or capture behavior.

## Compatibility and wire format

Keep v1 and its BEMaS-only meaning available. New clients request
`/youspeed/live/v2/regions/DE-BW`; immutable snapshots use
`/youspeed/live/v2/regions/DE-BW/snapshots/{sha256}`. Native parsers continue to
read v1 caches; v2 is an explicit schema/API version, not a v1 reinterpretation.
Existing opt-in preferences remain initially off and retain their stored values.

V2 keeps the v1 manifest/snapshot fields and limits (256 KiB manifest, 8 MiB
decoded snapshot, 10,000 features, 200,000 vertices). Manifest `freshness` still
contains `server_time` and an aggregate status. Aggregate availability is the
best enabled source status, ordered fresh, delayed, unknown, unavailable. It
never grants eligibility to individual features.

Manifest `sources` is a nonempty array of unique objects:

* `source_id`: `bemas`, `incidents-bw`, `autobahn-short-term`, or
  `autobahn-long-term` (unknown sources are rejected in this version).
* `enabled`: Boolean; false means no driving presentation for that source.
* `freshness`: `status`, `source_publication_at`, `source_modified_at`, and
  `last_checked_at`, using the same nullable offset-bearing clocks as v1.
* `attribution`: provider, dataset URL, license ID, license URL, changes.

Coverage keeps `region=DE-BW`, `complete_road_coverage=false` and a Boolean
`autobahn_included`, and adds `source_ids`, exactly the manifest source IDs.
The Autobahn flag must equal whether an enabled Autobahn source is present.
An empty or disabled source is not proof of complete coverage or an empty road.

Snapshot adds a unique nonempty `source_ids` allowlist and each feature adds
`properties.advisory_source` from that list. Its opaque ID must start with
`mobidata-bw:{advisory_source}:`. Existing `properties.source_id` retains the
publisher record identity. All v1 provenance, geometry, schedule and checksum
requirements remain. `kind` supports roadworks, closure, incident, hazard and
congestion; unknown meanings remain noneligible. `operator_status=reported` is
supported only for non-BEMaS sources; existing BEMaS statuses retain their meaning.
Snapshot source IDs must agree with the installing manifest source IDs.


BW incidents also require `validity_basis`, `source_validity_status` and nullable
`source_validity_start`/`source_validity_end` (the original overall source times).
For `scheduled`, status is `definedByValidityTimeSpec` and bounded source periods
are compiled as before. For `reported_active`, status is `active`: DATEX reports
current activity regardless of the original time specification. Its effective
`outer_start` is the source publication time and `outer_end` is at most 900
seconds later. This is an observation lease, **not a claimed physical event end**.
The lease is also constrained by ordinary per-source freshness, explicit
suspension and later projection replacement. A 304 cannot extend the original publication or lease. Native cache
installation binds such leases to the matching source's manifest publication
clock, and parked details label expiry as report expiry. Unknown validity and
non-real/test/exercise messages are not eligible. The
observed `allElementUpdate` profile is required for incidents; it establishes
completeness only within an included situation. Global collection completeness
is unverified. Each accepted publication contributes a positive subset; absence
only removes projection membership and cannot establish cancellation or road
clearance.
The original time specification is retained for inspection and cannot override
an explicit `active` status. BEMaS and v1 timing semantics remain unchanged.

## Source isolation

Use the manifest's trusted server/HTTP clock and monotonic elapsed time for
each source. A missing required clock, future clock, unsupported meaning or
disabled source cannot produce a driving card. Roadworks retain v1 ages:
fresh up to 30 minutes source age/15 minutes check age, unavailable after
24 hours. Incidents are fresh up to 10 minutes source/check age and unavailable
after 15 minutes source OR check age. Between those bounds they are delayed.
The incident freshness window follows the catalogue's ten-minute publication
cadence; the fifteen-minute cutoff remains a separate driving-advisory expiry.
These are advisory gates, independent of the protected speed-reference policy.

Select features using their own source status, not the aggregate status.
Failure/expiry of one feed must not suppress another healthy source. Source
removal or disablement invalidates its cards immediately; source loss never
renews previously reported event validity. Keep complete snapshots, atomic
promotion, current/previous rollback and immutable source provenance. A failed
source refresh retains its previous accepted generation and original clocks;
each accepted publication replaces only its own displayed projection. Missing
identities mean projection removal, not confirmed source cancellation or road
clearance.

## Presentation and release gates

Use neutral reported-nearby wording, existing 500/750 m hysteresis and two-fix
admission. Same-road/direction is unverified. Keep source labels, source-specific
age/status, full source text and uncertain schedules visible in parked details.
Use neutral incident symbols; existing roadworks sign art comes from shared
assets. UI strings remain aligned in DE/EN/FR/NL. Network requests still contain
region/snapshot identifiers only; no extra location stream or background jobs.

Feed adapters may only export verified explicit geometry and supported validity;
unsupported location references, ambiguous schedules and unknown enums are
quarantined or noneligible, never guessed. Unknown license/access terms and
unverified production schemas are per-source activation blockers. Synthetic
fixtures are identified as such and cannot serve as live-source acceptance.
No deployment, production scheduler, source activation or device installation
is authorized by this implementation task.
