# Manual screen orientation and dashcam controls

The Android and iPhone consumer apps share this behavior. The orientation is a
saved user choice, not a response to the device's orientation sensor.

## Mounting choices

| Saved value | Setting | Layout |
| --- | --- | --- |
| `portrait` | Portrait (default) | Existing top and bottom arrangement |
| `landscape_camera_lower_right` | Landscape — camera lower right | Existing top/sign area on the viewer's left; speed/location or dashcam workspace on the right |
| `landscape_camera_upper_left` | Landscape — camera upper left | The same left/right arrangement |

The landscape labels describe the physical camera mounting position. Map these
labels independently on each platform; native orientation names do not express
the camera corner. Physical-device feedback confirmed the Android choices and
identified the reversed iPhone choices, which are corrected by this mapping:

| Mount | iPhone interface / capture angle | Android requested orientation / CameraX target |
| --- | --- | --- |
| Camera lower right | `landscapeLeft` / 180° | `REVERSE_LANDSCAPE` / `ROTATION_270` |
| Camera upper left | `landscapeRight` / 0° | `LANDSCAPE` / `ROTATION_90` |

Preview, photos, video and recognition frames use the corresponding platform
mapping together. The saved values and user-facing labels remain stable.

Text and controls are upright for the selected mounting position. Changing
between the two landscape settings changes the physical display orientation by
180 degrees without exchanging the content panes. Turning the phone without
changing the setting does not change the selected orientation.

The choice persists across app launches and applies to settings and galleries
as well as the driving screen. Controls respect side cutouts and system bars.
Unknown saved values fall back to portrait.

## Dashcam action ordering

Any enabled in-app button pressed while dashcam video is active first requests
that the video stop. Its action runs only after the recorder confirms successful
file finalization. The gate affects dashcam video; it does not itself stop photo
capture or traffic-sign recognition.

1. Accept the first action and request dashcam stop.
2. Ignore or disable subsequent button actions while finalization is pending.
3. On successful finalization, execute the accepted action once.
4. On finalization failure, discard the pending action and display the error.

A missing finalization callback times out as a failure. Leaving the foreground
cancels the pending action; a late recorder callback must not navigate or change
the mounting mode when the user returns.

The dashcam button captures its original stop intent: stopping a video cannot
turn into starting another one after the gate opens. Recording starts again only
through an explicit user action. Actions whose own purpose is to stop the entire
drive session still stop its other modules.

Orientation changes follow the same ordering. Preview, photo capture and sign
recognition use the selected camera orientation, including a 180-degree change
between landscapes. A frame or annotation from the previous orientation must
not be attached using the new coordinate system. New videos use the selected
orientation from their start.

## Verification checklist

- Select each mode and relaunch: verify persistence, pane order and readable text.
- Change directly between the two landscape modes: verify display and capture
  orientation even though the view's width and height do not change.
- On small phones, inspect the sign, long street/place names, all recorder
  controls, settings and galleries with side cutouts and system bars.
- While dashcam recording, press each reachable button: verify a finalized,
  playable video before navigation or state mutation and no automatic restart.
- Press multiple buttons during finalization: verify only the first action runs.
- Exercise recording startup, stop, failure and background transitions: pending
  actions must not be released by stale callbacks from another recording.
- Stop dashcam through an unrelated button while photos and recognition are
  enabled: verify both continue unless the requested action stops the session.
- In each mounting mode, inspect real preview, JPEG orientation, sign detection,
  annotation coordinates and video playback. Simulator/unit checks cannot
  establish physical camera behavior.

Automated coverage lives in iPhone's `SpeedConsumerTests` and
`ScreenOrientationUITests`, and Android's `ManualOrientationTests`,
`DashcamButtonActionGateTests`, `ManualOrientationInstrumentedTest`,
`ManualOrientationLayoutInstrumentedTest`, `PanoramaxMetadataInstrumentedTest`
and `DriveRecorderInstrumentedTest`.

Implementation validation (14 September 2026): Android passed 291 unit tests,
13 emulator layout/controller/metadata tests, and the live CameraX button test,
plus the debug build and lint (no errors). iPhone passed 12 focused unit tests
and both UI flows on an iPhone 16e simulator, including changing mounts with
Settings open. Both landscape layouts were inspected visually. The builds were
subsequently installed and launched on the attached iPhone 14 Pro and Moto g86
5G. The user confirmed Android mounting choices and reported the reversed iPhone
choices addressed above. Real-device capture output checks remain part of
hardware validation.
