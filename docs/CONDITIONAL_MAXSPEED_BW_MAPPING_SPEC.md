# OSM conditional maxspeeds: Baden-Württemberg inventory and bundle design

23 October 2026. Companion to the
[OCR/application specification](CONDITIONAL_SPEED_LIMITS_OCR_SPEC.md).
Status: measured inventory and generation/interpreter contract. The historical
audit below describes the inspected pre-compiler bundle. Core generation,
Swift/Kotlin interpretation and a separate local full BW bundle are now
implemented in the working tree; see the
[continuation record](V1_5_IMPLEMENTATION_CONTINUATION_2026-10-23.md).
No deployment or release is implied.

## 1. Which bundle was inspected

The inspected artifact is local bundle **2026-10-21-v1.5-runtime**, region
`baden-wuerttemberg`, built from the 13 September road extract. Its uncompressed
database SHA-256 is
`e1a36e56cc4809cc69d2d5161b993eff21a1c08264e8d9300e79ec7546ccd00b`;
the local database matches the bundle manifest. The `ways.meta` input also
matches its source manifest, SHA-256
`ea4f53314e3cb93c06e4ae66a1564d43dbd3b89e8b86d115c09295528a5fb141`.

The source manifest records PBF SHA-256
`1856f4ac7c18435e17d74c7ba24a7b21b3a1231e60449851890dc0109638ded3`.
The existing [road-readiness receipt](MOBIDATA_BW_V1_5_ROAD_READINESS.json)
records replication time **2026-09-13T20:21:20Z**. The October build date does
not make these September OSM tags current. PBF provenance is recorded from the
existing manifest; this audit hashes the inspected DB and metadata, without
rescanning every original PBF node/relation.

Population: **1,085,790 car-drivable way rows**, identical in source metadata
and the database. Counts below are way/tag occurrences or distinct OSM way
IDs, not kilometres, sign assemblies, camera observations, or every object in
the original PBF. Split ways can describe one physical restriction repeatedly.

The [machine-readable inventory](CONDITIONAL_MAXSPEED_BW_2026-10-23.inventory.json)
contains every one of the **191 distinct conditional key/value patterns**,
raw values, occurrence counts, audit family, issue flags and example OSM ways.
It also records all speed-key counts, auxiliary-table retention and source hashes.
Audit families are descriptive; they are not parser certification or executable
applicability verdicts.

| Observed key | Way/tag occurrences | Proposed role |
|---|---:|---|
| `maxspeed:conditional` | 3,906 | Generic ordered speed exceptions. |
| `maxspeed:forward:conditional` | 51 | Exceptions along source-way node order. |
| `maxspeed:backward:conditional` | 53 | Exceptions against source-way node order. |
| `maxspeed:hgv:conditional` | 61 | HGV-specific exceptions. |
| `maxspeed:hgv:forward:conditional` | 6 | HGV plus forward scope. |
| `maxspeed:hgv:backward:conditional` | 2 | HGV plus backward scope. |
| `maxspeed:lanes:conditional` | 2 | Per-lane exceptions; requires dedicated lane grammar. |
| `maxspeed:reason:conditional` | 8 | Explanatory metadata; cannot supply a speed. |
| **Total in `maxspeed…conditional` namespace** | **4,089** | **4,069 distinct ways; 4,081 speed-rule occurrences after excluding reason metadata.** |

There are 163 distinct raw values across these keys. Another 24
`source:maxspeed:conditional=sign` tags are provenance, not 24 additional speed
restrictions. Forty-six generic conditional ways lack a generic `maxspeed` tag;
their base must be resolved from actual directional/profile/jurisdiction context
or remain unknown, never copied from the exception.

## 2. What the bundle actually contains today

The audit verifies **exact retention of all 4,089 conditional namespace
way/key/value triples**, with zero missing or extra triples, in
`traffic_sign_way_direction.lane_tags_json`. This is storage, not interpretation.

