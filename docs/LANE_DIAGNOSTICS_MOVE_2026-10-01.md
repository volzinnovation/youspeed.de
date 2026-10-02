# Lane option and dashcam regression check — build 10029

Both clients now place the existing lane-display switch at the end of
Diagnostics. General Settings no longer contains it. The one-time shared
preference marker `youspeed.drive_recorder.lane_diagnostics_opt_in_v1` resets
an existing installation to lanes disabled; a later explicit opt-in persists.
The move does not change dashcam recording controls or saved-video output.

## Verification

- Android: all 586 unit tests passed. Signed Debug build 10029 installed on the
  attached Moto g86. UIAutomator inspected the real Diagnostics bottom and
  confirmed `show-detected-lanes-toggle` unchecked. Stored preference is false
  and migration marker true.
- iPhone: build 10029 signed and installed on the attached iPhone 14 Pro.
  Its copied preferences independently confirm lanes false and migration true.
  `testLaneOptionIsOffAtBottomOfDiagnostics` passed on the iPhone 16e simulator:
  no lane switch while scrolling General Settings, switch reachable at the end
  of Diagnostics, value zero, original screenshot attached to XCTest.
- Android real-camera regression: 30.196-second lanes-off run passed;
  finalized movie 37.615 seconds, 25 sampled TSR inference events, zero lane
  frames, all 28 preview visibility samples passed, zero thermal pause time,
  preferences restored and owner media preserved. The sunset-drive movie's
  SHA-256 remained unchanged. Peak sampled RSS was 1,022,210,048 bytes; this
  short test does not prove sustained memory stability.
- iPhone: the 30-second harness test **skipped**, because normal startup resumed
  a dashcam recording from the driver's stored enabled preference. It is not a
  passing soak result. That normal recording was copied and independently
  decoded using AVFoundation: 26,401,746 bytes, 7.3667 seconds, 3840×2160 at
  30 fps, decodable frame at 4.6667 seconds. Console records dashcam-active
  preparing→recording transitions; persisted lanes preference is false.
  This proves short normal recording still works with lanes disabled, not a
  30-second or sustained iPhone result. The phone subsequently locked.

Evidence is outside the repository at
`/Users/raphaelvolz/YouSpeedDeviceBackups/2026-10-01/` and
`/private/tmp/youspeed-10029-verification/`. Copied logs and movies enter the
private Hugging Face evidence backup before local deletion.

The experimental lane presentation policies remain opt-in as documented in
the earlier evaluation. No Swiss penalty behavior or shared speed-reference
policy was changed by this lane option move.
