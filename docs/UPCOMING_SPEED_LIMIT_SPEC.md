# Upcoming lower speed limits on the followed road

Status: product specification; implemented in the working tree. Validation and
the local BW 1.5 bundle are recorded in
[the implementation record](UPCOMING_SPEED_LIMIT_IMPLEMENTATION.md).
Date: 23 October 2026. Applies equally to iPhone and Android.
Assessment: current working tree, including the local v1.5 sign-runtime work.

24 October repair: the owner's missing-preview request adds explicitly sourced
map-boundary previews to the physical-station implementation below. A verified
plain numeric OSM tag at a certified cross-way boundary may supply a candidate
with `sourceID=osm-road-tag`, its actual source snapshot, and an
`osm-road-boundary:<way>:<direction>` identity. It must share the followed
relation and cannot contain unresolved conditional/vehicle-specific maxspeed
tags. It never represents a physical sign or changes current authority.
Unique contiguous segments of the same directed way can continue through side
junctions when geometry/access are verified and no restriction barrier exists.
Different-way choices retain the certified unbranched successor requirement.
All existing horizon, freshness, lower-value, passage and display guards apply.

## 1. Requested behavior and feasibility

Show one upcoming **lower numeric speed limit and its remaining distance** when
the sign is ahead on the road/relation being followed within a **30-second
driving window, with a minimum distance of 300 m**. This replaces the original
300 m ceiling following the product owner's first-drive feedback on 23 October
2026. Place it in the app's lower-left corner in landscape and
at the lower-left of the current speed-limit sign in portrait. Remove it when
the vehicle leaves that road/relation or reaches/passes the sign.

**Same-way offline lookup is feasible with the sign-enriched v3 bundle.** Its
optional
`traffic_sign_capability.version=1` tables contain accepted physical sign
stations, travel direction, numeric values and applicability intervals. Existing
indexes support a small current-way query. Both apps already have matched-way
geometry, chainage and route-relation memberships; neither exposes this preview
in the baseline assessed here. Reliable cross-way lookup needs an additional directed topology
capability: existing links use rounded endpoint coordinates and omit interior
junctions and turn restrictions. Section 6.2 specifies that extension. This is
a bundle-data gap, not an expensive-query problem.

**This is not universally available in ordinary road bundles.** Base v3 contains
way-level speed tags, geometry and optional continuity/topology, but does not
establish a physical numeric sign station. A speed change at an OSM way boundary
does not prove a sign is there. The first implementation uses verified physical
stations from the optional sign runtime. Unsupported regions quietly omit the
preview. General map-derived speed-change previews would be a distinct later
data contract, with explicit boundary provenance rather than an invented sign.

The feature is automatic when supported offline data and reliable matching are
available. It requires no new setting, preview-triggered download, network
service, camera mode, audio alert or interaction while driving. Existing bundle
installation and network rules continue to apply.

## 2. Eligibility and selection

All conditions must hold for a visible preview:

| Condition | Requirement |
| --- | --- |
| Distance | Unrounded along-road distance is strictly greater than 0 and at most `max(300, observed_speed_kmh / 3.6 * 30)` metres |
| Direction | The physical sign's accepted approach matches the directed path |
| Road scope | The target is on the current way or a proven continuation of the frozen followed relation scope, as defined below |
| Source | Supported runtime capability; accepted physical association; static finite integer speed in the runtime's supported 1–300 km/h range; source/snapshot and bundle identities retained |
| Applicability | A unique accepted origin rule and post-station bundle offer, `lane_scope=all`, with the same direction/station and numeric value; no known unresolved conditional, dynamic, vehicle or lane restriction |
| Current limit | Compare against the final effective current limit shown by the main sign, after camera, voice and bundle resolution |
| Lower value | Upcoming numeric km/h is strictly less than the current numeric km/h; an authoritative unlimited current limit compares as infinity |
| Reliability | Fresh location, stable road match, usable source geometry and resolved direction; no pending/ambiguous road context |