The main `ways` table only has generic/directional scalar speeds,
`maxspeed_type` and `source_maxspeed`. It has neither a conditional-rule table
nor the complete raw speed tags. The optional sign-runtime import retains
conditions as a side effect of its lane/direction tag selection. Ordinary v3
builds without that optional overlay do not gain this retention path.

Both main mobile lookup implementations select scalar values without reading
those conditional expressions. Thus a road tagged `maxspeed=50` plus a night
30 can continue to supply 50 at night, and a road tagged `maxspeed=120` plus
`none` at night can incorrectly retain the daytime 120. These are identified
code-path risks, not claimed measurements of an attached-device drive.

The overlay's current `has_conditional_speed` check is also too broad for future
interpretation: it matches any `maxspeed…conditional` key, including reasons
and HGV-only scopes, then marks numeric inventory rules `lane_scope=conditional`
and stops propagation. The inspected overlay has **1,943 speed-rule rows** in
that scope; these are interval rows, not 1,943 unique signs. Its other 11
unresolved-lane rows are a separate issue. Replace the blanket check with
scope-aware rule evaluation; do not simply turn all these intervals on.

Additional observed speed information is partly lost from runtime storage:

- **1,577 ways** have a `maxspeed:variable…` key; the generic key occurs 1,550
  times. Only the two key forms containing `lanes` survive in the auxiliary JSON.
  Most dynamic markers and default/max/min/value metadata do not.
- **716 ways** have a speed-key value literally `signals`: 715 generic and one
  directional occurrence. It denotes an unresolved electronic indication, not
  an implicit road-class speed.
- Mode-specific static tags include `maxspeed:hgv` (646), `maxspeed:motorcycle`
  (66), `maxspeed:motorcar` (3) and `maxspeed:motor_vehicle` (1). Preserve them
  alongside conditions, or profile precedence will be incomplete.
- Eight non-conditional HGV speed keys contain an embedded `@` expression.
  Retain them as noncanonical source evidence; do not take their numeric prefix.
- No `maxspeed:wet` or `maxspeed:night` keys occur in this way population.
  Legacy wet aliases can be recognized for other snapshots, but night requires
  explicit semantics and cannot be guessed as 22:00–06:00.

## 3. Observed condition families and mappings

The following audit families partition all 4,089 way/tag occurrences. Features
such as PH, SH, weight and weekday can overlap across families.

| Family | Occurrences | Target interpretation and required context |
|---|---:|---|
| Simple local schedule | 3,340 | Civil-time schedule AST; includes explicit weekdays, multiple windows, overnight ranges, `24:00`, and typed `none` outputs. The subset is lexically screened, not runtime-verified. |
| Wet surface | 524 | `road_surface_wet`, with wet/dry/unknown context. |
| Vehicle, mass or usage | 145 | Vehicle class, actual/rated mass, hazardous load and purpose predicates. Missing relevant profile fields remain unknown. |
| Holiday schedule | 25 | Opening-hours calendar rules, including PH/SH inclusion or exclusions; requires a valid jurisdiction calendar. |
| Calendar range | 13 | Explicit month/month-day selectors, including ranges crossing New Year. |
| Dynamic operating lane count | 7 | `lanes=1`; qualified current traffic-management state, not the lane containing the car. |
| Conditional lane expressions | 2 | Lane vector of conditions plus lane identity. |
| Malformed/nonstandard | 22 | Preserve raw data and diagnostics; no automatic syntax repairs. |
| Other review required | 3 | Two contradictory clock expressions and one unknown `trailor` condition. |
| Conditional reason metadata | 8 | Display/provenance only; separate from numeric rule truth. |

There are **526 wet-bearing tag occurrences on 515 ways** when the two lane
expressions are included. PH occurs on 37 and SH on 19 ways, including malformed
expressions that are excluded from the 25 screened holiday-family rows. These
counts must not be added as independent populations.

Representative mappings, taken from the inspected source rather than invented
examples:

