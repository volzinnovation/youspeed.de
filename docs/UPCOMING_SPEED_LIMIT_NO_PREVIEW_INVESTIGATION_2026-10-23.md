# Missing upcoming signs in the first drives

Status: offline investigation completed against the full BW bundle; the cause
of the reported drives is not yet attributed because both phones left before
their new drive logs could be retrieved. Date: 23 October 2026.

## Findings

The complete normal controller pipeline produces previews on both platforms.
This was verified after the drive report using actual startup, coverage routing,
M7 matching, inventory rules, reference resolution, lookup workers and published
UI state. Tests used fresh controlled coordinates and the complete 3.1 GB
database. No main limit or upcoming snapshot was injected.

Three concrete behaviors can explain a much less visible feature than the
300 m maximum suggests:

| Finding | Observed consequence |
| --- | --- |
| Town-entry signs stop prediction and are not candidates | An expected town-entry reduction to 50 will not produce an upcoming 50. The bundle has 31,900 settlement-boundary records, currently used as barriers. |
| OSM way-level speed can change the main value before the physical sign | In a real-controller approach replay, main 70 and preview 50 counted down 48→38→28 m. On entering the sign's way, its OSM tag made main 50 already 5 m before the physical sign; the preview correctly reported `not_lower`. After passage it reported `no_target`. |
| Conservative topology frequently leaves a short final approach | For 51,192 numeric signs with positive same-way data windows, the median is only 25.62 m: 1.84 s at 50 km/h or 0.92 s at 100 km/h. Matching admission and fix cadence can consume that window. Only 6,247 signs have a certified cross-way approach within 300 m and common road-relation membership. |

Repeated or higher numeric limits are intentionally hidden. Pure OSM way-tag
changes without a verified physical numeric station also do not qualify.
The counts above describe potential data windows; they do not include every
current-reference, conflict, camera or freshness gate and are not visibility
rates for the user's route.

## Runtime checks

- **iPhone:** first fix establishes matching; the next 14 fixes show main 70 and
  preview 50 at the expected 48.013 m. Moving along actual source geometry
  decreases the distance to 38.013 and 28.013 m. Direction remains reverse,
  matching stable, generation unchanged and pending context false through the
  way transition. The current-value comparison explains the early hide in this
  replay; no context timeout or publication defect was reproduced.
- **Android:** main70/target50 and main100/target50 each show the preview on
  17/18 fixes after initial admission. Main50/target50 correctly hides it on
  all 18 fixes despite raw candidate evidence. All 54 fixes select the new
  bundle and have a current main reference with no pending context.
- **Physical reader cost:** all 1,025 iPhone and 675 Android full-bundle reader
  attempts were correct. Warm p95 was 3.00 ms and 2.29 ms respectively. A slow
  lookahead query does not explain universal absence in these measurements.
- Both retained driver profiles are M7. Installed version selection already
  deduplicates old same-region bundles, so simply retaining the previous BW
  version does not make it compete with the new version during routing.

These checks do not establish that a preview appeared during the user's real
drive. Physical UI checks were incomplete when the phones disconnected. The
actual route, camera/current-limit history and accepted fix quality remain
unknown for that drive.

## Follow-up when the phones return

Preserve and read the original 10059 drive logs before another install. Verify
the routed database/version, then trace each expected reduction through:

1. Matched way, direction, course accuracy and fix age.
2. Physical numeric station, association/applicability and distance.
3. Topology stop reason and retained raw relation scope.
4. Effective main limit/source before the sign, including camera or voice.
5. Preview candidate, selected/hidden reason, passage and actual UI lifecycle.

The iPhone already logs `upcoming_speed_limit` reason transitions. Android's
matched-fix records can be replayed through the same complete controller; the
offline harness records raw candidate, effective main and visibility gates.
An exact road/limit example can be checked against source data before return.

If the failed route confirms the coverage findings, useful product/data
extensions are previewing an accepted town-entry rule, resolving verified
physical sign transitions at their stations, and certifying a unique legal
continuation within the followed relation at an ordinary junction. Those need
specific source-backed cases and parity tests. Loosening freshness or ignoring
ambiguous paths would not resolve the data limitations.

The governed speed-reference policy and interpreter semantics remain unchanged.
No production behavior change has been made from an unverified drive hypothesis.

Evidence: [coverage analysis](../output/upcoming-speed-limit-no-preview-investigation-2026-10-23/data-coverage.json),
[iPhone controller approach](../output/upcoming-speed-limit-physical-10059/iphone/offline-controller-diagnostics.json),
[Android controller replay](../output/upcoming-speed-limit-physical-10059/android/controller-replay-results.json),
[physical installation/performance record](UPCOMING_SPEED_LIMIT_PHYSICAL_VALIDATION_2026-10-23.md).
