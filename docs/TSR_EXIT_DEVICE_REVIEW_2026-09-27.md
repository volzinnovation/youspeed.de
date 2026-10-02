# Exit-limit device review — 27 September 2026

## Findings

The retained Android history reproduces the reported pattern: a sequence of low
limits becomes camera-authoritative while the matched road remains a motorway
with a higher bundled limit. The current exit guard often cannot run because
its road snapshot is too old, and it can first see a sign before that sign reaches
the rightmost image region. Additional preprocessing is useful, but a right-side
mask alone does not address either problem.

The iPhone's retained application logs cover only the latest French drive,
14:54:02–15:25:36 UTC (16:54–17:25 local time). All 1,698 applicability batches
are FR: 1,509 primary-road batches, 118 trunk-road batches, and 71 without road
context. There are no motorway batches or Swiss inference batches in this file.
`DriveSessionViewModel.clearDrivingLogsOnAppLaunch()` deletes the older TSR and
match logs and truncates GPS history. The current file therefore cannot verify
what the iPhone used during the earlier Swiss drive. A separate historical
system-log collection was attempted but failed with exit 77: administrative
privileges are required. No device logs were cleared during this review.

Android retained 118,322 complete diagnostic records from 24–27 September,
including 78,947 applicability batches and 27,836 motorway batches. These are
frame/event counts, not independent signs or accuracy measurements.

## Concrete exit example

Android diagnostic lines 116458–116490, **27 September 19:01:36–19:01:44 local
(17:01 UTC)**:

| Time UTC | Mainline OSM way | Map km/h | Recognized sign | Centre x | Evidence |
| --- | --- | --- | --- | --- | --- |
| 17:01:36.538 | 537753532 | 110 | 70 | 0.525 | No exit branch; road snapshot 2.71 s old |
| 17:01:37.092 | 537753532 | 110 | 70 | 0.541 | Camera state applied; road snapshot 3.26 s old |
| 17:01:39.072 | 537753528 | 110 | 70 and 50 | 0.769 / 0.553 | Exit way 537753538, 24 m away; snapshot 2.11 s old |
| 17:01:40.388 | 537753528 | 110 | 50 | 0.628 | Camera passage/state events adjacent; snapshot 3.36 s old |
| 17:01:42.628 | 442035060 | 110 | 30 | 0.638 | Camera state applied; snapshot 2.90 s old |
| 17:01:44.168 | 442035060 | 110 | 30 | 0.819 | Finally withheld: `motorway_exit_ambiguous_speed`; snapshot 1.34 s old |

The 70, 50 and 30 observations and CAMERA applications are supported by the log.
Legal lane applicability still needs synchronized imagery/manual annotation;
the log alone cannot establish that every low sign in the history belongs to
an exit. This sequence is a strong reproduction candidate, not an accuracy label.

Both clients use the same narrow guard: stable motorway, map limit at least
100, candidate 30–90, linked outgoing motorway ramp within 350 m, compatible
heading, accurate GPS/course, snapshot age at most 1.5 s, and candidate centre
x at least 0.6. A matching left/central repeat exempts a candidate.

Across the retained Android history, **784 recognition-eligible lower-limit
motorway candidate samples** match the speed conditions. Of those:

- 739 have road snapshots outside the guard's 0–1.5 s freshness window.
- 598 have centre x below 0.6.
- 536 lack a linked motorway-ramp branch within 350 m in that snapshot.
- Only five diagnostic decisions contain `motorway_exit_ambiguous_speed`.

Conditions overlap. Neither 784 nor 739 is a count of false signs. The five
verdicts can include repeated observations of a track.

General applicability defaults to `shadow` in Swift and Kotlin. An UNKNOWN
verdict such as `stale_road_context` or `camera_calibration_unavailable` does not
block normal recognition; only the explicit exit/access-road guard reasons do.
Consequently a stale snapshot can disable exit suppression while recognition
continues to publish the low limit. A late rejected frame also cannot undo an
already accepted camera claim by itself.

## Model identification