The vehicle speed determines the search distance only. Do not compare the
upcoming limit with vehicle speed, a raw OSM tag beneath a camera/voice override,
a pending camera candidate, or a last-known/stale main value. Hide when the
current value is unknown, stale, walking/special, or obscured by speed-capture
entry. A camera or spoken correction can change eligibility without movement;
recompute the comparison whenever the effective main reference changes.

Choose the **nearest eligible lower physical station**, not the lowest number
in the window. For example, with current 100, signs 80 at 120 m and 50 at 240 m
show 80 / 120 m. Equal/higher numeric signs are not previewed; after reaching one,
the normal current-limit update causes eligibility to be evaluated again. Read
intervening events before selecting: stop at a town/reset/end boundary or known
unresolved applicability event rather than skipping it to advertise a lower
limit whose context cannot yet be established. A supported numeric sign at the
same physical station as a boundary requires the existing explicit event
ordering and a unique post-boundary offer; otherwise wait until after it.

Deduplicate repeated evidence for the same physical sign. Conflicting applicable
values at a station suppress that station and targets beyond the conflict.
Use the runtime builder's station clustering convention (currently 1 m) for
conflict checks; an arbitrary row order or `LIMIT 1` must not resolve a conflict.

The current runtime's accepted/all-lane classification is evidence about the
known bundle semantics, not proof of complete physical signage. The inventory
can omit supplementary plates and the runtime has no complete vehicle/time
applicability envelope. Preserve these source limitations in diagnostics; never
infer unconditional real-world applicability merely from a missing plate. Source
updates should retain explicit applicability/unknown status. The preview makes
the same qualified map-data claim as the existing bundle resolver.

Resolve the offer immediately after the station using existing forward/reverse
interval endpoint ownership and co-station ordering. A zero-length or shadowed
origin rule without a verified continuing numeric offer is not sufficient for a
preview that promises a current-limit handoff.

## 3. Followed road, relation and distance

### 3.1 Scope identity

An OSM **way** is a geometry element. A connected road-relation group is a set of
ways in the same connected component of an OSM road route. The bundle's
`route_relation_connected` membership is unordered and contains no chosen future
turn. `same_street_name_connected`, equal names/refs, nearby geometry or matching
relation ID alone cannot establish a directed path.

At candidate acquisition retain:

- Bundle identity/revision, drive session and a preview traversal generation.
- Current directed way and its raw connected route-relation group/source IDs.
- The target physical sign ID, source snapshot, origin way, direction and station.
- The ordered directed path to that target and its distance origin.

Freeze the initial eligible relation groups and narrow them by intersection with
each subsequent raw matcher result and every traversed way. Never add newly
encountered memberships to an existing preview. In particular, memberships
`{A}` → `{A,B}` → `{B}` cannot retain A's preview through B. A connected group ID
is scoped to its bundle; it is not a global road identity.

When a way has no verified road-relation group, same-way lookahead is still
valid: leaving that way clears it. Cross-way retention then remains unavailable.
With the proposed topology capability, a normal OSM way split within a verified
followed relation does not clear the preview if the directed continuation and
target remain established. Current v1-only bundles clear/reacquire at way changes.

Do not reuse `TrafficSignTraversalTracker` as the sole scope test. It deliberately
allows broader road-identity continuity and retains memberships in some missing
same-way contexts. Preview visibility must validate fresh raw context itself.

### 3.2 Bounded path ahead

Start from the matched projection and travel direction. Inspect the remaining
part of the current way, then only proven, permitted directed continuations
within the frozen common relation scope, until the speed-dependent path budget
is used.

Calculate `lookahead_distance_m = max(300, observed_speed_kmh / 3.6 * 30)`
from the observed driving speed already supplied with the accepted map lookup.
Use the unrounded result for every event query and final eligibility check.
Missing, negative or nonfinite speed, or overflow in the calculation, falls back
to 300 m. Zero and low speeds also retain this 300 m floor. There is no fixed
distance ceiling. Recalculate on each accepted fix; an older lookup retains its
own horizon rather than being reinterpreted using a newer speed.

