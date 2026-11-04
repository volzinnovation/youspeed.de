# Reported road advisories v2 — 28 October 2026

Implementation on `codex/youspeed-v1.5-mobidata-bw`, with backend changes
in the existing `Woladen.de-analytics` repository. Backend deployment, production
schedulers, source activation and publishing remain postponed. The owner
subsequently authorized updated-client acceptance tests and in-place updates on
both attached devices. Both native apps remain version 1.5. Parking, charging,
sharing and transit integrations remain later product scope.

The owner selected **BW incidents as the first pilot after qualification** on
28 October 2026. BEMaS and both Autobahn feeds must remain disabled, and deployment
remains postponed. This records the conditional source selection; it does not
start intake, enable a runtime flag or authorize a scheduler.

## Delivered behavior

The existing initially-off roadworks preference now controls **Live road
advisories**, with matching English, German, French and Dutch wording on iPhone
and Android. Its stored preference and existing control identifiers are retained.
The new `/youspeed/live/v2/regions/DE-BW` endpoint and immutable hash-addressed
snapshots distinguish BEMaS, BW incidents, Autobahn short-term works and Autobahn
long-term works. Existing v1 API behavior and native v1 cache readers remain.
A v1 response cannot revalidate a v2 network request.

Before any future activation of `reported_active` incident reports, distribute
and verify native builds containing the validity-basis parser and report-expiry
presentation on both platforms. Earlier development v2 clients ignore these
additive fields and could describe the observation lease as an ordinary event
time range. Existing v1 clients retain BEMaS-only semantics. This is a client
release gate; no server activation or compatibility mechanism is changed here.

Each source has independent enablement, publisher/check clocks, freshness and
attribution. The aggregate status describes availability; it cannot grant a
feature driving eligibility. A failed or expired incident feed does not hide
healthy works. Disabled, removed, future-dated or clock-unknown sources cannot
keep an active driving card. Cache installation verifies the exact snapshot
hash/size, schema and complete source-ID set before replacing current data.

Incidents are fresh through ten minutes of source/check age, following the
official catalogue's ten-minute refresh description; they become unavailable
for driving after fifteen minutes of either age. Works retain the existing
thirty-minute fresh source-age threshold and twenty-four-hour maximum. These
are advisory rules and do not change the protected speed-reference policy.

Driving presentation remains one passive **reported nearby** text notice in the
existing dashboard, using the
existing GPS quality gates, two-fix admission and 500/750 m hysteresis. Source
name, age and delayed/offline state accompany the report. Parked details include
source health, attribution, original text, publisher record ID, validity and
direction uncertainty. Incident, hazard and congestion labels use neutral
wording. No new speed offer, camera confirmation, sound, speech, capture,
routing or “ahead on your road” claim is introduced.

The notice separates its short summary and distance from a source/age/status
line. A long road name may be shortened on the driving screen; the parked
Settings section retains the complete report. Both clients use the dashboard's
existing foreground palette. iPhone reserves the measured notice height in its
sign/metric layout so it stays above the bottom controls. These corrections
followed physical screenshot review, which caught invisible Android text and
truncated or overlapping iPhone text that semantic assertions alone had missed.

Downloads still contain only region/snapshot identifiers; proximity stays on
the phone. No additional location stream or background job is added. Full
contract: [`shared/roadworks/CONTRACT_V2.md`](../shared/roadworks/CONTRACT_V2.md).
Wire schemas: [OpenAPI v2](MOBIDATA_BW_ROAD_ADVISORIES_API_V2.openapi.json).

## Backend and source handling

The sibling backend owns source intake, the one-shot CLI, isolated raw archives,
accepted per-source generations and atomic combined snapshots. A failed source
refresh retains that source's accepted content and original clocks. Each accepted
incident publication replaces only its own displayed projection. Missing IDs are
projection membership removals, not confirmed source cancellations or road
clearance. Incremental/unsupported profiles are rejected; `allElementUpdate`
confirms records within an included situation, not global regional completeness.
Rollback binds report content to its own source-generation clocks. Retention
pins current/previous combined and source generations and their raw provenance.
No management database or sign-contribution identity is used.

DATEX adapters use the explicit profiles observed in current public samples:
LMS-BW comma-separated longitude/latitude geometry and MIA's declared EPSG4326
latitude/longitude `posList`. Ambiguous geometry, unsupported coordinates,
unknown validity and unsupported schedules are not guessed. Explicit source-active
incidents use bounded observation leases, with original source times preserved.
Nationwide MIA records outside the supported regional envelope are counted
separately from malformed records. Long XML uses bounded streaming parsing;
client snapshots remain limited to 8 MiB, 10,000 features and 200,000 vertices.