| Raw source | Example way and source base | Mapping |
|---|---|---|
| `30 @ (22:00-06:00)` | [3453385](https://www.openstreetmap.org/way/3453385), Moltkestraße, base 50 | `numeric(30)` when daily overnight schedule true; base 50 when false. |
| `30 @ (00:00-06:00,22:00-24:00)` | [4096496](https://www.openstreetmap.org/way/4096496) | Two daily windows, union within the time selector; preserve `24:00` as end-of-day. |
| `30 @ (Fr 20:00-02:00)` | [5184227](https://www.openstreetmap.org/way/5184227) | Friday-start window extending to Saturday 02:00. |
| `30 @ (07:00-16:30 AND Mo-Fr)` | [694144318](https://www.openstreetmap.org/way/694144318) | `all(local_clock_range, weekday_set)`; order of these predicates does not change AND. |
| `100 @ wet` | [4295671](https://www.openstreetmap.org/way/4295671), B 36, base 120 | `numeric(100)` when wet; base 120 when dry; unresolved when wetness unknown. |
| `none @ (19:00-06:00)` | [4797492](https://www.openstreetmap.org/way/4797492), A 81, base 120 | `unlimited` at night; base 120 in daytime. Never map `none` to missing or zero. |
| `30 @ (Mo-Fr 07:00-17:00; PH off; SH off)` | [367976987](https://www.openstreetmap.org/way/367976987) | One schedule with holiday exclusions, not three speed clauses. |
| `30 @ (Sa,Su,PH)` | [29448990](https://www.openstreetmap.org/way/29448990) | Weekend OR public holiday; no printed clock means the complete selected day. |
| `120 @ (Oct-Apr)` | [178795075](https://www.openstreetmap.org/way/178795075), A 96, base 120 | Inclusive annual month selection Oct through Apr. Here both outcomes are 120, but preserve the condition/source. |
| `50 @ (Aug 15 - Oct 31)` | [30627266](https://www.openstreetmap.org/way/30627266) | Annual inclusive date selection; end at local midnight after Oct 31. |
| `60 @ weight>7.5` on an HGV key | [5118414](https://www.openstreetmap.org/way/5118414) | Scope HGV AND actual mass >7.5 tonnes; do not substitute rated mass. |
| `60 @ (maxweightrating>7.5)` on an HGV key | [23224351](https://www.openstreetmap.org/way/23224351) | Separate rated-mass predicate. Noncanonical `maxweight` expressions require semantic review rather than an automatic alias. |
| `30 @ hazmat` | [16134112](https://www.openstreetmap.org/way/16134112) | Hazardous-load profile predicate, not weather. |
| `80 @ wet\|80 @ wet\|` | [7990578](https://www.openstreetmap.org/way/7990578), B 36; static lanes `100\|100\|50` | Observed per-lane syntax needs validated lane parsing; retain the empty final lane. No whole-road 80 from the first token. |
| `50 @ (lanes=1)` | [220956325](https://www.openstreetmap.org/way/220956325), directional, variable lane signalling | Verify current operating lane-count semantics from source/signalling; static `lanes=…` does not establish the current condition. |
| `school @ (Mo-Fr 07:00-17:00)` on a reason key | [4303773](https://www.openstreetmap.org/way/4303773), numeric conditional 30 alongside base 50 | Attach explanation to the rule; `school` is not a speed or a school-open sensor. |

Malformed/review cases must be fixtures too: `17:030` (7 rows), extra closing
parenthesis (1), missing closing parenthesis (2), `Sa-So` (7), `*` (1),
`no @ (agricultural AND hazmat:water)` (4), `trailor` (1), and the disjoint
`22:00-06:00 AND Mo-Fr 07:00-18:00` (2). Never turn the last expression into OR.
Its literal AND is contradictory; keep a data-quality review flag before
promoting it as a trustworthy rule. `no` belongs to access semantics and is not
a typed maximum speed. These issues do not authorize editing OSM.

## 4. OSM semantics the interpreter must preserve

Use separate adapters for OSM conditional syntax and OCR plate language, then
emit the same typed predicates and limit values. Do not pass OSM through the
display formatter for OCR clocks.

OSM scope/ordering follows its documented rules: more specific mode wins,
direction beats generic scope within a mode, conditional beats static at the
same mode/direction, and lane restrictions add their own precedence. Within
one tag the **last matching value/condition pair wins**. Preserve pair order;
never sort by numeric speed or combine all speed values with `min()`.
[OSM conditional restriction rules](https://wiki.openstreetmap.org/wiki/Conditional_restrictions#Evaluation_of_conflicting_restrictions)

For YouSpeed's implementation this means:

1. Decode a key into legal-speed/reason/provenance role, vehicle scope,
   direction, lane scope and conditional marker. Reject unknown suffix
   arrangements from executable use while retaining them verbatim.
2. Resolve profile and directed/lane applicability before comparing values.
   `forward/backward` is relative to source geometry, not north/south. An HGV
   restriction cannot affect a verified motorcar profile. Unknown relevant
   profile or lane state cannot be assumed away.
3. Parse ordered speed clauses with a parenthesis/quote-aware tokenizer.
   Top-level clause separators and separators inside a calendar expression are
   different constructs. The outer `@` separates value and condition. Retain
   source offsets and fail complete parsing on residual unsupported text.
4. Parse the supported calendar subset into explicit selectors, windows and
   exclusions. Preserve nested Boolean structure and three-valued truth. A
   comma between clock windows is not a new speed clause. A blank lane slot is
   not zero, none or a missing vector position.
5. Evaluate the applicable ordered decision list against one context snapshot,
   combining static and conditional scopes. If a later possible match can
   change the result, do not declare an earlier known match authoritative.

OSM temporal expressions use opening-hours syntax, whose separators and
`off` modifiers have their own meaning. Pin the grammar/library version and
test its supported subset; no global semicolon split and no assumption that
every calendar rule is a simple union.
[Opening-hours specification](https://wiki.openstreetmap.org/wiki/Key:opening_hours/specification)

The app must evaluate **current driving time**, not PBF publication time,
bundle-generation time, or the photo's capture time. Use geographic zone and
calendar jurisdiction. Include midnight, DST, date/season boundaries, PH/SH
changes, context expiry and resume in the existing re-evaluation lifecycle.

Conditional `none` is a real possible result. A 120 base with unknown possible
`none` is not a definite current 120. Conversely, with a known inactive night
condition the actual base 120 is eligible again. Numeric 5 remains numeric 5;
it is not a synonym for typed walking pace. Bare invalid values and provenance
words are not numeric limits. Units require full-string parsing and explicit
normalization, rather than accepting a numeric prefix.
[OSM maxspeed values](https://wiki.openstreetmap.org/wiki/Key:maxspeed)

**Unknown-result rule:** compute the set of reachable effective typed values
under supported scope/precedence. Emit an exact current value only when all
reachable outcomes agree and the rule set is otherwise admitted. If outcomes
differ, emit unresolved and retain qualified observed/advisory information.
Correlated predicates must stay correlated: repeated wetness or the same clock
cannot be treated as unrelated coin flips. For unsupported structure, do not
claim the set is complete; remain unresolved.

Examples of this proposed unknown handling:

- `base 120; 100 @ wet`, unknown wetness: possible 100/120, unresolved.
- `base 120; 120 @ (Oct-Apr)`: both outcomes 120; calendar uncertainty alone
  need not hide an otherwise verified 120, with a diagnostic explaining why.
- `base 120; none @ night`, unknown clock: possible 120/unlimited, unresolved.
- Multiple ordered clauses: an unknown later wet branch can change a known
  time-branch result. Preserve the uncertainty unless it cannot affect the
  selected value; a definitely matching later clause can dominate earlier ones.

Do not publish the maximum possible numeric value as though it were the exact
current limit. The protected shared reference model has one typed current
value, not a separate alert ceiling. A future warning-from-bounds feature would
need its own explicit product/policy design; it is outside this implementation.

## 5. Calendar, vehicle and variable-state support

**Calendar:** simple clocks/weekday sets and exact month/day ranges are
deterministic offline. PH and SH need versioned, jurisdiction-scoped calendars,
coverage dates and provider provenance. Missing/expired calendar coverage gives
unknown for the relevant predicate, not “not a holiday”. Retain exclusions
such as `PH off; SH off` even in an initial build that cannot evaluate them.
`Sa,Su,PH` includes a holiday; it is not a holiday exclusion. Do not invent
school-opening hours from reason text.

**Vehicle:** use an explicit shared vehicle profile, consistent with existing
product defaults on both apps. Relevant fields are vehicle class, actual mass,
rated mass, trailer and load/usage status. Do not assume unknown HGV/load data
means false. Keep `weight`, rated-weight and unresolved `maxweight` terms
distinct. A verified non-HGV profile can rule an HGV key out without evaluating
its irrelevant weight clause. The eight embedded expressions under static HGV
keys require a reviewed normalization adapter or remain unsupported.

**Electronic limits:** `maxspeed:variable` describes changeable limits;
default/max/min/value lists do not prove the current displayed number. For
this design, publish no exact current bundle limit while relevant variable
state remains unknown. A qualified current camera or trusted signalling input
can resolve it through the existing producer path. `maxspeed:variable=no` is
distinct from an active variable marker. Do not clear unknown state because
traffic seems light or weather seems dry.
[OSM variable-speed documentation](https://wiki.openstreetmap.org/wiki/Key:maxspeed:variable)

**Explanations:** reason and source namespaces have no independent speed
authority. `Lärmschutz`, `school`, `sign` and notes remain metadata; they cannot
create a clock, weather predicate, or generic unconditional speed. Separate
their interpretation from conditional keys that actually change a value.
[OSM reason documentation](https://wiki.openstreetmap.org/wiki/Key:maxspeed:reason)

## 6. Concrete bundle-generation changes

Conditions must be a **core road-speed capability**, independent of whether a
country has a MobiData sign inventory. Add `conditional_speed_rules_v1` through
the standard full-build entry points, not only `build_traffic_sign_runtime.py`.
The capability is proposed; these tables/metadata do not currently exist.

| Proposed storage | Required fields/contract |
|---|---|
| `road_speed_source_tag` | `(way_id, key)` primary key; exact raw value, source snapshot, source object version when available. Preserve all legal-speed, mode, directional, lane, variable and explanatory/provenance tags. |
| `road_speed_rule` | Stable rule ID; way/directed path and lane scope; vehicle scope; typed limit/unit; base-rule reference; ordered priority/clause index; condition ID; source-tag reference and exact source span. |
| `road_speed_condition` | Bounded versioned declarative AST; required context fields; normalized calendar/Boolean predicates; raw source reference; no runtime truth baked into the bundle. |
| `road_speed_interpretation` | Rule-set ID; parser/normalizer version and hash; `supported / unsupported / malformed / review_required`; issue codes, residual source spans, conflicting relationships and default/base resolution provenance. |
| Capability metadata | Schema/grammar version, source PBF time/hash, parse counts/statuses, minimum interpreting app/runtime, supported feature set, calendar coverage/version, artifact integrity hashes. |

Implementation steps:

1. **Source packing:** `pack_runtime_artifacts_pyosmium.py` already retains raw
   way tags. Preserve that complete input and source identity. Enumerate the
   speed namespaces through a role-aware registry, including mode/direction
   combinations; do not maintain a short list of just the generic tag.
2. **Core SQLite build:** compile the relevant tags in
   `build_spatialite_v3.py` into the tables above. Keep an unsupported record for
   every unhandled rule; dropping it is not equivalent to an absent condition.
   Add indexes by way/direction/profile/lane and rule-set identity.
3. **Semantic compilation:** emit ordered decision lists and bounded ASTs,
   complete typed base rules, and required contexts. Do not pre-evaluate clocks
   at build time. Preserve day-range unions, `off` calendar clauses and `none`.
   Keep malformed aliases as review-required; no automatic OSM edits.
4. **Overlay reconciliation:** replace blanket conditional-way blocking with
   an evaluated link to the core rule set. A road inventory assertion that may
   be the same conditional sign cannot reintroduce an unconditional duplicate.
   Keep unrelated end/town events and enclosures under their existing semantics.
5. **Mobile resolution:** both V3 lookups query the rule set for the matched
   way and scopes. They return selected typed value plus explicit evaluated
   applicability/reason/revision to the existing speed-reference adapter.
   Remove scalar fallback paths that bypass a known unresolved exception or
   variable marker. An unrelated unsupported HGV key must not blanket-block a
   verified motorcar result.
6. **Time without rematching:** retain the current road rule set with source
   context. A timer/weather/calendar revision re-evaluates it even without GPS,
   then atomically updates display, alerts and penalties. Do not extend camera
   lifetime or alter the shared reference policy.
7. **Manifest and installation:** declare the new capability and a minimum
   version that actually understands its outputs. Existing `min_app_version=1.5`
   is not proof of support. Schema/capability omissions or corrupt data fail
   closed for affected rules; they must not silently select a flattened scalar.

Ordinary static roads remain usable, but **absence of an optional overlay is
not evidence of absence of conditions**. Compatibility must distinguish an old
bundle with no condition preservation from a new audited bundle with no
conditions on a particular way. Keep source-policy integrity separate:
bundles still cannot supply reference-state-machine policy bytes.

## 7. Delta generation and release gating

The inspected heuristic delta builder's `MAXSPEED_KEYS` omits conditional,
vehicle, lane and variable keys. Exact way comparison covers scalar road columns
and geometry; the context-table delta list does not include the proposed rule
tables or the optional sign-runtime direction JSON. Calling the mode “exact”
does not establish equivalence for these newly relevant tables.

Before enabling conditional-capable delta releases:

- Include every retained source-speed role in change detection, including
  conditional-only edits, reasons/provenance and marker removal. Regenerate the
  complete affected rule set, not just one numeric column.
- Apply ordered-clause, AST, issue/status, source and metadata changes in one
  transaction. Handle way deletion, reversal, split and source revision changes;
  direction must follow the updated source geometry. Reconcile dependent
  inventory intervals and prevent stale cached offers after an update.
- Add rule tables and capability/grammar/calendar metadata to exact equivalence
  checks. Compare a patched DB with a full rebuild, including deletions and
  conditional changes that leave generic `maxspeed` unchanged.
- Require a full bundle for schema/capability/grammar changes unless a verified
  migration exists. Until delta coverage is implemented and tested, distribute
  these capabilities through full bundles only and reject incompatible deltas.

Preserve current atomic install, checksums and rollback behavior. All builds,
downloads, publication and installation retain existing approval/consent gates;
this specification does not deploy or publish a bundle.

## 8. Acceptance and rollout priorities

First implement core retention/typed rule sets and the deterministic schedule
subset, including overnight, comma windows, direction and **conditional none**.
The audit identifies 3,340 such way/tag occurrences; this is implementation
priority evidence, not a prediction that all those roads are ready to warn.
Add exact annual date ranges next. Preserve wet, PH/SH, lane and vehicle
conditions from the start, even while they evaluate to unknown without required
context. Qualification of a weather/calendar/profile source is separate work.

Use all 191 exact key/value patterns as source fixtures and the following
specific runtime/build assertions:

| Fixture/operation | Required outcome |
|---|---|
| Moltkestraße 3453385 at 23:00 / 12:00 | Current 30 / 50 from the complete evaluated rule set. |
| A 81 way 4797492 at 20:00 / 12:00 | Typed unlimited / 120; no daytime-120 warning during the active `none` exception. |
| B 36 way 4295671, wet / dry / unknown | 100 / 120 / unresolved; no current scalar 120 offered for the unknown case. |
| Seasonal way 178795075 with both branches 120 | Current 120 can remain exact despite irrelevant date uncertainty, with complete source diagnostics. |
| PH off/SH off on holiday / calendar unavailable | Schedule false / unresolved where the holiday result can affect selection. |
| `Fr 20:00-02:00`, Saturday 01:00 | Active under the reviewed OSM temporal adapter. |
| Two clauses `30 @ night; 50 @ wet`, both true | 50 from last matching clause, not minimum 30. This synthetic fixture tests grammar beyond the snapshot. |
| Last clause unknown but could change the selected speed | Unresolved; do not stop on the first known match. |
| HGV conditional key and verified motorcar profile | HGV rule inapplicable; valid motorcar/base result unaffected. |
| HGV actual mass unknown, matching vehicle scope | Unknown mass condition; never substitute rated mass. |
| Conditional-lane vector with empty last element | Position preserved; inherit that lane's valid rule, not zero/unlimited. Differing possible lanes require qualified lane identity. |
| Dynamic lane count or electronic state unknown | No exact current numeric offer derived from static lane count or variable default/max metadata. |
| Reason-only condition | Metadata; cannot supply, cancel or block a speed rule by itself. |
| Malformed condition or embedded static-key `@` | Raw record and issue retained; no partial numeric extraction or guessed repair. |
| Condition-only edit/removal, unchanged generic 50 | Rule set and next evaluation change in patched DB; patch equals full rebuild. |
| Way reversal/split/deletion | Correct directed scopes, no dangling/stale rule IDs or source authority. |
| Unsupported capability on an older client | Installation/version gate prevents silent scalar interpretation. |
| Full build without inventory overlay | Identical core conditional rules, not a loss of all conditions. |

Run the shared policy conformance checks unchanged, then both native evaluator
and actual controller suites. Device acceptance is needed when deployment is
requested. No numeric recognition-accuracy or road-coverage claim follows from
this source-tag inventory.

## 9. Reproducing the inventory

The [read-only audit](../scripts/map/audit_conditional_maxspeeds.py) hashes the
database and metadata, checks their manifests, compares exact conditional triples
between metadata and SQLite, and emits the full pattern catalogue:

```sh
python3 scripts/map/audit_conditional_maxspeeds.py \
  --ways-meta mapdata/dist/baden-wuerttemberg-v1.5-roads/ways.meta \
  --db mapdata/dist-v3/baden-wuerttemberg-v1.5-runtime/speeds_v3.sqlite \
  --bundle-manifest mapdata/bundles/v3/baden-wuerttemberg/2026-10-21-v1.5-runtime/baden-wuerttemberg_manifest.json \
  --source-manifest mapdata/dist/baden-wuerttemberg-v1.5-roads/manifest.json \
  --out-json /tmp/bw-conditional-maxspeed-inventory.json
```

The script is an inventory, not a production OSM parser. Its mutually exclusive
family assignments are conservative lexical screens; it does not evaluate
truth, validate installed signage, infer missing vehicle data, or certify lane
syntax. Its output is source-pinned and reproducible apart from generation time.

Relevant implementation files: [source packer](../scripts/map/pack_runtime_artifacts_pyosmium.py),
[core builder](../scripts/map/build_spatialite_v3.py),
[inventory overlay](../scripts/map/build_traffic_sign_runtime.py),
[delta builder](../scripts/map/build_v3_delta_pack.py),
[delta table coverage](../scripts/map/v3_context_delta.py),
[iPhone lookup](../iphone/SpeedConsumerApp/V3SpeedLimitService.swift),
[Android lookup](../android/app/src/main/java/de/youspeed/android/alpha/V3SpeedLimitLookup.kt).
