# Build 10059 — physical BW lookahead validation

Date: 23 October 2026. This records the device installation and controlled
measurements separately from the user's subsequent report of missing previews
in real drives. Investigation of that report is ongoing; native-reader success
does not establish normal-drive visibility.
The machine-readable summary is
[UPCOMING_SPEED_LIMIT_PHYSICAL_VALIDATION_2026-10-23.json](UPCOMING_SPEED_LIMIT_PHYSICAL_VALIDATION_2026-10-23.json).

## Installed devices and data

- iPhone 14 Pro, iOS 26.6.2: normal `de.youspeed.SpeedConsumer`, version 1.5,
  build 10059, updated in place. Normal executable SHA-256:
  `8f712749739d6207008f11ed9fecd13fe68befa7131b0166e26bd50ccbe0e8cf`.
- Moto g86 5G, Android API 36: existing `de.youspeed.android.debug`, version
  1.5-debug, build 10059, updated in place. Installation APK SHA-256:
  `7fdcb48186846c9131431319425a5d776ce9d435ce661ff25ead06a2016704cb`.
- Both received the full **2026-10-23-v1.5-lookahead** BW database in a new
  versioned directory. On-device database size **3,099,021,312 bytes** and
  SHA-256 `34b31aac1dc5a6abacce959afb8ec44043146f5aa4f1ea488c07cb4a68efe09c`
  were verified. Older maps were retained and active-state metadata was updated.

The iPhone's immutable normal app was restored after native XCTest validation.
An artifact audit then found an unused old test plug-in in the reused normal
build product. It is not invoked on an ordinary app launch; the executable is
10059. The original artifact/evidence is retained and a separate clean artifact
is being prepared for the phone's return. This is not evidence of the cause of
the missing preview.

Evidence is under
[`output/upcoming-speed-limit-physical-10059`](../output/upcoming-speed-limit-physical-10059/).
Raw device identifiers and installed container paths are local evidence.

## Full-bundle measurements

All figures below use the complete installed database, not the small extracted
probe. Public source-backed approaches include 25 different current and target
ways, 12 forward and 13 reverse approaches, and numeric limits from 30–100 km/h.
Every measured attempt is retained, including absent previews or a different
road chosen by the matcher. The table reports receipt medians and nearest-rank
tail percentiles.

| Device / operation | Samples | Median | p95 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| iPhone preview reader, fresh connection | 250 | 1.210 ms | 5.514 ms | 10.950 ms |
| iPhone preview reader, warm | 750 | 0.831 ms | 2.996 ms | 3.185 ms |
| Android preview reader, fresh connection | 50 | 5.131 ms | 10.829 ms | 29.304 ms |
| Android preview reader, warm | 625 | 1.166 ms | 2.290 ms | 4.514 ms |
| iPhone complete V3 lookup, fresh connection | 25 | 33.328 ms | 56.281 ms | 461.017 ms |
| iPhone complete V3 lookup, warm | 750 | 12.945 ms | 23.326 ms | 25.043 ms |
| Android complete V3 lookup, fresh connection | 5 | 168.086 ms | 322.925 ms | 322.925 ms |
| Android complete V3 lookup, warm | 125 | 123.382 ms | 186.807 ms | 205.030 ms |

Fresh connection is **not storage-cold**: operating-system cache state is
uncontrolled. No global cache was dropped. The external preview wall timer
includes the reader's call, with connection-open time recorded separately.
Android includes geometry retrieval/projection inside its reader; iPhone
receives geometry/chainage from its matcher, so the two reader measurements
cover different work. Complete-service workloads also differ: iPhone covers
all 25 cases, Android the first five. These are platform-specific measurements,
not a controlled comparison of device speed.

All **1,025 iPhone** direct-reader attempts (including 25 recorded warmups) and
**675 Android** direct-reader attempts returned the expected physical sign,
limit and distance. No reader returned a budget-suppressed or nil result.
Android's one 29.304 ms external fresh-reader outlier includes lazy capability
setup outside its internal traversal timer; its internal maximum was 14.895 ms.
The 25 ms traversal limit is cooperative and cannot cancel an active SQLite read.

The actual post-station primary inventory offer was checked on five iPhone
anchors and all 25 Android cases; the normal resolver returned the expected
limit and the post-station reader excluded the passed sign. Passage, jitter,
relation departure and freshness have controlled replay coverage. An actual
Android three-second expiry/clock-rollback test also passed on the phone.

Raw measurements:

