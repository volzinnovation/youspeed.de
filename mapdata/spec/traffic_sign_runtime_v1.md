# Optional traffic-sign runtime capability, version 1

`traffic_sign_runtime_v1.sql` is additive to the existing v3 road schema. A client
must find `traffic_sign_capability.version=1` and all required columns before
using it. Missing/unknown capability, missing tables, malformed rows or another
region retain normal OSM/settlement/camera behavior. Raw inventory stays separate
with `usage_role=inventory_only`; derived accepted rules have their own provenance.

Signs are identified by `source_id:record_key` and the source snapshot hash.
Numeric source values are never synthesized from generic classifier labels.
Image paths address the shared official PNG bytes relative to `shared/`.
`model_classes_json` records vocabulary coverage, not confirmation evidence.
Only exact classifier labels populate that array; family aliases and artwork
coverage cannot confirm an exact source sign or its printed value.

`traffic_sign_way_direction` records OSM oneway, permitted motorcar directions,
lane counts and raw lane tags. `traffic_sign_lane` contains only explicitly known
directional lanes in OSM order (one-based); unknown lanes are not fabricated.
Differing directional lane limits yield `lane_scope=unresolved` rules until a
client has independent lane applicability evidence. Multiple same-direction
carriageways remain distinct OSM ways, not invented lanes of a nearby road.

The association stage decodes the OpenLR point-along-line physical reference,
matches both LRPs and a permitted directed path against this bundle's geometry,
checks reference bearings/offset/path length and sign position, and keeps all
rejections with evidence. OpenLR direction, not an assumed sign-face convention,
defines the directed approach. Source group orientation is a consistency check.
Unresolved/dynamic/malformed/ambiguous signs never supply an active speed rule.

`traffic_sign_way_rule` uses direction +1/-1 relative to the stored source
geometry. Start/end chainages always ascend; a reverse rule becomes active after
passing its station in decreasing chainage. A rule with `inside_city` and null
`speed_kmh` terminates old references and requests a fresh legal/default offer;
it must never reuse the old same-way posted limit. Intervals stop at subsequent
speed/town/end events and unresolved junctions. Only `association_status=accepted`
and `lane_scope=all` rows are actionable. The immutable association log retains
where a sign was actually placed even when an interval continues on another way.

Continuation is limited to an unbranched, unmerged continuation of the same
named/ref road (or unnamed road of the same highway class), at most 32 further
ways and 5 km. A new source sign, differing explicit OSM speed or conflicting
lane limits stops propagation. `traffic_sign_rule_path` retains the connected
directed path for each continued interval. Its child entry station is an interval
boundary, never another physical sign passage or a repeated town reset.

Trusted existing OSM town stations with known location and directed
`node_membership`/`collinear_way_split` association fill inventory gaps. They use
`source_id=osm-settlement`, the pinned road-PBF hash and ODbL attribution, and
retain the original `settlement_sign` identity. Nearby accepted MobiData town
duplicates are suppressed across every proven source-way alternative at a
physical OSM split. In DE only, existing directed `city_limit:begin/end` source
semantics normalize to DE:310/311 without reversing the already-resolved exit
direction; original codes remain in association evidence. Bare/unknown-direction
city limits stay excluded. `osm_town_fallback=materialized` tells clients to use
these ordinary runtime records instead of querying a second town-event stream.

DE:310/311 fully reset prior speed references. DE:278/282 remove an applicable
posted limit through the existing speed-end resolver, preserving independent
zone/pedestrian enclosures. A null-speed end interval masks an obsolete same-way
OSM posted tag; it does not override a retained enclosure with a road default.

Chainage uses the sum of spherical source-segment lengths with radius
6,371,000 m, matching v3 `way_endpoints`. A local plane chooses the nearest
segment and fractional projection only; changing the query latitude must not
rescale accumulated road length. Geofence distance uses the shared mobile
haversine radius 6,371,008.8 m and does not enlarge the specified radii.

Ordinary secondary encounters trigger within 10 m, without a fabricated speed-way
association. Town encounters use 30 m; changing city/penalty context requires an
accepted directed station traversal. A triggered secondary card remains visible
until a newer admitted sign replaces/invalidates it or its drive/bundle/country
context resets; leaving the geofence or losing GPS does not expire the card.
Capture/confirmation still use the live encounter, never the retained card.
For an accepted secondary association, a qualified actual vehicle heading that
opposes the source travel heading by >90° rejects that face. Source travel heading
is the stored geometric heading rotated once by 180° for direction -1. Unknown
heading/association evidence preserves proximity semantics without claiming a
verified face. Primary directed rule requirements remain unchanged. Inventory
proximity never constitutes a camera confirmation. Existing confidence, consent,
camera/storage/network gates remain in effect.