| Evidence | Model |
| --- | --- |
| Retained iPhone session | `fr-panoramax-bootstrap-evaluation-v1`, ready 15:00:22 UTC |
| Android Swiss model-loaded event | `ch-panoramax-bootstrap-evaluation-v1`, 13:28:09.799 UTC / 15:28 local, line 94008 |
| Installed Android APK, extracted and hashed | CH classifier `ch-classifier-bootstrap-v9`, shared sgblur YOLO11n Panoramax detector |
| Current iPhone repository CH pack | Same classifier source checkpoint v9; Core ML export |

The detector is `sgblur-yolo11n-panoramax-169451970702aca0`, source revision
`169451970702aca0dde9ff3106dba0f67e0b88a8`, checkpoint SHA-256
`698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a`.

The Swiss classifier is
`panoramax-classify-ch-road-signs-ch-classifier-bootstrap-v9`, source SHA-256
`984c63ecb7dda0a4faf4e49ea3461e5cdf0ffb820dbb90fd2f57efdd87ac5dbc`.
The actual installed Android classifier bytes hash to
`eb59c48a0dc5ff1adb1b488b1f3bddfda7324a152ed51e7d7df7c99b43f5b72e`,
and the actual detector bytes hash to
`e5490acd60ceb015336bed487b5e247c2728b2b98b6336790bf6ffe02a6f7207`;
both match the APK manifest. The repository iPhone classifier export hash is
`7ac5f120f208fa824b26f4ece9e7cfb268ca34b7d1680046d8071eb55749c1f7`.

**A loaded pack is not evidence of successful live recognition.** All retained
Android applicability batches identify FR. There are no inference/applicability
records between the CH load at 13:28 and the next FR load at 15:27. During this
interval there are road-context diagnostics, capture configuration changes, and
2,125 FR switch requests. Some of this interval has recognition disabled, so the
absence is not by itself proof of a model failure. The Swiss success reported
on iPhone is useful field evidence, but cannot be attributed conclusively to v9
from the retained iPhone log.

The `modelId` in frame logs is the **detector hash**, shared between country packs;
it cannot identify the country classifier. Future lifecycle/frame diagnostics
should include pack ID, classifier hash, detector hash, and country together.
The FR classifier packaged on Android is the Panoramax checkpoint at revision
`7f2bdd58f20b3dfc7161c5aea7c672ce02749c8f`, not the Swiss v9 classifier.

## Proposed preprocessing and runtime change

The repository already generates `motorway_exit_approach` through
`scripts/map/motorway_exit_context.py`: legally directed, endpoint-connected
mainline traversal up to 350 m across way splits. It stores mainline way,
endpoint, exit way, network distance, and branch heading. Reuse this mechanism.
The new Swiss local bundle includes it; older regional bundles may not.

Extend it to **directed subsegments**, rather than marking an entire OSM way:
`way_id`, travel direction, along-way start/end offsets, exit anchor/way,
branch side, action/reason, source provenance, and capability version. Long ways,
left exits, opposite carriageways, entrances, and overpasses need distinct
handling. Derive departure side from the mainline and branch geometry; geographic
proximity alone is insufficient.

On each client, resolve the active segment against current matched progress.
Admit/withhold candidate tracks before immediate display, passage confirmation,
and persistence. Preserve the decision for the same physical track across
subsequent frames and relevant mainline way splits. End it after leaving the
segment or confirming travel onto the ramp. Restore normal recognition there.
A camera-mounted-right exit sign can start near image centre: replay this
sequence before choosing a sector threshold. Preserve genuine mainline signs
and paired repeats, including roadworks and overhead signs.

Fix snapshot freshness/coherence and log each failed guard condition. Do not
simply lengthen the freshness threshold or switch all applicability to enforce:
that could use an old road after a real departure or suppress ordinary signs
without camera calibration.

A common spatial index can later serve sensitive-area exclusions, but keep
separate actions. Exit filtering concerns sign applicability. A military-area
capture exclusion must be enforced before recording, QA-image persistence and
upload, and may require full capture suppression when projection is uncertain.
A TSR-only mask would leave the original images in those other outputs. No
military zones, legal buffer distances, or new schema have been activated here.

Acceptance replay should include this exact 70→50→30 sequence, long/split ways,
left exits, adjacent unconnected roads, stale GPS, actual ramp departure,
mainline roadworks, camera rotations/mirroring, and both platforms.