- [iPhone final performance](../output/upcoming-speed-limit-physical-10059/iphone/performance-final.json).
- [iPhone first strict run](../output/upcoming-speed-limit-physical-10059/iphone/performance-first.json), retained after a test expectation exposed matcher unavailability.
- [Android raw attempts](../output/upcoming-speed-limit-physical-10059/android/full-bundle-results.json)
  and [summary](../output/upcoming-speed-limit-physical-10059/android/performance-summary.json).
- [Protocol](../output/upcoming-speed-limit-physical-10059/protocol.json) and
  [query-plan review](../output/upcoming-speed-limit-physical-10059/query-plan-review.json).

## Admission and visibility limitations

The existing full matcher did not select the expected road in four of 25
iPhone cases (124/775 calls). All 651 calls selecting the expected road returned
the correct preview evidence, and no preview appeared without a selected road.
Android's first anchor had no match in all 26 calls; the other four anchors
returned correct evidence in all 104 calls. These failures remain in the
performance distributions. They are not counted as preview success. The
protected speed-reference policy was not changed.

The direct-reader test supplies qualified known-road evidence. It does not prove
that the final current limit is higher than the target: some sample signs are
repeaters or increases and should be hidden. For example, source case 3 has an
active inventory 70 km/h offer and an upcoming 50, while case 4 already has 50
and its upcoming 50 should stay hidden.

Physical UI validation did not complete before the phones left. QuickTime
confirmed the normal iPhone app launched to its retain-logs prompt; later physical
UI tests were blocked at the locked-device preflight and executed no cases.
Android's first layout case passed circle separation but stopped on an
inconsistent supplementary-plate fixture assertion. Its final preference
comparison passed. Neither result establishes a normal-drive preview being
visible. The earlier six simulator and 12 emulator layout combinations remain
separate evidence.

## Investigation after the first drives

Both phones are disconnected, so their new drive logs have not been retrieved.
Offline checks subsequently exercised each actual controller, worker, router
and main-limit resolution path, using fresh fixes and the full database without
injecting a main limit or upcoming snapshot. Both passed:

- iPhone: first fix establishes admission; fixes 1–14 show actual main 70 and
  upcoming 50 at 48.013 m. Moving along the source geometry counts down to
  38.013 and 28.013 m. At the first origin-way fix, 5 m before the physical sign,
  the main limit becomes 50 from that way's existing OSM tag and the preview
  reports `not_lower`. After passage it reports `no_target`. Direction remains
  reverse, matching stable and pending road context false. There is no hidden
  eight-second wait in the captured transition.
- Android: all 54 frames route to the new lookahead version. Case 3 (main 70,
  target 50) and case 5 (main 100, target 50) show the preview on 17/18 frames
  each, after initial matching. Equal-limit case 4 has a raw target on 17/18
  frames but correctly hides the preview on all 18. Main-reference `current`
  is true and pending context false.

These normal-controller replays did not reproduce a universal publication or
visibility failure. They do demonstrate how an OSM way-level value can make
the main limit change before the physical station, immediately removing the
preview through the strictly-lower comparison. The direct post-station primary
rule checks above remain valid; they should not be described as exact physical
station promotion of the displayed main value.

Evidence:
[iPhone controller diagnostics](../output/upcoming-speed-limit-physical-10059/iphone/offline-controller-diagnostics.json),
[Android controller replay](../output/upcoming-speed-limit-physical-10059/android/controller-replay-results.json).
The Android agent also reran all 12 corrected layout combinations successfully
in the isolated emulator; those are separate from the incomplete physical UI run.

The [bundle-wide coverage analysis](../output/upcoming-speed-limit-no-preview-investigation-2026-10-23/data-coverage.json)
found 51,660 unique numeric post-station origins. Of those, 51,192 have a positive
allowed same-way approach window, but its median is only **25.62 m**: about
1.84 seconds at 50 km/h. Only 14,816 have at least 50 m of same-way approach and
6,247 have a certified cross-way approach within 300 m with common relation
membership. Conservative junction/restriction stops can leave very little time
for a fresh stable match before passage. These counts omit current-reference,
camera and intervening-event gates and are not drive visibility rates.

The current feature also treats **31,900 settlement-boundary signs as barriers**;
it does not preview their implied town-entry 50. An OSM way-tag speed drop without
a verified physical numeric sign is likewise outside the current preview scope.
An exact route/limit example or returned drive logs are needed to attribute the
user's missing previews to a specific gate, data gap or integration defect.
