# Phone road matches and crop sequences — 2026-10-09

The crop API now accepts the OSM way matched by the phone. Both clients retain
that match with the sampled frame before asynchronous inference and storage. The
Inspector can filter by the exact way ID and open its road geometry and available
portal/connected-way context in the loaded map bundle. This gives road-context
triage a direct starting point instead of repeating a nearest-road search.

## Recorded metadata

The additive, optional `phone_road_match` object contains:

| Field | Meaning |
| --- | --- |
| `schema_version`, `source` | Version 1, `on_device_bundle_matcher` |
| `osm_way_id` | Canonical positive decimal string; no floating-point ID conversion |
| `bundle_version`, `bundle_db_sha256` | Identity of the materialized bundle used for the match |
| `matched_fix_at` | Original match location's UTC timestamp |
| `frame_match_delta_ms` | Crop frame time minus that original fix time, signed |
| `travel_direction` | Forward, reverse or unknown relative to the way |
| `matched_way_stable` | The phone's recorded stability state |

The bundle identity and original fix are captured together with the matcher result.
They are carried through the accepted frame and copied to each crop. A new match,
GPS fix or bundle arriving while inference runs cannot replace this record.
Android's refreshed recognition coordinates are not used to manufacture a newer
match timestamp. Existing runtime frame-admission behavior is unchanged.

Unavailable or invalid metadata yields an explicit null; it does not prevent the
crop from being collected. Historical manifests without the field remain valid.
The signed age is diagnostic, including admitted stale/future values within the
one-day contract bound; this is not a new freshness or recognition gate. Old,
explicitly unavailable and recorded contexts are distinct in Inspector. No
historical crop is backfilled with a later map match.

The backend retains the field through its existing intake, archive, management
manifest and reviewed export paths. The published contract and native validators
constrain compliant payloads; the bounded fast intake, archive and import paths
preserve raw manifests without automatically invoking the full crop contract
validator. No new database column or crop storage migration is required for this
JSON field.

## Use the way, bearing and successive crops together

Crop metadata already includes frame time, original normalized/pixel sign box,
source dimensions, per-crop vehicle position, GPS course and course accuracy.
The existing location producer samples the available fix when handling the
recognition result and records its original fix time and signed frame offset;
it is not guaranteed to be a capture-instant fix. Keep the recorded age/accuracy
checks when combining crops. The new road-match metadata independently preserves
the original matcher fix before inference.
Those fields allow a first pass to:

1. Look up the recorded way directly in the appropriate bundle and enumerate
   connected branches and nearby roads.
2. Use travel direction and each crop's GPS course to prioritize the road corridor
   ahead of the vehicle.
3. Compare the sign's box and vehicle position over crops sharing one source
   observation, checking whether the candidate remains consistent with the
   mainline or an exit branch.
4. Request surrounding frames or additional camera geometry for unresolved cases;
   full video is not a prerequisite for every road-context triage step.

This patch supplies and exposes those inputs. It does not yet implement a new
multi-view sign-position estimator or change the sign-relevance decision. GPS
course is vehicle travel bearing; calibrated camera yaw/FOV are not in the crop
contract. The recorded way is a context anchor, not a sign-to-road label.

The October 9 read-only live snapshot contains **266 observation groups with two
or more saved crops**, totaling **955 crops**; each has its own recorded location
and a finite GPS course in the range [0°, 360°). Another 846 groups have one saved
crop. All 1,801 eligible crops have a recorded finite course, including legacy
fallback positions, but **254 of 1,801** have reported course uncertainty above
30°; **183 of the 955** crops in multi-crop groups do so.

The 30° comparison applies the existing frozen exit-context algorithm's
`max_course_accuracy_degrees` bound as a diagnostic. That algorithm requires
reported course uncertainty between 0° and 30° inclusive to classify heading
relative to a mapped exit approach; higher uncertainty leaves that relation
unknown. It does not change geographic near-exit status or exclude these crops
from review. These counts describe retained metadata, not independently measured
directional accuracy or which signs were actually displayed.

The observer qualifies a sighting after at least two analyzed frames spanning
100 ms. It then attempts a first crop and subsequent crops at least 500 ms apart,
with six regular samples and two reserved for substantial size improvement.
That is not a guarantee of two stored crops: visibility duration and failed or
skipped capture can leave one. The presentation-track association used for user
corrections currently remains in memory and is not serialized. A durable
display/presentation link is the next small capture extension if the analysis is
restricted specifically to signs actually shown to the driver.

## Inspector workflow

- `phone_way_id` filters by exact recorded string ID before pagination. Omitted,
  null, malformed numeric IDs and non-phone source tags cannot match the filter.
- **Im geladenen Karten-Bundle ansehen** opens the recorded way using an indexed
  lookup, available corridor/portal connections, crop position and GPS bearing.
  This is explicitly the loaded Inspector bundle; the phone's bundle identity
  remains visible for comparison. An external OSM link opens the current OSM way.
- **Crops dieser Beobachtung anzeigen** selects the exact installation, collection
  epoch and observation. Conflicting class/time/way filters are cleared so later
  crops from a changed road match are included. The gallery remains chronological,
  newest first. Grouping by source observation is separate from physical-sign/site
  review.
- Every map handoff clears the previous crop's road, position, bearing and portal
  overlays, including absent GPS and missing-way cases. IDs beyond the existing
  map viewer's safe numeric range are refused there while remaining exact in the
  API, metadata and external OSM link.

## Validation and rollout

Backend implementation: `e7dd00933c5ca6154655b590b83cbd47de916e79` in
Woladen.de-analytics. **81 targeted tests passed**, including exact IDs above
JavaScript's safe integer limit, timestamp/age checks, repeated crop-specific
metadata, actual intake and signed archive round trips, and a disposable
PostgreSQL review/history/export check. The SQL harness starts at verified archive
contents; the full older PostGIS importer is not qualified by it. Backend CI passed.
All 18 shared contract artifacts are byte-identical to the backend export.

The actual Inspector query was independently checked in disposable PostgreSQL
for exact large/adjacent IDs, null/old manifests and malformed metadata. Native
tests cover immutable A-to-B road changes while inference is delayed, missing
metadata, repeated crop storage, and common Swift/Kotlin contract vectors.
Android passed **52 targeted tests**, with one existing archive-dependent skip;
both focused **iOS simulator tests passed**, as did the Swift collection host
suite and **25 shared provenance vectors**. Inspector passed **37 Python tests**
and **83 JavaScript tests**. These include the real map-handoff function and
synthetic DOM workflow checks; no phone or field accuracy qualification is claimed.
Independent review found and fixed a Swift fractional timestamp boundary that
could reject a valid crop, and stale map overlays between Inspector selections.

The full CI run also exposed a pre-existing Swift expression type-check timeout
and macOS-specific Android test export paths. The behavior-preserving Swift
decomposition produced identical actual penalty-engine outputs in 58,080 cases
and passed iOS simulator-target type checking. After the path fix, the complete
Android unit suite passed 663 tests with one skip using a Linux-style temporary
root. These local checks do not establish a green full GitHub run; see the current
[PR #29 checks](https://github.com/volzinnovation/youspeed.de/pull/29/checks).

Activate the accepting backend before shipping clients that emit this field,
including explicit null: an older strict processor does not know the new key.
The #27/#28 review-table rollout remains a separate prerequisite for durable
class review and geographic-context writes. No production deployment, phone
installation, sign decision, model or protected speed-reference policy change
was made here.