## Disregard-vision design

[Design sheet](designs/disregard-vision-2026-09-27.png) ·
[Editable SVG](designs/disregard-vision-2026-09-27.svg) ·
[Transparent icon](designs/disregard-vision-icon.svg)

Use the existing eye language: angular outer edges, outlined centre circle, and
a diagonal strike. White 2 pt strokes; 32×24 pt glyph inside a 48×48 pt touch
area; no filled eye or enclosing button ring. Portrait: upper left in the former
debug location, inside the safe area. Landscape: lower left of the sign pane.
Keep it separate from recording controls; arrange any sign pictogram so it does
not cover the action. Show while TSR is active, dim/disable without dismissible
camera evidence. Provide the accessibility label “Disregard vision, use road
limit” and a brief acknowledgement after a successful tap.

One tap should withdraw current visual evidence, invalidate pending results,
suppress the same sign/track from immediate resurrection, and reselect the
current valid road limit. TSR remains running for subsequent signs. Do not
write the road limit as a user correction or alter map data. Preserve an actual
voice correction; if no road reference is available, show unknown rather than
reviving the rejected camera value from last-known memory.

The owner subsequently approved this design and implementation. The button is
now implemented in both clients, with controller-level parity tests and the new
owner-approved reference policy 1.1.0. See the follow-up below. No attached
phone was updated during this work.

## iPhone voice routing change

The existing speech capture activated `.record`/`.measurement` without selecting
an input. The local patch now requests `.builtInMic` after activating the audio
session, records the resulting input route, rejects invalid audio formats before
installing the input tap, and clears its preferred input on completion. An
unavailable microphone follows the existing visible capture-failure path.

This follows Apple's [preferred input API](https://developer.apple.com/documentation/avfaudio/avaudiosession/setpreferredinput(_:)).
It addresses an app-started correction on the phone. It cannot intercept the
CarPlay/steering-wheel Siri trigger: Apple's [CarPlay voice instructions](https://support.apple.com/guide/iphone/use-siri-in-your-car-iph0aa8c80e6/ios)
assign that control to Siri. Being the foreground iPhone app does not provide
a documented override. App Intents/Siri commands or an approved CarPlay app
button would be separate integrations; this repository has no CarPlay scene.

Validation: iOS Simulator build passed. Existing controller regressions
`testCancelledSpeedCaptureCannotEndRetryOrDiscardPreviousCorrection` and
`testMapAndCameraUpdatesCannotReplaceActiveVoiceCapturePresentation` each
passed. These verify capture-state behavior, not physical microphone routing.
No app was installed or launched on either attached device by this review.
Wired/wireless CarPlay, speech capture, interruption and route restoration still
need a physical in-car check before calling the routing problem fixed.

## Evidence retained locally

Raw copies are under `/tmp/youspeed-iphone-review-20260927/` and were not added
to Git or uploaded. This is temporary local storage; preserve it before cleanup
if needed for annotated replay. The design and this report are in the repository.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `20260927_145402_716_tsr_log.ndjson` | 4,730,367 | `73a09fc4545cc3f6eeda402afe9a6075d96989793b1d83375371455d7074e323` |
| `20260927_145402_714_drive_match_log.ndjson` | 5,230,969 | `31c5f0961d362cced4eb12cc9d1a7f4c0803615f9b3717bcea3d2c96024ccff1` |
| `android/runtime_diagnostics.ndjson` | 342,725,542 | `76800e88d1a8e3ec76f97efc280a5d1b2bfafa04c5600db5cb93263f1cede304` |

Also retained: installed Android APK/CH manifest, Android analysis JSON,
iPhone diagnostic reports, active-bundle records, GPS/current match logs,
Android logcat, build/test logs, and the unsuccessful system-log collection log.

Recommended diagnostic follow-up: bounded per-drive history instead of deleting
all iPhone logs on launch, plus explicit classifier identity and snapshot age in
both clients. Existing unrelated Switzerland/bundle work was preserved.

## Follow-up: grey-circle investigation and implemented changes

The owner approved the button's artwork, position and size, accepted the Swiss
classifier based on successful field experience, and requested the road-context
investigation and fixes on both clients.