| Observed speed | Search distance | Nominal notice at constant speed |
| --- | ---: | ---: |
| 30 km/h | 300 m | 36 s |
| 50 km/h | 416.67 m | 30 s |
| 80 km/h | 666.67 m | 30 s |
| 100 km/h | 833.33 m | 30 s |
| 130 km/h | 1,083.33 m | 30 s |

Thirty seconds is the search target where verified sign coverage and directed
path evidence are available. It is not a guaranteed warning period: the first
qualifying fix, lookup delivery, acceleration, missing source coverage and
conservative junction/applicability stops can shorten actual notice. Increasing
the horizon must not guess a future turn or bypass an unresolved event. The
existing BW topology stores complete segment/successor decisions independently
of distance; this client change does not require a larger bundle or rebuild.

With the proposed source-node topology capability, lookup may cross **ordinary
unbranched, unmerged way splits** whose direction/access metadata, geometry and
relation scope are all available. Existing v1 sign-runtime data alone must stay
on the current way. Stop before forks, merges, uncertain junctions, missing
direction/access, cycles, missing geometry or coverage boundaries. Do not guess
a turn from nearest geometry, way ID, a shared name/ref, global way heading or
relation member enumeration. A sign before such a stopping point remains
eligible. Further junction-aware traversal needs resolved unique legal
continuation within the same relation; current relation tables cannot prove it.

Endpoint-only topology does not describe every interior-vertex junction or turn
restriction. Its absence must not be reported as proof of unrestricted routing.
Same-way prediction means continuing on the currently followed way; it is
withdrawn as soon as fresh matching no longer establishes that approach. A
propagated `traffic_sign_rule_path` describes an existing rule's downstream
continuation heuristic, not proof of an upcoming sign's approach or a substitute
for the proposed topology capability.

Use a visited directed-segment set and a hard maximum of 32 path segments per
lookup, including the current segment and any endpoint-passage marker. Keep
the existing 25 ms traversal deadline. Reaching a work cap hides targets beyond that point; it cannot
return a candidate from an incomplete or guessed path. There is no whole-relation
scan, shortest-path search or route planning on each GPS fix.

### 3.3 Distance and projection

On the same way:

```text
remaining_m = direction * (physical_station_m - current_chainage_m)
direction = +1 along stored geometry, -1 against it
```

Across ways sum the remaining current-way length, complete intervening way
lengths, and the destination station's distance from its directed entry. Stored
geometry orientation may change at a split; each edge has its own direction.
Use the runtime's source-segment chainage convention: spherical segment lengths
with radius 6,371,000 m; local projection chooses the segment and fractional
position. Reuse existing projection/cache code, including its bend handling.

Direct GPS-to-sign distance is not the display distance or the adaptive range gate. Do
not expand the gate using GPS accuracy or the sign's existing 10/30 m geofence.
Reuse primary inventory evidence gates: stable match, horizontal accuracy ≤25 m,
projection within 25 m, heading accuracy ≤35° and approach alignment ≤35°. Freshness
must use the existing accepted-fix checks. The preview also expires no later than
3 seconds after its last accepted location timestamp, using a timer even if no
new lookup arrives. This is a preview-only freshness limit; it does not change
the primary reference policy or permit future-dated fixes.

## 4. Presentation

| Layout | Placement |
| --- | --- |
| Landscape, both saved mounts | Lower-left safe area of the full dashboard, inside the left sign pane; screen position stays the same for either mount |
| Portrait | Compact block immediately to the lower-left of the current main sign, within the upper sign pane; keep the main sign centered |

Use a smaller schematic numeric sign with a distance caption such as **in 120 m**.
Start with a 56–64 pt/dp sign and a readable 14–16 pt/sp caption, constrained by
the existing layout and accessibility scaling. The current main limit remains
the dominant sign. Keep the preview separate from the retained upper-left
secondary-sign surface, supplementary restriction text, eye decoration, recorder
status and bottom action controls. It remains visible in telemetry and dashcam
preview modes, with camera/TSR on or off.

