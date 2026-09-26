# iPhone road-camera focus regression

## Recording comparison

The two supplied MOV files were inspected locally; no video or extracted frames
are committed. Recording times below come from the embedded QuickTime creation
date, converted to CEST. Filesystem creation times correspond to recording end.

| Clip prefix | Recording start | File creation | Format | Sampled detail |
| --- | --- | --- | --- | --- |
| `drive-BBDD6A3D` | 2026-09-14 12:01:57 | 2026-09-14 12:04:31 | HEVC, 3840×2160, ~30 fps | Sharp road signs, building edges and foliage |
| `drive-A5086473` | 2026-09-26 15:30:13 | 2026-09-26 15:38:37 | HEVC, 3840×2160, ~30 fps | Broad defocus across nearby and distant road detail |

Frames near the beginning, middle and end show the difference. The routes and
camera mounting angles differ, so this is not a controlled optical comparison.
The timestamps locate relevant source changes but do not prove which app binary
produced either recording.

## Source change and correction

Commit `3a37fce41c8203391870a3d34c1e0c4059d92e60` (20 September) added
`setFocusModeLocked(lensPosition: 1.0)` to the shared iPhone capture session.
Before that change the app did not override camera focus. The other changes to
`PanoramaxRecorder.swift` between the recording dates adjusted output allocation
and capture lifecycle; they retained the same physical rear wide-angle camera
and 4K/high-preset selection.

Apple explicitly documents that [`lensPosition`](https://developer.apple.com/documentation/avfoundation/avcapturedevice/lensposition)
is device-dependent and that `1.0` is not infinity focus. Locking this value
prevents the camera from correcting defocus. This is a concrete API misuse and
the likely explanation for the regression.

The iPhone now uses continuous autofocus with a centered focus point and a
[`far` range restriction](https://developer.apple.com/documentation/avfoundation/avcapturedevice/autofocusrangerestriction-swift.property)
where supported, reducing the chance of selecting windscreen dirt or reflections.
Face-driven autofocus is disabled. Preferences are set before the focus mode so
the initial focus scan uses them. Cameras without continuous autofocus fall back
to a single autofocus acquisition; fixed-focus hardware is left untouched.
The configuration is reapplied whenever the capture graph is rebuilt and is
shared by Dashcam, Panoramax photos, preview and traffic-sign recognition.

Android was checked for parity. Its existing `LENS_FOCUS_DISTANCE = 0.0f` uses
[Camera2's documented infinity distance](https://developer.android.com/reference/android/hardware/camera2/CaptureRequest#LENS_FOCUS_DISTANCE).
iOS has no equivalent calibrated infinity-distance setter, so it uses far-range
autofocus to achieve the same road-focused capture intent. Android is unchanged.

## Validation

Regression tests cover recovery from locked focus, setting preferences before
focus acquisition, cameras without range/point controls, single-autofocus and
fixed-focus fallbacks, and configuration-lock failure.

- Five new focus tests and five existing capture/control regression tests passed
  on the iPhone 17 Pro simulator (iOS 26.4).
- The Debug build for a generic physical iPhone passed with signing disabled.
- `git diff --check` passed.

Validation used an isolated checkout of `99d62f2` plus the two camera code/test
changes. The working repository's first build was blocked by an unrelated
in-progress Xcode reference to a missing `SpeedLimitReferenceView.swift` file;
that work was not altered. No build was installed on the attached phone.
Optical sharpness still requires a fresh recording on a physical iPhone after
installation.
