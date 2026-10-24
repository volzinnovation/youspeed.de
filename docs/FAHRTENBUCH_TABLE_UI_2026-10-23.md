# Fahrtenbuch table and normal Settings revision

Historical build 10061 record. Its surrounding charts, counters, filters and
detail controls were rejected by the owner. The current implementation follows
[the simple-table build 10062 revision](FAHRTENBUCH_SIMPLE_UI_2026-10-23.md), which
supersedes this screen composition and its desk-use navigation rules. The receipts
below remain evidence of build 10061, not the corrected UI.

The owner's 23 October 2026 revision moves automatic trip saving and its
disclosure into the existing Settings screen. Fahrten remains immediately left
of Settings on the dashboard. Opening history does not automatically request
recording consent.

The trip list has five aligned data columns:

| Date and time | Start location | End location | Distance (km) | Car ending odometer (km) |
| --- | --- | --- | --- | --- |
| Multiline local date/time | Available offline location name | Available offline location name | One decimal, localized separator | Optional reading, plus row share/delete actions |

Cells wrap; narrow screens can scroll horizontally. Selecting a trip opens its
optional ending-odometer dialog. A missing reading may be saved once, including
for a closed trip. Existing values cannot be overwritten. Entry must be finite,
nonnegative and no lower than the starting reading. This changes neither
measured distance nor timestamps, trip state or aggregate counters. Details
remain accessible for map, replay, media and export.

The Fahrtenbuch and odometer dialogs use white backgrounds and explicit X close
controls. Sharing opens native sharing for the selected trip's GPS track and
GPS/TSR logs. Original media is not included automatically; the existing detailed
export controls retain optional odometer disclosure. Deleting a trip retains its
existing confirmation and lifetime-counter preservation behavior.

Fresh stable offline matcher context supplies private street/locality evidence
at the original GPS timestamp. Endpoint names are read-only projections tied to
nearby valid endpoint fixes, limited by time, distance and coverage gaps. An
unavailable name is shown explicitly. Place evidence is excluded from masked
sharing, and no online geocoder or new database schema is introduced.

The source-priority order and inner/outer-city rules are unchanged by this UI
revision. Data-structure optimization remains separate work.

## Validation and test builds

The [combined validation receipt](FAHRTENBUCH_TABLE_UI_2026-10-23.validation.json)
records the final implementation and both installed builds.

iPhone's final isolated simulator run passed **21 journal unit tests and three
UI tests**, with zero failures. It exercises normal Settings, the five columns,
German decimal input, write-once end readings, X close, retained detail access,
delete cancellation and native sharing without sending. Export regressions
verify that GPS/TSR remain included while optional odometer fields and entry
events remain excluded by default. Endpoint tests cover equal-time evidence and
reject names borrowed across a coverage boundary.

The attached iPhone was updated in place to **1.5/build 10061**. The normal signed
application contains no XCTest plug-in; signature verification and launch passed,
and its normal process remained running. Fresh pre/post-install preferences and
active-map metadata were identical; all 211 inventoried existing Application
Support files remained present. Five log/SQLite-WAL files changed size during
shutdown. This is a fresh filename/size check, not a full media hash readback.
After the owner reconnected the iPhone, QuickTime showed its actual dashboard at
0 km/h with Fahrten immediately left of Settings. The new journal/odometer
interactions were verified on the simulator; no physical iPhone controls or
recording preferences were changed for this visual check.

- [iPhone simulator receipt](../output/fahrtenbuch-ui-2026-10-23/iphone/validation.json)
- [iPhone history screenshot](../output/fahrtenbuch-ui-2026-10-23/iphone/history.png)
- [iPhone odometer screenshot](../output/fahrtenbuch-ui-2026-10-23/iphone/end-odometer.png)
- [iPhone build 10061 installation receipt](../output/v1.5-device-10061-2026-10-23/iphone/validation.json)
- [Connected iPhone dashboard](../output/v1.5-device-10061-2026-10-23/iphone/dashboard-quicktime-connected.png)

Android's final isolated emulator batch passed **24 tests**, including storage,
recovery, endpoint naming, optional saved-trip ending readings, inline Settings,
white/X dialogs, multiline cells, independent Share/Delete, native ZIP contents
and retained route detail. Its full JVM suite passed **847 tests**, with one
archive-dependent fixture skipped and no failures. Screenshots were visually
inspected on both platforms.

The normal Android **1.5-debug/build 10061** APK is ready and verified:
626,937,473 bytes, SHA-256
`4e7b6d911e8c26c69af9f8072d04d86731a7658983329fa9e4f00a3ebc4ef7eb`.
After the owner reconnected and unlocked the Android phone, it was updated in
place to build 10061 and launched. The installed APK hash matches the frozen
artifact. Its UID, original install date, complete preference-file hashes,
recording consent and active-map metadata were retained; the full map hash was
also rechecked. Metadata for all 1,036 original photos and three recordings was
identical before/after the update.

On the physical Android phone, normal Settings showed the inline recording
option still off, its disclosure and history link. The history UI hierarchy
contained the empty state, X close and all five table headers. A live GPS safety
gate returned to Settings before a history screenshot could be taken; that
image is labelled accordingly. White journal/odometer appearance and per-trip
interactions are established by the emulator evidence above. The phone was left
on its normal dashboard without changing mounting or recording selections.

The full file inventory additionally records 74 removed Panoramax queue metadata
files, forming 37 batch JSON/journal pairs. The existing startup maintenance
prunes empty batch records and their journals only after checking that the
batch is not capturing, has no items or incomplete remote upload, and has no
remaining assets. No photo or recording was removed. This maintenance is
separate from the requested UI changes; no queue records were restored or
manually deleted.

- [Android emulator history, left](../output/fahrtenbuch-table-2026-10-23/android/history-left.png)
- [Android emulator history, right](../output/fahrtenbuch-table-2026-10-23/android/history-right.png)
- [Android odometer dialog](../output/fahrtenbuch-table-2026-10-23/android/odometer.png)
- [Normal Android build 10061 APK](../output/v1.5-device-10061-2026-10-23/android/YouSpeed-1.5-10061-debug.apk)
- [Android native-test receipt](../output/fahrtenbuch-table-2026-10-23/android/validation.json)
- [Android build 10061 installation receipt](../output/v1.5-device-10061-2026-10-23/android/validation.json)

Both phones retain their existing lookahead map; no replacement bundle was
transferred. No recording preference was enabled, no GPS position was injected,
and no native share was sent. No store release, backend publication, protected
speed-reference policy change or data-structure optimization was performed.

Build 10060's prior installation remains documented in
[its original record](V1_5_DEVICE_INSTALL_10060_2026-10-23.md).
