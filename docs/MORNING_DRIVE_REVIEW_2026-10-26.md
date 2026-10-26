# Morning drive review — 26 October 2026

Both attached phones ran version 1.5/build 10071. The cameras recognized 60 km/h
signs in Bad Herrenalb and on the approach to Dobel. Those observations did not
become admitted numeric camera assertions. Earlier camera-derived limits then
remained authoritative while GPS, map lookup and secondary-sign presentation
continued. This is a numeric-admission/reference problem, rather than evidence
that camera inference stopped.

All times below are **Europe/Berlin (CET, UTC+1)**. The device files use UTC.

## Recognition and stale limits

| Local time | Device evidence |
| --- | --- |
| 08:57:34–38 | Android repeatedly reports `maxspeed:60`, including confirmed detections; iPhone confirms 60 at 08:57:35.903. Both subsequently publish bundle-derived 60. This does not establish admission of the camera observations. |
| 08:58:33.903 / 08:58:34.075 | iPhone / Android apply a camera maximum-speed-end fallback of 100. Whether every end-sign interpretation was visually correct cannot be established from logs alone. |
| 09:02:05–08 | Android again confirms `maxspeed:60`. iPhone confirms 60 at 09:02:06.928, with additional confirmed observations through 09:02:08.353. |
| 09:02:07/08–21 | Android has 15 and iPhone 14 match records with map=60 but effective camera=100. The selected ways and map results continue updating. |
| 09:02:22 | Town entry retires the old camera reference and both clients select bundle 50. |

During 08:56–09:06, the iPhone has 22 live-frame records explicitly reporting
`speed_kmh=60`. Android has 14 inference records with primary class
`maxspeed:60`, ten marked confirmed. Producer diagnostics such as
`displayAccepted=true` and a passage track becoming armed/committed do not prove
that the primary speed display admitted that numeric claim. Neither platform's
reference-offer diagnostics contain an admitted camera 60 in this interval.

The live numeric parent gate requires native supplementary-panel inspection
and two distinct qualifying source frames for a bare sign. On iPhone, all ten
recorded native OCR attempts for `maxspeed:60` in this interval report
`no_separate_plate`, no text and no OCR passes. That diagnostic does **not** by
itself certify that the complete lower context is free of panels. The controller
keeps the parent unresolved, logging `pixel_verification_pending` and
`applicability_not_verified`. Android's nine corresponding OCR attempts report
eight `unresolved_lower_region` decisions and one `unread_or_ambiguous_panel`.
The controller consequently never acquires the required plain-sign proof.

The applicability/calibration diagnostics run in **shadow** mode. A shadow
`camera_calibration_unavailable` decision is not, by itself, the explanation for
live numeric rejection. The iPhone controller's `applicability_not_verified`
label also covers an unverified assembly path; it does not isolate calibration
as the live cause.

Both clients' presentation telemetry records secondary updates during the
camera-100 episode, including dangerous-liquid restrictions, pedestrian
parking, roadworks, pedestrian prohibition, hazard and priority signs. iPhone
records presentation lifecycles; Android records Compose lifecycles. Neither
telemetry stream is proof of compositor pixels, but both corroborate the user's
observation that the secondary path continued running.

The later drive also contains further camera/map disagreements: 418 iPhone
and 130 Android match records across the copied morning sessions. These totals
are disagreements between sources, not a count of visually verified wrong
limits. They include limits other than 60 and differ between platforms.

The owner's follow-up explicitly requested independent processing with primary
speed limits first, secondary signs next and plate detection last. The resulting
repair is described below. The shared reference policy remains 1.2.0 with its
original approval lock and interpreter semantics.

## Recognition repair

Both clients now publish a qualified confirmed numeric parent through their
existing road, spatial, source and passage gates without waiting for plate OCR.
An absent, failed, deferred, unread or ambiguous plate result cannot withhold an
otherwise admitted primary. Positive, source-matched plate/restriction evidence
can still withdraw or revise **its own** parent. Applying a parsed condition
continues to require the existing two distinct complete source-frame proofs.
Unknown auxiliary evidence is no longer treated as positive plate evidence.

