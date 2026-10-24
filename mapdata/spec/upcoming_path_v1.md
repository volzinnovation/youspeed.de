# Upcoming-path capability, version 1

This additive capability supplies conservative directed lookahead, not navigation.
Clients require `version=1`, `completeness=complete`, and
`geometry_convention=source_vertices_spherical_6371000m_v1`. The
`road_snapshot_sha256` must match `traffic_sign_capability.road_snapshot_sha256`.
Missing, malformed or unknown capability disables cross-segment lookahead.

The builder reads the pinned original PBF. Every source `highway` way contributes
node incidence, including roads omitted from the bundle. Source OSM node identity
is authoritative: coincident coordinates do not connect different source nodes.
Every admitted way is checked against its complete stored source vertices and
length. Segments split at all shared/interior junction nodes, repeated nodes,
restriction via nodes and access/barrier nodes. Shape vertices stay inside a
segment. Incomplete/mismatched source geometry prevents capability completion.

`upcoming_path_segment` stores both directions. Chainage bounds always ascend;
`start_node_id` and `end_node_id` follow the row's travel direction. `length_m`
is their chainage difference, using spherical source-segment lengths with radius
6,371,000 m. Only `permission_status=allowed` is usable. Direction/access
conditionals, unresolved access values and node barriers stop continuation.

`upcoming_path_successor` contains a row for each segment. A missing row, a
`stop` row, unknown proof or unknown permission means stop. A client may use
only `status=certified` with `proof=source_node_unbranched_unmerged_v1`.
Certification requires complete source incidence degree two, a single permitted
forward successor after excluding the reverse of the arrival segment, and no
extra incoming merge. All source turn-restriction relations are conservative
barriers on every involved way and via node, including conditional and via-way
restrictions. A restriction is never interpreted as permission. Bundle clipping,
nonadmitted roads, unknown access, forks, merges and loops cannot create an
unproven certificate. Clients still enforce their frozen common road-relation
scope and their adaptive distance/work budgets; topology does not select a
future turn. The stored segments and certificates have no 300 m cutoff.
Clients can use the 30-second, minimum-300 m window without rebuilding this
capability or changing its version. They remain bounded by 32 path segments,
the existing 25 ms traversal deadline and event caps.

`upcoming_path_way` and `upcoming_path_node` retain validation evidence.
`source_degree` is the number of incident source-highway half edges, saturated at
three (three means at least three). An interior source node contributes two;
an endpoint contributes one. `restriction_barrier` also includes physical node
barriers/access restrictions. Source restrictions on an involved way forbid all
of its boundary continuations, rather than attempting partial turn evaluation.

Segment IDs are deterministic within a source way: `way_id * 1048576 +
source_segment_index * 2 + (direction == 1 ? 0 : 1)`. They remain bundle-local.
The builder adds a full physical-sign station index containing all association
statuses, so a conflict station remains a search barrier. Physical sign locations
continue to come from `traffic_sign_association`, not propagated rule stations.

Delivery currently requires a complete bundle. Both exact and heuristic delta
builders reject a base or target with this capability until every topology,
physical-event, source-capability and index change can be reproduced together.
This prevents old certificates surviving beneath updated road geometry.