Round the distance **up to the next 10 m** only for presentation; show **in <10 m**
for `0 < remaining_m < 10`. At the 300 m minimum window, 300.1 m is hidden;
at 100 km/h, 800 m is eligible. A remaining 299.1 m displays 300 m, and
9 m displays <10 m. Never display a retained `0 m` or negative distance. Do not
smooth a distance across passage or relation departure. Distance can increase
slightly with valid projection changes; do not fabricate monotonic progress.

Use existing numeric sign styling without current-speed penalty/overspeed
coloring or camera-confirmation decoration. A preview is not an observation or
an active speed reference. It has no tap/long-press action. On supported compact
screens and enlarged text, reserve or reflow space for both current and upcoming
values; avoid covering a supplementary plate or shrinking the main sign to an
unreadable size. Missing preview collapses its own space without moving controls.

Localize the distance caption and accessibility description in English, German,
French and Dutch. A single accessible element says, for example, “Upcoming speed
limit, 70 kilometres per hour, in 120 metres.” Keep numeric/distance meaning
available without color; do not produce automatic spoken countdowns.

## 5. Lifetime and handoff to the current limit

The preview is transient presentation state independent of primary-reference and
retained secondary-sign state. Keep a separate directed-traversal passage ledger;
hiding presentation or invalidating asynchronous work does not reset that ledger.
Evaluate these transitions on each accepted fix, effective-limit change,
lifecycle change and preview freshness timeout:

| Event | Required behavior |
| --- | --- |
| Eligible target enters `0 < distance ≤ lookahead_distance_m` | Show the nearest lower station and current distance |
| Same directed path, fresh fix | Update distance; reevaluate eligibility and nearer candidates |
| Current effective limit becomes equal to/lower than target | Hide; a later valid main-limit change can make it eligible again |
| Ordinary verified split on frozen relation path | With the new topology capability, retain target identity and recalculate; v1-only fallback clears/reacquires |
| Match departs frozen relation/path, reverses, becomes unstable/unknown, or enters pending road context | Clear at that result; no 8-second primary-reference departure grace |
| Invalid/stale fix, expired preview timestamp, lookup failure or pause | Clear; reacquire only from fresh accepted context |
| At or beyond target station | Clear and mark physical passage consumed, including retained candidates currently hidden by `not_lower` or a temporary gap |
| Stop/start drive, background/resume, country/bundle change or capability loss | Clear and invalidate outstanding results; reacquire after fresh context |

At passage the sign's rule becomes the **current bundle offer** through the
existing active-interval resolver. When bundle authority is selected, this is
the new main speed limit. Publish the cleared preview and new effective main
state from the same committed lookup, including endpoint stations shared by two
ways. Do not wait for the next geofence encounter to discover a rule already
crossed; validate endpoint ownership/continuation when implementing this handoff.

The protected [speed-reference policy](speed-limit-reference/MODEL.md) currently
prioritizes speech, then applicable camera, then bundle. An active higher-priority
claim can therefore keep the main display different after map-sign passage.
The preview must still disappear at passage. Unconditional replacement of
camera/voice authority would require a separately named policy change under
[`shared/speed-limit-reference/AGENTS.md`](../shared/speed-limit-reference/AGENTS.md).
This specification requests no policy edits, artificial reset/boundary events,
or fabricated camera observations for a numeric preview.

A fresh fix beyond a station after a gap clears/rejects the old preview and lets
normal current-rule resolution run; it does not prove an observed camera passage.
Keep consumed physical sign/direction identities until the preview traversal
ends so GPS jitter cannot resurrect a passed sign. A genuine later approach after
leaving/reentering or a direction change starts a new verified traversal; an old
asynchronous result or mere loss of GPS cannot reset passage memory. A sign may
be eligible on a genuine later circuit, never by replaying stale context.
Pause, background/resume, hidden UI and `not_lower` also preserve passed identities
within the drive. Only a new drive or independently proven new directed approach
rearms the station. Keep the passage ledger's traversal identity separate from
the generation used to cancel stale lookup completions.

## 6. Existing bundle contract and efficient retrieval

