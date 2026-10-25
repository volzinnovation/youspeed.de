# Turnaround device-log review — 24 October 2026

The return drive reproduces a shared limit-reference failure. Both phones kept
100 km/h from an outbound camera end-sign after turning around on the L 340.
Their road match subsequently reported 60 km/h, but the effective limit stayed
100 until town entry. GPS lookup and camera inference continued throughout.
The missing previews and saved-trip results have additional, separate causes.

Times below are **Europe/Berlin (CEST, UTC+2)**.

| Time | Evidence |
| --- | --- |
| 15:51:15 | Both clients applied a camera maximum-speed-end fallback of 100 km/h. |
| 15:52:09–25 | The turnaround traversed ways `178845215`, `935939126` and `723493085`, with changing travel directions. |
| 15:53:20 | Both cameras recognized a 60 sign on the return approach. Android logged `confirmed`, `contextIsCurrent=true`, `displayAccepted=true`, `passageFinalized=true`; these producer fields do not establish active-limit admission. iPhone also logged a confirmed live 60 observation. |
| 15:53:25/26–15:54:34/35 | Android has 71 and iPhone 70 match records with map=60 and effective camera=100. |
| 15:54:20 | iPhone additionally accepted a camera zone-end fallback, replacing the earlier camera evidence with another 100 assertion. This is not proof that a real zone ended; images were not reviewed. |
| 15:54:35/36 | Town entry cleared camera authority and restored the bundle limit. |

## Turnaround continuity

Both adapters detect a direction reversal only when consecutive observations
refer to the **same OSM way**. A different way with the same road identity or
shared relation can restore continuity and cancel a pending departure. During
this turn, the short excursion and subsequent way changes allow the returning
L 340 to be treated as continued outbound travel.

The relevant implementations are
[Swift](../iphone/SpeedConsumerApp/SpeedReferenceRuntime.swift#L168) and
[Kotlin](../android/app/src/main/java/de/youspeed/android/alpha/SpeedReferenceRuntime.kt#L145).
A native Swift replay of the unchanged runtime and approved policy, using a
simplified sequence modeled on these observed ways/directions, reproduced:

- outbound camera 100 remains current after returning to `723493085` in reverse;
- a later bundle 60 on `313163866` still leaves camera 100 current;
- explicit town entry then selects bundle 40.

This isolates a continuity failure consistent with both device traces. It is
not a complete GPS/controller replay. The Kotlin implementation has the same
reversal and continuity conditions; it was inspected but not executed in this
replay.

## Recognition and previews

The cameras did not stop recognizing signs. The return-leg evidence contains
confirmed 60 observations. Representative applicability decisions on both
clients report `camera_calibration_unavailable`, with `displayEligible=false`,
`immediateEligible=false` and `passageEligible=false`. **Those calibration
records run in shadow mode and do not reject live numeric authority.** Code
inspection after the initial review corrected that attribution. The live
supplementary-panel gate requires two distinct, full native context inspections
before admitting a bare numeric sign. Its negative-panel proof previously
accepted only a nearly uniform lower background, so vegetation could leave a
bare 60 unresolved. A retained return-drive photo shows a bare 60 against
vegetation; it does not establish the outcome of every recorded frame.

iPhone preview diagnostics change through `stale_fix` and `current_unusable`
during the turn, then return to `no_target` on the reverse path. At 15:54:32 the
reason is `unresolved_applicability`. They never report a visible return-leg
preview. Source topology also stopped at interior side-path junctions on the
same directed way, reducing the town-approach window to a few metres. Inventory
encounters explain why nearby 60 signs are insufficient:
some have `low_source_confidence` or `no_verified_directed_path`; an accepted
60 association on way `723489307` targets direction +1 while this drive is -1.
Android logs the same source-association problems, including
`target_way_direction_unresolved`, but omit the per-fix preview rejection
reason. Its exact preview decision cannot be reconstructed from that log alone.

There is also an iPhone map-state discrepancy: the driving session identifies
`2026-10-23-v1.5-lookahead`, SHA-256
`34b31aac1dc5a6abacce959afb8ec44043146f5aa4f1ea488c07cb4a68efe09c`.
The copied persistent active-map metadata instead identifies
`2026-10-23-v1.5-journal-conditional`, SHA-256
`e973d279de2803b13037b9e87132be72f28a22d8f9c9bbef79d73093772b1849`.
Android session evidence uses the latter conditional bundle. The earlier
metadata/native-reader city-entry check therefore does not establish which
map the iPhone driving session actually used.

## Saved drive and video

The iPhone **did record the drive**: its checkpointed journal contains one
active trip starting 15:47:48, distance **4,405.294 m**, 670 GPS events, 979 sign
events and 135 media events. The moving return leg is present. The row was
still active at collection, not finalized. Whether the history UI displayed
that row was not inspected.

Android has one active saved trip starting **15:58:05**, after the drive,
with zero distance. Its recording preference is now enabled; the earlier
pre-drive receipt recorded it as unconfigured/off. This is consistent with
recording becoming active later. The logs do not prove the exact preference
change time or show the turnaround disabling recording.

Dashcam video was disabled on both phones during this session. Absence of a
new video is separate from trip-journal recording.

## Evidence and limits

Raw evidence remains outside Git at
`/private/tmp/youspeed-turnaround-20261024/`. That folder contains
`analysis.json`, a SHA-256 `evidence-manifest.json`, and the native replay's
source and `results.json` under `replay/`.

The live iPhone TSR transfer repeatedly stopped at 20 MB. Its complete-line
prefix was supplemented with log messages retained in the checkpointed trip
database, producing `derived/iphone-tsr-reconstructed.log` through 16:00:48.
This is a deduplicated reconstruction, not a byte-identical log copy.
The database and later WAL were copied at different live instants and did not
form a consistent pair. All reported journal queries use the checkpointed
main database with `immutable=1`; both main databases pass `PRAGMA quick_check`.

This report describes the collected build 10065 evidence. The subsequent
owner-authorized repair covers cross-way turnaround continuity, negative-panel
proof, directed previews and the iPhone persistent/in-memory map discrepancy,
plus the requested stop/save dialog. Calibration remains a shadow diagnostic.
Policy 1.1.0 and its approval lock remained unchanged for that build 10066
adapter repair under [the policy governance instructions](../shared/speed-limit-reference/AGENTS.md).
The later, separately owner-approved policy 1.2.0 change is recorded in
[the 25 October review](IPHONE_TRIP_AND_REFERENCE_REVIEW_2026-10-25.md).
