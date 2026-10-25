# Turnaround and automatic trip save — 24 October 2026

This is the historical build 10066 receipt. Build 10067 replaces the automatic
15-second prompt with an explicit Stop-at-zero action and persistent odometer
editor, and activates owner-approved reference policy 1.2.0. See
[the current behavior and validation](IPHONE_TRIP_AND_REFERENCE_REVIEW_2026-10-25.md)
and [device deployment](V1_5_DEVICE_INSTALL_10067_2026-10-25.md).

The owner authorized the turnaround, rejected 60-sign, missing-preview and
iPhone map-state repairs, plus a stop/save dialog in both clients. The selected
stop delay is **15 seconds**. Build 10066 / version 1.5 is installed in place on
the attached iPhone 14 Pro and Moto g86 5G. Recording remains enabled on both.
Existing maps, trips and capture preferences were retained.

## Behavior

- **Turnaround:** remember accepted travel direction per OSM way across
  intervening ways. Preserve a pending reversal on the same followed road or
  relation through those segments. The existing eight-second confirmation
  clears the old reference scope; both controllers also retire camera producers
  and pending conditional tracks. An old physical evidence ID cannot restore
  the outbound limit. Published policy 1.1.0 and its approval lock are unchanged.
- **Bare 60 signs:** the native supplementary-panel scan can prove a textured
  vegetation background clear of a panel. It rejects coherent panel-sized
  surfaces, ambiguous frames, darkness and undersized crops. Two distinct
  native frame inspections and the existing parent, crop and known-plate gates
  still apply. Calibration remains a shadow diagnostic, not the live rejection
  cause. This does not promise admission of every small or blurred sign frame.
- **Previews:** follow unique contiguous segments of the same directed way
  through side junctions, honoring access and restriction barriers. Cross-way
  traversal still needs the certified unbranched successor and common followed
  relation. Plain explicit OSM limits can supply a map-boundary preview with
  their own source snapshot and identity. Conditional/vehicle-specific tags
  stay withheld. The explicit 40 at town entry takes precedence over assuming
  that the town boundary means a numeric 50.
- **iPhone map state:** normalize filesystem aliases before comparing selected
  and enumerated map paths. `/var` and `/private/var` can identify the same file
  on a physical phone. Refresh the active reader on foreground when the saved
  selection changes, clearing in-flight work from the former map generation.
- **Automatic trip save:** recording must be enabled, the trip must have
  actually driven, and fresh accurate fixes must confirm 15 seconds at rest.
  Six decimal dials replace the ordinary zero-speed metric. Drag each digit up
  or down; the estimate adds measured distance since the last confirmed reading
  to that reading. Without a prior reading, the dials start at 000000 and are
  labelled as a car-odometer entry. Continue keeps the same trip and suppresses
  another prompt at that stop. Save atomically stores the ending reading and
  ends the trip; recording stays enabled and begins the next trip on movement.
  Movement, stale GPS, backgrounding or speed-capture mode hides the controls.
  Save rechecks the backend stop condition before accepting an entry.

## Verification

- Policy checker: 39 scenarios, 171 steps, all 16 transitions and five states;
  artifact hashes and both clients' pins match.
- Android JVM suite: 861 tests, zero failures, one skip. A separate scanner
  regression checks the complete native scan with vegetation and a panel.
- Physical Android: 25 regression tests pass, including recording/odometer,
  six-digit drag/Save/Continue, native preview reads and conditional-camera
  admission. Full dashboard checks pass in portrait and landscape, including
  immediate restoration of speed on movement. The controller turnaround test
  passes with producer-generation retirement and rejected old evidence reuse.
  Two other preview controller tests also pass.
- Physical iPhone: 69 selected tests, zero failures, three opt-in fixture skips;
  this includes turnaround publication, conditional-camera guards, the stop
  policy and persistent trip Save/Continue/rearm. Both additional selected-map
  regressions pass on the phone, including the filesystem-alias failure that
  initially reproduced the stale selection.
- A 303,104-byte extraction of the actual selected BW map supplies six native
  route cases on both phones: 60 at 200/550/700 m and 40 at 50/100/150 m. This
  tests the real source rows and native readers, not whole-map latency or an
  actual repeated drive.
- iPhone simulator UI: six native wheels, digit adjustment, Continue, Save,
  rearming and immediate restoration of speed on movement pass. Screenshot
  review verified the digits' contrast and the dashboard layout. The final
  native vegetation/panel scan regression also passes in the simulator.

The physical iPhone UI automation run requires the phone's XCTest passcode
confirmation. QuickTime screen inspection also requires the Mac to be unlocked.
Those hardware UI checks are pending; the native iPhone tests and simulator UI
test above completed successfully. No repeated road drive was performed.

Evidence remains outside Git in
`/private/tmp/youspeed-turnaround-fix-20261024/`: build/test logs, native route
results, isolated dashboard screenshots and `validation.json`. The original
drive evidence and its hash manifest remain in
`/private/tmp/youspeed-turnaround-20261024/`. No commit, push, merge or publication
was performed during this validation.