iPhone plate work runs on a separate serial queue with one active job and only
the latest pending frame; its tracker state and crop context belong to that
queue. Android releases primary frame admission before invoking its independent
bounded plate worker and copies the admitted native crop before its backend
recycles the source window. A stalled OCR worker therefore cannot stop later
primary detections. OCR callbacks are supplementary-only: they do not replay a
passage, primary recognition or capture side effect.

Numeric selection and secondary presentation use independent candidates. A
stronger speed detection does not hide a weaker valid secondary sign, and a
stronger secondary does not replace a qualified speed candidate. Each stream
keeps the spatial-applicability decision for its own physical sign. Optional
collection work follows primary and secondary publication. An ordinary numeric
candidate also avoids waiting behind an unrelated zone-panel OCR check;
zone-only observations retain their existing native proof requirement.
Dismissal also follows each stream's own physical track: dismissing a numeric
sign cannot suppress a different secondary sign or its supplementary text, and
dismissing a secondary sign cannot suppress a different numeric parent.

Generation, capture session, context, bundle, traversal, physical-parent,
frame/timestamp, class, speed and source-box checks remain in force. Auxiliary
authority accepts only source observations aged 0–3 seconds. Newer camera
parents and driver/voice corrections remain protected from late older OCR;
original sighting time/distance still anchor any condition's lifetime. Cached
presentation text never counts as a new source-frame proof.

## Trips and implemented cleanup

The checkpointed iPhone journal contains the completed 08:56:02–09:38:02 drive,
measured at 31,026.508 m. Android's consistent snapshot contains the completed
08:56:19–09:38:21 drive, measured at 29,372.043 m, with ending odometer 54,704 km.
The difference in accumulated distance has not been investigated in this task.
Both completed drives have approximately 21.75 km of endpoint separation.

Later active sessions are also present: iPhone measured 68.543 m with about
62.21 m endpoint separation; Android measured 62.216 m with about 80.42 m
endpoint separation. The snapshots were taken at different times. Manually
deleted rows are not reconstructed or restored.

The owner explicitly selected **straight-line distance between start and end**,
rather than driven distance. Both clients now discard a trip on closure if its
first and last usable GPS fixes are less than 100 m apart. This includes loops
ending near their start, even after driving over 100 m. Stationary endpoints
count; invalid, network-only, duplicate and out-of-order fixes do not. Empty
zero-distance sessions are discarded; missing endpoint evidence on a nonzero
trip does not prove that it was short.

While endpoint separation is below 100 m, evidence is buffered internally so a
real trip can continue, but the active recording is omitted from the Fahrten
table and the stop button is unavailable. Crossing 100 m enables the normal
history/stop flow; returning within 100 m withdraws both again. Stop/save also
recheck eligibility, so an older visible control cannot save a now-short trip.

Cleanup applies to explicit stopping, recording disablement, long foreground
interruptions, completion of the existing finalizer and interrupted-session
recovery. Active trips remain available to accumulate movement. Existing
completed history and explicitly restored backups are not retrospectively
filtered. Trip events, bindings and temporary exports are deleted; lifetime
counters and independent media remain. Late callbacks cannot resurrect deleted
ownership. A discarded stopped trip skips the odometer editor and still rearms
recording on movement. The stop controls on both platforms now share explicit
17 pt/sp semibold text, an 18 pt/dp stop symbol and 48 pt/dp minimum height. The
large zero is hidden only while the stop control is presented; it remains
visible at the beginning of a trip. The shared contract is documented in
[`shared/trip-journal/README.md`](../shared/trip-journal/README.md).

## Evidence and validation

Private raw evidence, derived summaries, SHA-256 manifest and test logs are
retained outside Git at `/private/tmp/youspeed-morning-20261026/`. No private
coordinates or raw device logs are included in this report.

