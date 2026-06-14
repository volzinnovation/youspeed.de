# Hard-Case Audit Protocol

Purpose: add a small, manually reviewed corpus that complements hindsight pseudo-label replay. A row must not be counted as manually audited until `manual_audit_status=audited` and the reviewer/date/evidence fields are populated.

Review steps:

1. Open the source log around `log_index` and inspect at least five fixes before and after the target fix.
2. Inspect the local OSM geometry and tags for `live_way_id`, `pseudo_label_way_id`, and `oracle_way_id` when present.
3. Assign `manual_correct_way_id` only when the trajectory, heading, speed, and road geometry make the selected way defensible.
4. Record one short evidence note, for example "trajectory remains on B 462 tunnel carriageway through next 6 fixes" or "GPS scatter overlaps both residential arms; ambiguous".
5. Use `ambiguous` when the evidence is insufficient. Ambiguous cases can remain in the corpus as stress tests but should not be used as binary ground truth.

Recommended categories for balance:

- tunnel or portal transition
- motorway or high-speed same-reference ambiguity
- same-name parallel or divided roads
- same-reference rural or arterial roads
- low-speed intersection or stationary fixes
- low GPS quality or missing course
- logged no-match gaps
- sparse geometry distance fallback