All source configurations default off. Reviewed schema and licence evidence
are required for activation; the operational status reports remaining blockers.
The incident catalogue identifies Landesmeldestelle BW and
[dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0).
Autobahn per-feed licensing was not established by this implementation's
catalogue queries and remains an activation gate. Synthetic fixture licences
are explicitly test-only and are not asserted provider permissions.

Backend details and local CLI commands are retained in
[`Woladen.de-analytics/docs/youspeed/ROAD_ADVISORIES_V2.md`](../../Woladen.de-analytics/docs/youspeed/ROAD_ADVISORIES_V2.md).
The normal intake entry point mounts both API versions. Local Caddy source
includes the explicit v2 route, and Compose source includes a separate
one-shot tool profile with the existing live volume and read-only configuration
mount. Empty configuration leaves every source disabled. These source files
were prepared and checked without applying host configuration. A later isolated
qualification job on **live-eu.woladen.de** used the actual Dockerfile and current
COPY inputs with the reviewed 1 GiB / 1 CPU / 64 PID limits. It exposed no ports,
mounted no production state or secrets, and changed no production service,
release, configuration or scheduler. Its candidate image and staging were
removed afterwards. All 12 existing containers retained their image, running
state and health. See the [container acceptance receipt](MOBIDATA_BW_CONTAINER_ACCEPTANCE_2026-10-28.validation.json).

## Initial source observations

The [source receipt](MOBIDATA_BW_ROAD_ADVISORIES_2026-10-28.evidence.json)
records URLs, HTTP clocks, decoded sizes, hashes and the BEMaS result. Raw
downloads stayed outside the repositories. These are individual observations,
not a cadence, service-availability or field-accuracy benchmark.

| Source | Decoded XML | Source members | Exported window features | Resolved / unknown schedules |
| --- | ---: | ---: | ---: | ---: |
| BW incidents | 1,495,703 bytes | 128 | 92 | 92 / 0 |
| Autobahn short-term | 50,512,307 bytes | 3,479 | 229 | 52 / 177 |
| Autobahn long-term | 229,312,195 bytes | 23,343 | 465 | 415 / 50 |

Exported is not equivalent to eligible: unknown event meanings and inactive
intervals still cannot produce a driving card. The incident sample additionally
had 29 unbounded active reports, four unsupported point references and three
suspended records. MIA records outside the supported envelope were excluded;
the adapter does not invent border clipping. Supported geometry/schedule
coverage requires further qualification before activation.

The unchanged BEMaS adapter accepted 852 window features from 996 source IDs,
quarantined four suspect Points, and retained **all 852 schedules as unknown**.
GeoJSON modification time was 14:40:13 UTC; XML publication was approximately
14:20:04 UTC. Their twenty-minute skew exceeds the existing fifteen-minute
pairing limit. That limit was preserved. Operational BEMaS readiness therefore
still depends on compatible source representations, not merely server polling.

## Release checklist and approval scope

Engineering must supply a source-specific acceptance receipt before proposing
activation. Owner approval selects the qualified sources and authorizes concrete
live operations; it does not certify technical facts or waive missing licence
terms. Existing approved advisory behavior does not need approval again.

- Record authoritative dataset rights, final attribution and the reviewed
  production schema/profile. Exercise actual updates, withdrawal/suspension,
  supported geometry, bounded validity, recurrence/DST, unknown enums and clocks.
  Synthetic fixtures and a successful single fetch do not establish acceptance.
- Measure publication/check age over repeated updates and verify source-isolated
  failure, expiry and rollback. Confirm partial coverage and uncertain direction
  remain explicit, with matching stale/offline behavior on both apps.
- Benchmark full HTTP ingestion, decompression, elapsed time and peak container
  memory against the configured limits; the provisional 1 GiB limit and local
  parser measurements are not production qualification. Include rollback and
  retention checks in the receipt referenced by `schema_evidence`.

| Source toggle | Evidence still required before activation | Recommended first pilot |
| --- | --- | --- |
| `bemas` | Compatible GeoJSON/XML generations within the retained 15-minute pairing gate. Later paired captures showed unchanged decoded content while HTTP clocks advanced; XML publication was over an hour older. Phase-expanded intervals also require qualification. | Keep off until compatibility is demonstrated; do not reinterpret unknown schedules as active. |
| `incidents-bw` | Functional qualification, the isolated live-eu container check and isolated physical native suites passed for the latest-publication positive subset; full regional completeness and cancellation from absence are unverified. Normal iPhone installation and its final smoke/preservation checks remain pending connection. | Owner-approved first pilot after qualification; keep runtime off while deployment is postponed. |
| `autobahn-short-term` | Authoritative per-feed rights and attribution, production profile and schedule qualification; 177 of 229 exported sample schedules were unknown. | Keep off until its own blockers clear. |
| `autobahn-long-term` | Same rights/profile evidence, schedule qualification and full production ingestion/resource measurement for the 229 MB decoded sample. | Keep off until its own blockers clear. |

