# Core conditional road speeds v1

`scripts/map/conditional_speed_rules.py` runs in the standard v3 full database
builder, independently of MobiData inventory. Capability version 1 and grammar
`youspeed-osm-speed-1` require clients 1.5 or later. Full bundles only; both exact
and heuristic delta generators reject databases carrying this capability.

The tables are defined by that compiler's `SCHEMA` constant:

| Table | Meaning |
| --- | --- |
| `road_speed_capability` | Version, grammar and exact compiler SHA-256 |
| `road_speed_source_tag` | 64-bit way ID, source key, original value and source snapshot |
| `road_speed_rule_set` | Per-way bounded JSON decision list for native evaluation |
| `road_speed_rule` | Stable rule ID, source key, original clause order/specificity, typed value, condition identity and source character offsets |
| `road_speed_condition` | Content-addressed declarative Boolean/calendar/context AST |
| `road_speed_interpretation` | Per-key support status and reason; unhandled syntax is never dropped |

Source offsets are zero-based Unicode character positions in the exact raw tag,
start-inclusive/end-exclusive. Way IDs remain SQLite 64-bit integers; JSON rule
IDs are strings. Numeric units are km/h; `unlimited` is distinct from absent,
unsupported, numeric 5 or walking pace. No conditions are evaluated at build time.

The initial grammar covers local clock/weekday windows, overnight start-day
anchors, comma windows, annual ranges, Boolean expressions and PH/SH exclusions.
PH/SH, wetness and other predicates remain unknown without qualified context.
Unparsed lane/weight/vehicle expressions stay explicitly unsupported, filtered
by their applicable vehicle/direction scope before they can mask a current value.
Variable limits remain unresolved without current visual/signalling evidence.

The last matching clause wins inside a source tag. Vehicle specificity precedes
direction, and conditional precedes static at the same specificity. An unknown
leaf is correlated across repeated occurrences. An exact result requires all
reachable admitted outcomes to agree. Native adapters bound rule bytes, tag and
AST depth, and enumerate at most 12 unknown contextual facts. Larger ambiguity
fails closed. Existing camera, own-correction and government producer priority
is unchanged; the state-machine policy is never supplied by this capability.

Shared conformance fixtures: `shared/conditional-speed-rules/conformance-v1.json`.
The tests additionally compile all 191 measured BW conditional key/value patterns.
