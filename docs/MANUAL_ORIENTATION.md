# Manual screen orientation and dashcam controls

On Android and iPhone, orientation is a saved user choice, not a response to the
device's orientation sensor.

## Mounting choices

| Saved value | Setting | iPhone / Android layout |
| --- | --- | --- |
| `portrait` | Portrait (default) | Centered speed-limit sign above the full-width speed/fine and city or dashcam workspace |
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

## Portrait layout

iPhone portrait restores the original vertical arrangement shown on youspeed.de:
the large speed-limit sign is centered above the speed/fine and city display.
Dashcam preview replaces that lower display. The action row, including the
debug/local-recordings button, spans the full width at the bottom. In landscape,
the sign stays on the left and the workspace and its action row stay on the right.
Both the telemetry and preview frames reserve space for the bottom action row
and the recorder status strip, so their content cannot extend into those controls.

The portrait layout restoration keeps both clients aligned: the speed-limit
pane uses the full display width above the workspace, with the camera eye
centered around the sign and its tips inset from both display edges.

All full-screen sheets share a 48 dp close button to the left of the title.
The dialog window follows the current display size, including rotation while a
sheet stays open. Sheet borders and content stay inside system bars, cutouts and
the on-screen keyboard; long content scrolls beneath the fixed header.

Gallery actions and local-recording actions wrap onto additional rows when
space is limited. Their labels remain readable with enlarged system text.
Dashboard controls have 48 dp targets. In portrait, the recorder, gallery, local
recordings, legal notices and settings controls share the bottom row. Android's
dashboard omits the GPS marker and accuracy readout, matching iPhone; GPS data
remains available in diagnostics. Startup messages scroll so that Retry remains
reachable on a narrow portrait screen, including long failure messages.

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

Android portrait regression coverage also includes
`SheetBoundsInstrumentedTest` and `PortraitContentLayoutInstrumentedTest`.
These check unclipped bounds, close-button placement, both landscape-to-portrait
transitions with Settings open, the real keyboard, gallery and recording
actions, long startup errors, and all five onboarding steps. Narrow-screen
coverage includes 320/360 dp widths and text enlarged to 150%.

iPhone layout restoration validation (14 September 2026): the Debug build and
both orientation UI tests passed on iPhone 16e (iOS 18.6). The dashboard test
checks all three mounts with telemetry and with the recorder strip and dashcam
preview, then switches each preview back to speed and city. It checks content
clearance above the bottom controls and between the preview and recorder strip.
`YOUSPEED_SCREENSHOT_DASHCAM=1`, together with an existing screenshot state,
uses an idle camera session and simulated recording state; these checks validate
layout, not physical camera capture. Portrait fine/city and portrait/landscape
preview screenshots were also inspected.

Implementation validation (14 September 2026): Android passed 291 unit tests,
13 emulator layout/controller/metadata tests, and the live CameraX button test,
plus the debug build and lint (no errors). iPhone passed 12 focused unit tests
and both UI flows on an iPhone 16e simulator, including changing mounts with
Settings open. Both landscape layouts were inspected visually. The builds were
subsequently installed and launched on the attached iPhone 14 Pro and Moto g86
5G. The user confirmed Android mounting choices and reported the reversed iPhone
choices addressed above. Real-device capture output checks remain part of
hardware validation.