For each MIA feed, obtain authoritative answers to whether the terms permit
YouSpeed's intended app use, normalization and public redistribution of derived
snapshots; local caching, raw archive/rollback retention; and the proposed source,
licence and modification notices. Establish any publisher approval, access or
additional conditions before entering real `license_evidence` and attribution.
The candidate official catalogue entries for
[short-term works](https://mobilithek.info/offers/641235133820284928) and
[long-term works](https://mobilithek.info/offers/641228542228467712) are discovery
leads: their current per-feed terms remain unverified. Public download access
and the separate Autobahn App's licence do not establish these permissions.

The owner has conditionally selected `incidents-bw` as the first pilot after
qualification; that source-selection decision does not need to be requested
again. Keep the other three flags off. Before live operations, present the exact
qualified source-registry JSON diff and the deployment scope for review. Separately identify
the target host, image/configuration and proxy changes to deploy; any scheduler's
cadence and resource limits; and the rollback/stop plan. Approval must name those
operations rather than grant a blanket exception to the gates. App installation
and publication remain separate operations. This checklist changes no source
flags and authorizes no activation, deployment or scheduler.


## Incidents-first qualification follow-up

The first actual HTTP sample at 19:37:33 CET (18:37:33 UTC) contained 120 records:
92 bounded exports, 23 active reports without an end time, four unsupported point
references and one suspended record. Only 63 bounded exports were eligible at
that instant; no accident or congestion report survived. Treating that result as
complete current-incident support would hide an important coverage gap.

The qualification change explicitly represents DATEX `active` as a
`reported_active` observation lease tied to the source publication, with a
maximum 900-second expiry and the existing independent source freshness gates.
It retains the original source validity times and never labels lease expiry as
the event end. DATEX defines `active` as overriding its time specification;
see the [DATEX II v2 validity enumeration](https://docs.datex2.eu/_static/data/v2.2/umlmodel/html/EARoot/EA2/EA3/EA6/EA315.htm).
Unknown statuses and non-real/test/exercise reports are excluded. The observed
per-situation update profile is pinned and incremental or missing declarations
are rejected; this does not establish global upstream completeness. iPhone and
Android must use identical validity semantics
and parked-detail wording. V1 and BEMaS pairing rules remain unchanged.
The client release gate above requires updated builds before activation. The
later device-acceptance work is separately authorized and leaves source
activation and backend deployment postponed.

A subsequent publication at 19:41:47 CET demonstrated two record additions, one
disappearance and three changes from the earlier sample. Disappearance means
only absence from that HTTP publication. DATEX II defines `allElementUpdate`
at the situation level; a global `snapshot` has different semantics. Full-feed
recall/completeness remains outside this pilot qualification. The official
[ten-minute LMS catalogue](https://www.govdata.de/suche/daten/kopie-von-verkehrsmeldungsdaten-der-landesmeldestelle-bw-aktualisierung-alle-10-minuten)
describes a complete dataset, but its exact linkage to this IPL DATEX resource
was not established. The public integration configuration leaves the upstream
URL in an externally supplied variable; broader completeness claims remain
unqualified. These are bounded
qualification observations, not a service-availability guarantee or a claim
that disappearing reports prove the road reopened.

Autobahn rights findings are now established at the catalogue/access level in
the [licensing receipt](MOBIDATA_BW_AUTOBAHN_LICENSING_2026-10-28.evidence.json):
both offers specify restricted, free use, publisher approval and the source note
“Die Autobahn GmbH des Bundes | MIA”. The public metadata does not supply the
applicable full licence, redistribution/cache/retention rights or a permission
grant for the MobiData mirror route. No subscription or terms acceptance was
performed; both feeds remain disabled.


The BEMaS [timing investigation](MOBIDATA_BW_BEMAS_TIMING_2026-10-28.evidence.json)
observed HTTP modification clocks and ETags advance across two complete paired
exports while both decoded GeoJSON/XML bodies stayed identical. XML publication
was more than an hour older than the mirror timestamps. Both unchanged-adapter
runs exported 840 window features, all schedule-unknown, and quarantined four
suspect Points. A separate historical comparison found phase-expanded GeoJSON
intervals: 132 match individual compiled XML phases, while other mismatches
remain. These are separate qualification issues. The 900-second clock guard
was preserved, and BEMaS remains disabled. The mirror's internal export/delay
cause was not established.

Functional qualification is restricted to **positive reports in the latest
accepted publication**, with partial geometry/type coverage. It does not certify
regional completeness, physical event truth, or cancellation from absence.
The acceptance receipt records repeated HTTP captures, 200/304 clocks, record
membership changes, explicit suspensions and replay. Actual normalized output
was parsed, installed and eligibility-checked by both native clients.

Final checks passed: **70 backend tests, 24 iPhone Simulator tests, 19 Android
JVM tests and six shared-contract tests** (23 subtests), with no failures or
skips. The captured final sample had 120 source records, 111 exports (19
`reported_active`), 78 eligible reports at capture, four unsupported Point
profiles and five explicit suspensions. Its enabled incident flag exists only
in an isolated native acceptance fixture; no runtime registry was activated.

The later isolated live-eu check completed real HTTP ingestion, decompression,
SQLite projection and snapshot generation in 0.758 seconds, with a measured
90.97 MiB peak container memory footprint. API/cache, failure, expiry, rollback
and retention checks passed. This qualifies a short incident payload; it does
not establish sustained load, maximum valid payloads, BEMaS or Autobahn resource
qualification. The first attempted local container workflow was stopped after
the owner clarified the hosting boundary; no local backend test container
completed and OrbStack was returned to its initial stopped state. Deployment
and scheduling remain postponed. No source-selection approval needs to be
repeated for the already authorized incidents-first scope.

Full evidence: [incident pilot qualification](MOBIDATA_BW_INCIDENT_PILOT_QUALIFICATION_2026-10-28.evidence.json).

The one-shot research tool `scripts/research/qualify_bw_incidents.py` captures
through the owning backend adapter into an isolated evidence directory. Its
`--replay-receipt` option re-evaluates captured bytes without network access.
Neither mode edits runtime configuration or creates a recurring job.


## Attached-device acceptance follow-up

The [Android receipt](MOBIDATA_BW_INCIDENT_ANDROID_ACCEPTANCE_2026-10-28.evidence.json)
records **15/15 physical tests**, including six controller/store ANR regressions,
and the in-place **1.5 build 10080** installation. The installed APK hash matches
the built artifact. Critical data, the active map hash and prelaunch inventory
were preserved; normal Settings visually retains the advisory switch off.

The [iPhone receipt](MOBIDATA_BW_INCIDENT_IPHONE_ACCEPTANCE_2026-10-28.evidence.json)
records **38/38 physical tests**, with no skips, including parser/service,
generation/persistence/journal concurrency, and actual dashboard/parked views.
Six watermarked dashboard images cover portrait/landscape and three existing
warning palettes. Rendered-text recognition checks source, full age, distance,
road text and clearance above the controls; manual image review confirmed the
final result. Captured source data and synthetic telemetry are confined to the
isolated test host. They are not current live incidents.

The iPhone backup contains 5,681 user-state/media/log files (10,070,247,943 bytes),
with SHA-256 records and successful checks of all three copied app databases.
The complete 8,479-entry support inventory and 17 critical files are prepared
for prelaunch comparison. Immutable installed maps remain on the device;
their bytes were not all redundantly copied or hashed.

**Normal iPhone installation remains pending.** The phone disconnected before
the install command could find it, so that attempt performed no installation.
The last verified normal app is 1.5 build 10077; the signed normal build 10080
is ready. Postinstall preservation and normal Settings/foreground smoke checks
must follow reconnection. Backend deployment, scheduling and all live-source
activation remain postponed. BEMaS and both Autobahn feeds remain disabled.

## Initial implementation validation (before the follow-ups)

- Shared OpenAPI/fixture/schema/checksum checks: 5 passed, including v1 wire
  compatibility and inconsistent v2 source metadata rejection.
- iPhone: 17 targeted XCTest cases on an isolated iOS 26.5 iPhone 17 Pro
  simulator, covering real service/cache lifecycle and parser/relevance gates.
- Android: 12 targeted JVM cases passed; instrumentation test sources compiled.
  The newly written instrumentation regressions were not run on a phone.
- Backend: 46 targeted cases passed in the owning repository after the guarded
  patch was applied. They cover normalization, source-isolated refresh/failure/withdrawal, clock
  ageing, XML safety/bounds, generation retention/rollback and v1/v2 API tests
  plus normal intake startup, default-off configuration, and source-only
  proxy/Compose preparation. Docker/production configuration was not activated.

The final [validation receipt](MOBIDATA_BW_ROAD_ADVISORIES_V2.validation.json)
records the original source hashes and commands. The later physical-device and
isolated live-eu receipts above supplement that historical evidence.
