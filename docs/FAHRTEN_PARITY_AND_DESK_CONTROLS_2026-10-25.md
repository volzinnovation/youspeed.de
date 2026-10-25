# Fahrten parity and flat-phone controls — build 10071

Both attached phones received version 1.5, build 10071, as an in-place update.
Existing app containers were retained. Device validation used separate test apps
and synthetic trips; the driver's private trip history was not copied.

## Changes

- Share precedes date/time; Delete follows the odometer. Both actions align with
  the top of the row text. German headings are `Distanz (km)` and `Auto (km)`.
- Android fits all five columns and both actions within the viewport. Long place
  names wrap vertically; history no longer needs horizontal scrolling.
- Android opens Delete confirmation before checking linked media. Export work
  shows progress, errors are visible, and repeated actions are blocked while busy.
- Both clients resolve endpoint names after the five-second finalizer. Metadata
  version 2 repairs missing version-1 names once from saved local evidence while
  preserving existing names, distances, timestamps and counters.
- Valid Android gravity vectors remain usable when the Moto sensor reports
  accuracy status zero. Raw accelerometer fallback checks remain in place.
- Pausing motion intake retains confirmed posture on both platforms, preserving
  open Settings and nested trip history through system-sheet interruptions.
  The next live reading reapplies the existing posture gate.

See [trip journal behavior](../shared/trip-journal/README.md) and
[posture rules](MANUAL_ORIENTATION.md#phone-posture-and-controls).

## Validation

| Scope | Result |
| --- | --- |
| Android posture, motion and photo policy JVM tests | 17 passed |
| Moto g86 isolated journal/storage/actions suite, build 10070 | 11 passed |
| Moto g86 final live posture, Settings/nested history, table and native Share checks, build 10071 | 5 passed |
| Attached iPhone journal unit tests and two journal UI flows, build 10068 | 29 unit tests and 2 UI tests passed |
| Attached iPhone final posture/state tests, including live gravity and synthetic speeds through 180 km/h | 16 passed |
| iPhone simulator Settings/nested history at 180 km/h, including background/return | 1 UI test passed |

The final physical iPhone UI flow could not start: XCTest timed out while enabling
automation mode. A retry after the user confirmed the phone was unlocked and
awake produced the same infrastructure error; CoreDevice also reported that no
passcode was required. No assertions from that UI flow ran on the physical phone.
The normal installed app was reopened after testing.

Both normal builds succeeded. The iPhone app signature and installed build
metadata were verified; Android installed build metadata and running process
were verified. The protected speed-limit reference policy was unchanged.