| Existing data | Use / limitation |
| --- | --- |
| `ways`, `way_geom`, `way_endpoints` | Base speed tags, full polyline, length and endpoint lookup; no general physical numeric sign location |
| `way_continuity_group`, `way_continuity_membership` | Indexed connected relation membership/source relation IDs; no ordering, member roles or turn choice |
| `traffic_sign_runtime` | Physical source identity, numeric value/unit/status, coordinates and provenance |
| `traffic_sign_association` | Physical origin way, direction and `station_chainage_m`; only accepted associations may supply a target |
| `traffic_sign_way_rule` | Applicability interval and accepted/all-lane speed; verify the physical origin rule |
| `traffic_sign_way_direction` | Permitted motorcar directions, endpoints, lengths and preserved directional/lane tags |
| `traffic_sign_rule_path` | Propagation provenance; its child entry station is not another physical sign |

**Critical distinction:** continued rules put `station_chainage_m` at each child
way's entry while retaining the original sign ID. Querying rule stations alone
would invent repeated upcoming signs. Start with physical associations and join
the matching **origin** rule, not propagated child rules. Check original source
station bounds and reject malformed/nonfinite values before distance arithmetic.

The two clients currently differ in query shape: iPhone resolves active intervals
and geofence signs; Android already loads accepted current-way directional rules.
Both need the same physical-station candidate semantics. Do not enlarge the
existing encounter geofences or reuse retained secondary presentation as a cache.

### 6.1 Retrieval plan

1. Inspect supported capability, required columns and index availability once
   when opening a bundle. Optional/malformed/unknown capability returns no preview
   and does not prevent ordinary driving behavior. Never repair downloaded DBs
   in place.
2. After final way selection, use the existing serialized read-only connection,
   statement cache and source geometry cache. Query physical events on the
   directed current-way interval; only the new topology capability permits
   extending to bounded proven continuations.
3. Fetch all located directed events in station order before lower-limit selection,
   including nonaccepted associations that retain a station. Only accepted events
   can qualify as targets; a positioned unresolved/conflicting primary-control
   event blocks targets at/beyond it. Resolve physical origin rules by indexed
   way/direction and sign identity, and validate source semantics. Do not filter
   SQL to `speed < current` and silently skip conflicting/intervening events.
4. Cap each path segment at 256 returned physical events. Fetch one extra row to
   detect overflow; an incomplete segment cannot justify a target at/beyond its
   truncated portion. Log and hide the segment on overflow rather than choosing
   a potentially incorrect “nearest” candidate. Do not resolve a partial
   co-station cluster as though it were complete.
5. Return a compact candidate snapshot. In the controller compare it with the
   final effective reference. Recheck on camera/voice changes without another DB
   query if the location/path snapshot remains fresh.

Existing association indexing is `(way_id,direction,status)`; it narrows to one
directed way but does not range-seek chainage. The optional future bundle-builder
optimization is an additive index, with no table/schema-version change:

```sql
CREATE INDEX idx_traffic_sign_association_station
ON traffic_sign_association(way_id, direction, station_chainage_m, sign_id);
```

Use separate forward/reverse range statements, rather than an absolute-distance
expression or an `OR` over directions. For a forward segment, the physical-event
query shape is:

```sql
SELECT a.sign_id, a.status, a.station_chainage_m,
       s.kind, s.sign_code, s.numeric_value, s.unit, s.parameter_status,
       s.source_id, s.snapshot_sha256
FROM traffic_sign_association AS a
JOIN traffic_sign_runtime AS s ON s.sign_id = a.sign_id
WHERE a.way_id = :way_id AND a.direction = 1
  AND a.station_chainage_m > :current_chainage_m
  AND a.station_chainage_m <= :segment_end_m
ORDER BY a.station_chainage_m ASC, a.sign_id ASC;
```

For reverse travel use `< :current_chainage_m`, `>= :segment_end_m` and descending
station order. A destination way includes its entry station once; the current
way query excludes the current station to avoid previewing an already-current
limit. Separate event evaluation handles passage at an exact station and
co-located boundary ordering. Validate zero-length/endpoint interval behavior in
both native clients.

