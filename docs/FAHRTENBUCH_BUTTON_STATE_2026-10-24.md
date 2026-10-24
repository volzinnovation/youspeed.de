# Fahrtenbuch button recording state — build 10065

Both apps show a diagonal strike-through on the Fahrtenbuch button when saved
trip recording is off, and remove it when recording is on. Each app reuses its
existing Panoramax slash geometry, stroke and foreground color. The button
remains second from the right, immediately left of Settings, and opens history
in either state. It does not change recording consent when tapped.

The indicator follows the persisted recording choice. iPhone observes the
existing UserDefaults key through AppStorage. Android observes the existing
SharedPreferences choice while the dashboard is composed and unregisters its
listener when it leaves composition. Accessibility announces the current state.
No recording defaults, journal schema, map or source-priority behavior changed.

## Verification

- iPhone simulator: the existing history/Settings UI check passes with actual
  Settings switch changes off → on → off. Off still opens the simple table and
  normal Settings. Off/on screenshots were visually inspected.
- Android API 36 emulator: the existing history/Settings UI check passes with
  live off → on → off preference changes. Both button-row screenshots were
  visually inspected, and navigation remains available while recording is off.
- Both normal version 1.5/build 10065 apps build successfully. iPhone signing
  verifies. Build 10065 is installed and launched on the physical iPhone;
  QuickTime confirms the crossed-out button immediately left of Settings with
  recording off. All saved preferences and active conditional-map metadata
  match the pre-install values. Android build 10065 is installed on the Moto g86
  5G; the installed APK hash matches the tested package, and the conditional map
  remains active. The physical Android button check awaits unlocking the phone.
- No physical-phone recording preference was changed, and no physical GPS/TSR
  contents were read or exported for this UI change.

[Build and deployment record](../output/fahrtenbuch-button-10065-2026-10-24/builds.json)

The separately recorded iPhone startup-log retention discrepancy remains open
in [the build 10064 record](V1_5_BUILD_10064_2026-10-24.md).
