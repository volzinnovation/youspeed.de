# Fahrtenbuch simple table and desk controls — build 10062

The owner rejected the surrounding charts, counters, filters and controls in
build 10061. Both apps now open Fahrtenbuch directly to the requested table on
a white background with an X close button. The five columns are date/time,
start location, end location, distance in kilometres to one localized decimal,
and ending car odometer. Long cells wrap; narrow screens can scroll horizontally.
Share and Delete are per-row actions. Selecting a row opens only the compact
ending-odometer field, Save, validation and X. Existing ending readings remain
write-once. Sharing retains the GPS track and GPS/TSR logs.

There are no charts, counters, totals, filters, search, help, Details links,
new-trip controls or data-management buttons in this history/odometer flow.
Recording preferences stay in normal Settings; backup, restore and clear-all
are in a collapsed inline data-management disclosure there.

Face-up posture within 10° of horizontal now keeps dashboard buttons, Settings
and submenus available at every reported speed, including GPS drift on a desk.
Settings is not replaced by the driving shutter in that posture. Away from flat
posture, existing below-4-km/h or no-GPS navigation behavior applies. Native
permission/review standstill checks and dashcam finalization remain in force.

Source priority remains own corrections > camera visual evidence > government
data (MobiData only in Baden-Württemberg) > OSM bundle. This correction changes
no map bundle, journal schema, storage representation or protected reference
policy. It retains the preview-sign and inner/outer-city implementation already
in build 10061.

## Verification

The [combined receipt](FAHRTENBUCH_SIMPLE_UI_2026-10-23.validation.json) links the
focused test and physical installation evidence.

All **32 focused checks passed**: 14 iPhone control/posture tests, three iPhone
UI flows, 10 Android posture/photo policy tests, and five Android emulator flows.
The UI checks cover the opening viewport, absence of clutter, five table columns,
multiline names, compact odometer save/X and write-once behavior, independent
Share/Delete, GPS/TSR ZIP contents and inline Settings. Android also exercises
Settings remaining open at high fixture speed while flat, then closing when
non-flat. Fixture speeds are confined to isolated test apps; no OS GPS position
was injected into either driver's app. Entire opening screens and compact
prompts were visually reviewed on both platforms.

- [iPhone UI and posture receipt](../output/fahrtenbuch-simple-2026-10-23/iphone/validation.json)
- [iPhone entire opening screen](../output/fahrtenbuch-simple-2026-10-23/iphone/initial-screen.png)
- [iPhone final columns/actions](../output/fahrtenbuch-simple-2026-10-23/iphone/table-last-columns.png)
- [iPhone compact odometer prompt](../output/fahrtenbuch-simple-2026-10-23/iphone/odometer.png)
- [Android UI and posture receipt](../output/fahrtenbuch-simple-2026-10-23/android/validation.json)
- [Android entire opening screen](../output/fahrtenbuch-simple-2026-10-23/android/initial-full-screen.png)
- [Android final columns/actions](../output/fahrtenbuch-simple-2026-10-23/android/history-right.png)
- [Android compact odometer prompt](../output/fahrtenbuch-simple-2026-10-23/android/odometer.png)

## Attached phones

Both normal driver apps were updated in place to **1.5/build 10062**, using
frozen signed artifacts. No app was uninstalled and no data was cleared.

On iPhone, signature and installed-version verification passed. Fresh before/after
preferences and active-map metadata are identical, and all 215 inventoried
Application Support files retain their names and sizes. This is a metadata
comparison, not a full media hash readback. After the owner unlocked the phone
and Mac, normal launch and running-process verification passed. QuickTime showed
the actual dashboard at 0 km/h, with Fahrten immediately left of Settings.
QuickTime recording was not started. The new table and prompt interactions are
verified on the simulator; QuickTime provides screen viewing rather than phone
touch control.

Android launched build 10062, and the actual phone showed the simple white table,
X and brief empty state. Its installed APK hash matches the frozen artifact.
Preferences, original install time and UID, active-map metadata, all 1,036 photo
metadata entries and three recording metadata entries are retained. Recording
consent remains off and the journal contains zero trips. Existing startup
maintenance removed 26 empty Panoramax queue metadata files (13 batch/journal
pairs), with no media removed.

- [iPhone installation/preservation receipt](../output/v1.5-device-10062-2026-10-23/iphone/validation.json)
- [iPhone actual dashboard](../output/v1.5-device-10062-2026-10-23/iphone/dashboard-quicktime.png)
- [Android installation/preservation receipt](../output/v1.5-device-10062-2026-10-23/android/validation.json)
- [Android actual phone table](../output/v1.5-device-10062-2026-10-23/android/history-initial.png)

Existing lookahead maps remain installed. No recording preference was enabled,
share was sent, or real drive performed during this correction. Earlier broad
storage/export/road checks remain in the historical build 10061 and v1.5 records;
this focused run verifies the UI and desk-control changes.