The measured bundle contains 1,169 positioned `conflicting_source_values`
associations, including 1,145 numeric signs. Reading only `status='accepted'`
would miss those barriers. Unlocated/unknown-direction rejected signs cannot
safely be attached to the current path as barriers; this limits data coverage
and must not be resolved with a nearest-road guess.

Existing bundles can use their original index and sort the small selected way
set. If representative performance passes, the additional index is an optional
scaling improvement, not a new download prerequisite. Builders may add it on a
later rebuild; clients must not create it on the driving path.

### 6.2 Topology extension for relation-wide coverage

Add an independent optional `upcoming_path` capability, version 1, to a v3 bundle
rebuild. This contract is absent from the original measured bundle and is
implemented in the separate BW lookahead bundle. The concrete schema and
certificate statuses are defined in
[`upcoming_path_v1.md`](../mapdata/spec/upcoming_path_v1.md) and
[`upcoming_path_v1.sql`](../mapdata/spec/upcoming_path_v1.sql). Keep
`traffic_sign_capability.version=1` and its existing semantics unchanged. Pin the
new capability to the same road source/revision, geometry/chainage convention
and association snapshot as the sign runtime. Older apps ignore additive tables;
new apps use same-way fallback if this capability is absent, unknown or invalid.

The builder must preserve original OSM node IDs and incidence at **every** road
junction, including interior vertices, plus motorcar access/oneway and
turn-restriction evidence. A geometric crossing without a shared source node is
not connectivity. Clip boundaries, incomplete incidences and unsupported
conditional/via-way restrictions remain explicit stops. Do not infer permission
from a unique rounded-coordinate endpoint neighbor.

Minimum logical tables/fields for the additive capability:

| Table | Required fields / indexes |
| --- | --- |
| `upcoming_path_segment` | Segment ID, source way ID, direction, ascending start/end way-chainages, source start/end node IDs, length, permission/completeness status; index `(way_id,direction,start_chainage_m)` |
| `upcoming_path_successor` | From directed segment, status (`certified` or `stop`), nullable to directed segment, source via-node and incidence/restriction proof; primary key on from directed segment |
| `upcoming_path_capability` | Version, source hashes, geometry convention, supported access/turn semantics and validation report identity |

Split lookup segments at source junctions and relevant access-scope changes,
without rewriting OSM way IDs or existing matcher/association chainages. Map the
vehicle and physical sign station to these segments; each sign remains anchored
to its original association. Assign entry/exit stations deterministically so no
sign appears twice. Missing successor rows mean stop. Keep relation membership
checks separate and intersect the frozen scope on every segment/way.

For version 1, emit `certified` only for a proven ordinary split with complete
source incidence, exactly one forward continuation, no extra incoming merge,
known permitted access/direction, and no unresolved ordinary/conditional/via-way
restriction touching it. Junctions are stops even if the road name seems to
continue. A future version may admit a junction with one proven legal successor
inside the frozen relation scope; multiple valid choices need an actual selected
route. Member order alone cannot establish that choice.

Resolve successors offline in the builder. Runtime work becomes indexed segment
selection plus indexed successor reads and physical-event range queries, bounded
by the speed-dependent distance, 32 path segments and the event cap. Validate full source-node incidence,
direction/turn evidence, source hashes/station bounds and every declared
successor; test interior side roads and grade-separated coincident coordinates.
The full relation feature is complete only after this capability, both client
readers and cross-way acceptance pass. Same-way fallback is a first increment,
not complete relation-wide support.

### 6.3 Measurement and limits

Repository inspection and local read-only database measurements are recorded in
[`UPCOMING_SPEED_LIMIT_BUNDLE_EVIDENCE.json`](UPCOMING_SPEED_LIMIT_BUNDLE_EVIDENCE.json).
The BW runtime DB is 2,122,903,552 bytes with 1,085,790 ways and 172,304 source
signs. It contains 52,377 distinct accepted all-lane physical numeric speed
signs; 30,858 have origin ways in road-relation groups. Accepted associations
per directed way have median 1, p95 3 and maximum 48. The existing indexed numeric
candidate query, over 1,000 source-way samples after 100 warmups, took median
0.0223 ms, p95 0.0362 ms and maximum 0.0932 ms. It uses the existing association
index, source-sign primary key and rule way/direction index, plus a small sort.
This prototype filters to numeric candidates and does not inspect intervening
boundaries/conflicts; its SQL is evidence of retrieval cost, not the selector.