### Grey circles: confirmed producer bug

All 1,445 retained iPhone drive-match records have a selected road and numeric
speed: 818 primary-road matches, 474 primary-road camera overrides, 136 trunk
matches and 17 service-road matches. There are no no-match records in that
retained session. An unresolved end sign at 15:08:18 UTC is followed by repeated
`T15 / camera_scope_invalidated` transitions every second from 15:08:19 through
15:10:01, despite fresh road evidence. T15 clears the current bundle reference
as well as visual authority, so repeatedly emitting it undid each successful
road update and displayed grey last-known information.

Android has the same producer call pattern and 60 logged LAST_KNOWN transitions
with reason `camera_scope_invalidated`; examples start at 12:03:25.208,
12:03:27.552 and 12:03:30.608 UTC for way 377804827. Its history also contains
132 `context_pending`, 82 `road_relation_exit` and eight `context_missing`
LAST_KNOWN transitions. These are event counts, not durations or independent
road-matching failures. The latter categories were not disabled or retuned.

Both native adapters now withdraw authority once per physical evidence ID.
A fresh bundle update after an unresolved end remains authoritative on later
reconciliation/publication. A different unresolved sign can still withdraw
authority. The shared expiry, priority and context thresholds remain unchanged.

### Geometry finding

`pack_runtime_artifacts_pyosmium._downsample_coords` already returns every
source vertex. The compatibility `max_points` argument does not truncate roads;
new geometry rows declare `source_vertices_v1`. Older installed bundles can
still contain the legacy 24-point sampling and need regeneration to gain the
precision improvement. Removing simplification a second time would not fix
the reproduced grey-circle loop. No national bundle was rebuilt or published
as part of this follow-up.

### Dismissal and Swiss acceptance

Both controllers clear visual resolver/immediate claims and camera-derived
last-known memory on dismissal, preserve current road/voice claims, and suppress
same-track and pre-dismissal queued evidence. Recognition remains enabled for
new signs. The 32×24 outlined glyph uses a 48×48 hit target at portrait upper
left and landscape lower left; it dims when no visual evidence can be dismissed.
Four-language accessibility labels are included. Policy 1.1.0 adds only the
owner-requested dismissal semantics; published 1.0.0 files are untouched.

The [Swiss acceptance record](../shared/tsr/field-acceptance/CH-v9-2026-09-27.json)
pins classifier v9 and both platform exports. Existing bundled selection already
uses it. This records the owner's field acceptance without inventing statistical
calibration results or changing the signed download registry.

### Verification

- Shared policy: 39 scenarios, 171 steps, all 16 transitions and five states;
  artifact hashes and both native pins match.
- iPhone simulator: nine targeted native/controller tests passed, including
  repeated unresolved-end publication, dismissal and voice-capture preservation.
- Android: seven native unit tests passed; APK built. The emulator controller
  test passed for fresh-road recovery, visual resolver clearing and voice
  preservation. Tests use an isolated app-data fixture.
- Bundle geometry/settlement: all 25 source-to-bundle tests passed with
  osmium 4.3.0 and Shapely 2.1.2, including preservation beyond 24 vertices.

The attached iPhone and Android app installations were not changed. Physical
in-car voice routing still needs verification. Automatic exit-sector masking
and sensitive-area capture exclusion remain the separate preprocessing proposal
above; they are not claimed as implemented by the grey-circle fix.

## Authorized device deployment — 27 September, 21:51–21:53 local

Following the owner's explicit deployment request, rebuilt and installed both
apps in place: iPhone 14 Pro (`de.youspeed.SpeedConsumer`, 1.2 / 10015) and
moto g86 5G (`de.youspeed.android.debug`, 1.2-debug / 10015). Both built packages
contain reference policy 1.1.0. No app-data clear or uninstall was performed.

On the attached Android, the isolated reference-controller regression and
normal-launch smoke test both passed. The normal app was relaunched afterward;
the dashboard and the lower-left landscape dismissal control were verified
on its actual display. The control correctly dims without camera evidence.

The iPhone installation succeeded, but launch was denied by iOS because the
phone requires its passcode. The owner was asked to unlock it; launch and
QuickTime screen verification remain pending that unlock.
