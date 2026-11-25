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

### Vehicle-specific speeds

Keep the passenger-car limit in `maxspeed` or its directional variant. In OSM,
`maxspeed:hazmat=30` scopes the value to vehicles carrying marked dangerous
goods (DE:1052-30). `maxspeed:hazmat:water=30` scopes it to vehicles carrying
water-polluting cargo (DE:1052-31). Use the way's `:forward` or `:backward`
suffix when applicable, followed by `:conditional` if an additional condition
is posted. `hazmat:water=*` is an access tag. The compiler retains the raw speed
tags and their scope. Both apps exclude cargo-only limits from the passenger-car
reference and upcoming limits. See the [OSM hazard tagging guide](https://wiki.openstreetmap.org/wiki/DE:Key:hazmat)
and the [conditional restriction syntax](https://wiki.openstreetmap.org/wiki/Conditional_restrictions).

The physical assembly uses `traffic_sign=DE:274[30],1052-31`. The comma links
the supplementary plate to its primary, and brackets hold the posted speed.
Taginfo records the values `DE:274-30,1052-31` and `DE:274:30;DE:1052-31`.
The German hazmat page also shows a semicolon. Use the comma for related
signs in new entries, following the [German traffic-sign tagging guide](https://wiki.openstreetmap.org/wiki/DE:Key:traffic_sign).
[OSM Taginfo](https://taginfo.openstreetmap.org/api/4/key/values?key=traffic_sign&query=1052-31&page=1&rp=10&sortname=count&sortorder=desc)

Way 822226813 has `maxspeed=70` and `maxspeed:hazmat:water=30`. Its additional
`maxspeed:conditional=no @ (agricultural AND hazmat:water)` retains the vehicle
condition and the unsupported value. The condition excludes passenger cars,
so the conditional value does not mask 70. [OSM way 822226813](https://www.openstreetmap.org/way/822226813)

Inventory builds pair a cargo plate with the speed sign in the same source
assembly. The bundle retains their source observations and excludes that
assembly from passenger-car speed rules. Both apps evaluate the visual plate
under its parent sign independently of the map position. If a source inventory
omits the plate, its speed remains a separate map observation until the source
assembly is corrected.