A second measurement reads **all statuses** in each physical event window plus
the directed way's accepted rule rows: over the same 1,000 cases it took median
0.0337 ms, p95 0.0584 ms and maximum 0.7080 ms, including row materialization.
It returned at most 13 events/window and 20 rules/way in this sample and retained
9 nonaccepted event rows. This is closer to the specified production read shape;
semantic selection and path/controller work remain outside the measurement.

Desktop query timing does not establish device lookup latency or driving
accuracy. Before enablement, measure the complete addition, including path
construction, source geometry decoding, rule validation and controller
publication, on both phones.

Proposed device budgets: at most one additional lookahead calculation per accepted
map lookup, no UI-thread I/O, warm p95 added lookup time ≤5 ms, p99 ≤10 ms, and
cold computation ≤25 ms for the bounded 32-segment path. Keep preview cache memory
within 1 MiB beyond existing map/geometry caches. These are acceptance targets,
not measured results. If a deadline/work cap is reached, keep ordinary matching
responsive and omit the preview. Record cold and warm timings separately.

## 7. Client integration

Add an optional `UpcomingSpeedLimit` model with: bundle/session/lookup token,
fix timestamp, preview traversal generation, frozen relation scope, ordered
directed path, physical sign/source/snapshot ID, origin station, rule ID, numeric
km/h and unrounded remaining distance. Keep 64-bit OSM IDs intact across Swift,
Kotlin, SQLite and diagnostic serialization. Raw candidates must remain distinct
from the final visible selection.

| Concern | iPhone reference | Android parity |
| --- | --- | --- |
| Physical events/projection | [`InventorySignRuntime.swift`](../iphone/SpeedConsumerApp/InventorySignRuntime.swift) | [`InventorySignRuntime.kt`](../android/app/src/main/java/de/youspeed/android/alpha/InventorySignRuntime.kt) |
| Final matched road, relation metadata | [`V3SpeedLimitService.swift`](../iphone/SpeedConsumerApp/V3SpeedLimitService.swift), [`MatcherCoreModels.swift`](../iphone/SpeedConsumerApp/MatcherCoreModels.swift) | [`V3SpeedLimitLookup.kt`](../android/app/src/main/java/de/youspeed/android/alpha/V3SpeedLimitLookup.kt) |
| Effective comparison, invalidation, atomic publication | [`DriveSessionViewModel.swift`](../iphone/SpeedConsumerApp/DriveSessionViewModel.swift) | [`ConsumerSessionController.kt`](../android/app/src/main/java/de/youspeed/android/alpha/ConsumerSessionController.kt) |
| Presentation | [`MainView.swift`](../iphone/SpeedConsumerApp/MainView.swift) limit pane | [`ConsumerAppUi.kt`](../android/app/src/main/java/de/youspeed/android/alpha/ConsumerAppUi.kt) limit pane |

Use existing latest-result guards plus a preview context generation. Clearing on
departure, stale location or bundle/lifecycle change invalidates in-flight work.
A completion for an old fix, session, bundle, generation or current scope cannot
restore a preview. Serialize current-limit comparison with publication; a camera
change between query start and commit must use the new effective main value.

Local diagnostics should retain candidate identity/direction/station, computed
distance and `horizon_m`, path/scope, current comparison value/source, capability,
lookup duration and a reason such as `visible`, `not_lower`, `outside_horizon`, `passed`,
`left_scope`, `ambiguous_path`, `stale_fix`, `unsupported_bundle`,
`unresolved_applicability`, `conflict` or `budget_exceeded`. Emit transitions
through existing diagnostics; no new network telemetry, contribution sighting,
camera-confirmation record or capture trigger follows from a preview.