The iPhone match copy contains 2,889 complete records, 08:56:02–09:48:39.
Its live TSR transfer ended with a socket error after approximately 76 MiB;
complete lines extend through 09:39:43 and cover the reported Bad Herrenalb /
Dobel passages. The trailing incomplete record is excluded from analysis.
Journal figures use the checkpointed main database opened with `immutable=1`,
which passes `PRAGMA quick_check`; no consistent live WAL pair is claimed.

Android has 2,910 morning match records, 08:56:20–09:48:37. The initial streamed
journal copy changed during transfer and failed integrity checks, so it is not
used for conclusions. A second copy was staged on-device while the parked app
was briefly suspended, then the app immediately resumed before transfer. That
main/WAL snapshot passes `PRAGMA quick_check`. Temporary staging was removed.

iPhone's final simulator run executes 191 native tests: 190 pass, with zero
failures and one optional private external-image fixture skip. The earlier
stop/odometer UI test also passes.
It includes 33 journal tests, 64 passage tests, runtime/fusion cases and the
recognition/controller regressions. All 20 conditional tests pass, including
the four-second stale-source case and both directions of independent dismissal.
Android passes
275 focused JVM cases and 39 emulator instrumented checks with no failures or
skips. Instrumented coverage includes trip recording/history/sharing, stop and
odometer UI, and native conditional-camera controllers.

Portrait and landscape simulator/emulator screenshots were inspected for the
stop control's typography, spacing and absence of the large zero. Initial-trip
screens retain the ordinary zero and unit. These are controlled fixture states;
the repaired recognition has not yet been validated on a new road drive.

Recognition regressions hold OCR blocked while later frames publish a new 60
and secondary signs, reject delayed output after stop/scope changes, reject
same-session stale source frames, preserve a newer camera/voice parent, and
exercise simultaneous stronger numeric/weaker secondary candidates with
separate spatial owners. Dismissing either stream leaves the other stream and
its own supplementary text eligible. Trip cases cover the 100 m threshold and returning
near the start, a driven loop over 200 m with a nearby endpoint, preserved
counters/media, export cleanup, late callbacks, recording rearm, empty recovery,
finalization and retained-trip metadata/odometer behavior.

Test receipts and iPhone results are in
`/private/tmp/youspeed-recognition-20261026/`; Android's final JVM log is
`/private/tmp/youspeed-recognition-final-jvm-20261026.log`. The stop-layout
emulator logs and screenshots use the
`/private/tmp/youspeed-stop-20261026-` prefix. Existing retained-trip fixtures
were extended past 100 m, and an old active-row place assertion was aligned
with the captured-evidence/finalizer contract. Android verification uses the
isolated `.testhost` package with build 10072, separate from the attached
driving app. Neither test application replaces a driver's normal app.

The final Android receipt is
`/private/tmp/youspeed-stop-20261026-android-verified39.log`; its clean isolated
build is recorded in `...-android-clean-final-build.log`. Verified German stop
screenshots use `...-android-final-portrait-de.png` and
`...-android-final-landscape-de.png`; the initial-zero state uses
`...-android-final-initial-zero.png`. iPhone screenshots use
`...-iphone-portrait.png`, `...-iphone-landscape.png` and
`...-iphone-initial-zero.png`. The task's temporary Android emulator was closed
after verification.

The final iPhone native log is
`/private/tmp/youspeed-recognition-20261026/iphone-dismissal-final-escalated-tests.log`,
with `dismissal-final-escalated-tests.xcresult` in the same directory.
`source-receipts.json` and `implemented-changes.patch` there identify the final
reviewed sources, validation logs and layout screenshots.

At completion of this initial review, no driving app had been replaced and no
deployment, commit, push, merge or publication had been performed. The owner's
subsequent commit, push and attached-device deployment request is a separate
follow-up to this review.
