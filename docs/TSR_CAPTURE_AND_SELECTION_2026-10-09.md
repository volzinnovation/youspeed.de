# Capture-context and simultaneous-sign follow-through — 2026-10-09

Following crop review and exit-context preparation in #27/#28, this work addresses
the bounded next steps in #13/#15 on the current app-foundations source. It does
not close full applicability qualification or establish field accuracy.

## Capture context (#13)

Both production map-fix adapters explicitly leave horizontal camera FOV and yaw
unavailable. When other requirements are satisfied, generic bearing-based
applicability therefore returns `camera_calibration_unavailable`. Synthetic test
snapshots with FOV 80° and yaw 0° do not establish measured calibration for a
phone mount, and passing through the actual map-only adapter removes those fields.

There are useful camera inputs in the existing visual pipeline: iPhone has upright
intrinsics and exposure-clock information in `RoadPathCameraCapture`; Android
CameraX supplies intrinsics and converted sensor exposure time. However,
`RoadPathCalibration` currently assumes zero yaw/pitch/roll. Visual calibration is
an image guide, not a measured camera-to-vehicle transform. It is unsafe to treat
these zeros as calibrated applicability yaw.

The current applicability timestamp is receipt UTC (`Date()` / `Instant.now()`),
while the visual pipeline retains exposure information separately. Thus existing
fixtures that validate immutable supplied snapshots do **not** prove exposure-time
alignment under real camera/inference load. The 1.5-second freshness bound remains
unchanged; newer/future road context must not be substituted for missing context.

Source differences still requiring qualification:

| Concern | iPhone reference | Android | Next action |
| --- | --- | --- | --- |
| Camera geometry identity | Orientation, dimensions and visual revision | Normalized dimensions | Add mount/orientation transition fixtures before changing identity invalidation. |
| Pending map lookup | Drops context while pending | May retain bounded prior context for 6 s / 250 m / 45° | Test delayed capture and provider transitions; the generic applicability gate still rejects the original fix once older than 1.5 s. |
| Exposure time | Available in the road-path capture structure | Available in the road-path frame structure | Bind verified exposure clock and immutable capture-time map snapshot, with unknown/failure cases explicit. |

The shared replay now checks the actual native map-only adapters, exact frame and
road identities, known-FOV/unreviewed-yaw, and a six-frame fresh → threshold →
stale → future → fresh sequence. **58 synthetic scenarios pass Swift/Kotlin
parity, with 176 snapshot-adapter checks; 11 Python tests pass.** Neither production
adapter nor the protected speed-reference policy was changed.

## Surviving simultaneous signs (#15)

Before this change, Android retained the backend's selected detection only if it
survived the active exit/access-road guards. If that strongest sign was withheld,
a lower-scoring valid mainline sign could remain in the frame but never reach
recognition fusion. iPhone already sends all surviving detections to its fusion
selector.

The bounded fix reselects from survivors only when a guard actually withheld a
candidate. Selection follows the unchanged iPhone admission and ranking rules,
including declared raw/calibrated score, per-class qualification, original mapped
semantics and bounding-box validity/area. The shipping `no_overtaking:end` class
is mapped as unknown; it cannot hide a supported speed sign. Existing downstream
Android semantic normalization remains unchanged. It returns the original detection
so raw frame index and physical-track lineage remain intact. With no withholding,
Android preserves its existing backend selection. Collection/annotation evidence
is retained. The tested all-exit-withheld path cannot synthesize a disappearance
or passage; existing access-road passage semantics remain unchanged.

The reference harness executes production Swift fusion directly, using eight full
production files and four verbatim model-enum declarations extracted for host
compilation. It records source, support, fixture and executable hashes. It does
not substitute a Python/Kotlin approximation for the iPhone reference.

**51 Android fusion/orchestrator tests pass. All 14 shared survivor-selection
cases pass the actual Swift reference; two host-harness tests also pass.** The
fixture binds the shipping `no_overtaking:end` mapping to both DE manifests and
separately tests an explicitly mapped restriction-end sign and an out-of-frame
competitor. This proves selection behavior, not parity of all downstream
normalized events. The shared fixture SHA-256 is
`d80bc6b3c9c0897ecaf86f518c8dc4cb5781d8b794e664929b8be572cc9b1fba`.

## Important remaining guard limitation

The existing motorway-exit guard resets fusion and passage state whenever **any**
exit candidate is withheld on both platforms. Android also marks the whole frame
unqualified for passage and secondary display. The Swift secondary-display path
can receive surviving detections independently; that pre-existing display
admission difference remains open. Repeated guarded frames reset confirmation,
so restoring the selected survivor does not prove confirmed mainline speed
activation while the exit remains visible.

This patch changes surviving recognition selection, not the guard-wide activation
rules. A prior valid override remains intact on all-withheld frames. Do not count
this fixture success as a measured reduction in wrong-road acceptance or as proof
that all valid simultaneous signs are displayed. #15 remains open for the complete
sink/lifecycle matrix and reviewed encounter outcomes.

## Next bounded experiment

Use the eligible live encounter ledger to distinguish three questions: did the
extractor recover useful geometry; was the sign assigned to the correct road;
and did the final display/override/passage path retain or reject it correctly?
Include the same simultaneous mainline/exit signs in all three layers. Review the
whole-frame reset and secondary-display behavior against those fixtures before
changing active guard semantics. A calibrated exposure/context provider and useful
semantic segmentation are separate inputs; neither can compensate for a candidate
that never reaches the decision path.

No general enforcement activation, mobile deployment or speed-reference policy
change occurred. Phone timing, thermal performance and real encounter accuracy
remain unmeasured in this work.