## 8. Acceptance and implementation sequence

Create shared synthetic event/path scenarios consumed by both native suites.
Exercise the existing complete inventory/interval resolver and the controllers,
not only a standalone distance helper.

| Scenario | Expected result |
| --- | --- |
| Minimum 300 m window, 100 current, 70 at 300.1 / 300 / 0.1 / 0 / -1 m | Hidden / visible / visible with <10 m / cleared / cleared |
| Observed 50 / 100 / 130 km/h; lower target exactly at adaptive boundary | Visible at 416.67 / 833.33 / 1,083.33 m; just beyond each unrounded boundary is hidden |
| Observed speed changes between accepted fixes | Recalculate window while preserving passage memory and the independent main-limit comparison |
| 70 current, upcoming 70 or 100 | Hidden |
| 50 current by camera, 70 upcoming, OSM base 100 | Hidden; comparison uses main 50 |
| Authoritative unlimited current, 120 upcoming | Visible; unknown, stale or walking current hides |
| 100 current, 80 at 120 m, 50 at 240 m | Nearest lower 80; reevaluate after passage |
| Bend/hairpin, parallel road, opposite sign face | Along-road distance and accepted direction decide; proximity alone never qualifies |
| Reverse travel and opposite geometry orientation at split | Correct positive path distance and exact passage ownership |
| Same relation, ordinary proven split | With the new topology capability retain preview; v1-only fallback clears/reacquires; no duplicate sign at propagated child entry |
| Side-road departure, overlapping/transitive relations, U-turn | Clear at fresh incompatible/pending context; stale completion cannot restore it |
| Ambiguous fork, merge, unknown access, cycle or missing coverage | No target beyond unresolved path; current-way target before it still works |
| Conditional/dynamic/vehicle/lane restriction or conflicting station | No unsupported numeric preview and no skipping conflict to a later target |
| Town/end boundary before lower target | Stop the preview search at the boundary until fresh context is resolved |
| Station at a way endpoint, boundary + speed co-located, zero-length/shadowed rule | Physical station counted once; show only with a verified unique post-station numeric offer |
| Passed sign followed by GPS jitter/gap/resume | No resurrection within the same traversal; fresh current rule resolves normally |
| Camera/voice changes without movement | Eligibility updates immediately; normal authority remains at map passage |
| No callback after last valid fix | Preview timer clears within 3 s of that fix timestamp |
| Capability absent/unknown/malformed, old region, bundle switch | Preview absent/cleared; normal matching continues |
| Offline, camera off, TSR off | Preview works with supported local data and valid matching |

Extend iPhone `SpeedConsumerTests`/`ScreenOrientationUITests` and Android
`InventorySignRuntimeTests`, lookup/controller tests and orientation layout
instrumentation. Inspect all three saved mounting modes with telemetry and
dashcam, secondary signs, supplementary plates, recorder strip, safe-area
cutouts, long translations, 320/360 dp widths and enlarged text. Verify the
main sign remains centered in portrait and both landscape mounts anchor the
preview at the screen's lower-left.

Implementation order:

1. Add shared scenarios and the read-only same-way physical-event lookup,
   including capability and malformed-data fallback; benchmark existing indexes.
2. Implement the iPhone candidate model, controller lifetime/handoff and UI.
3. Implement equivalent Android behavior against the same scenarios; validate
   existing primary reference conformance without policy/lock changes.
4. Build and validate the additive source-node path capability and both native
   readers, then exercise relation-wide scenarios; same-way fallback alone does
   not satisfy complete relation coverage.
5. Verify layout and complete cold/warm device budgets. When device deployment is
   requested, validate parity on the attached Android and inspect the attached
   iPhone through QuickTime; use native tests/phone interaction for controls.
6. Enable only for validated local sign-capable bundles; publishing, deployment
   or new data downloads remain separate explicitly authorized actions.

This specification's original feasibility assessment performed no app or bundle
implementation. The subsequent implementation and its checks are documented
separately; source/model retraining, external publication and physical-device
deployment remain outside that work.
