# 1.4 feature gallery upload order

Use the same six-image story for every Play listing locale:

1. `01-camera-recognition.png` — traffic-sign display, moving at 27 km/h.
2. `02-live-assistance.png` — additional sign and live speed assistance, 27 km/h.
3. `03-fine-calculation.png` — the app's live French monetary-fine example at 52 km/h.
4. `04-dashcam.png` — local recording, with the existing genuine road-frame composition.
5. `05-panoramax-upload.png` — photo selection and the Panoramax upload control.
6. `06-reference-signs-DE.png` — supporting offline sign catalog, last.

Sources are in `listing/<locale>/phone-screenshots/`; Fastlane mirrors are byte-identical. All nine locales use this order. Do not place the reference catalog before the driving/upload features.

The asset library can add screenshots in a different order from the file picker. After adding them, explicitly arrange and verify the six thumbnails against the numbered list before saving/submitting. The original unsaved browser edit must not be treated as the completed ordered gallery.

The Panoramax source is a retained native English demonstration screen with a selected synthetic test thumbnail. It shows the upload control, not a completed upload. Upload is disabled in the Android example because no account is connected. No account credentials or successful network upload are staged for this screenshot.

On 18 October, the native Chrome controller timed out while trying to manage the listing. The final controller check reported the Mac is locked and requires manual unlock. The revised Play assets are prepared locally; remote upload/order is not confirmed. The GitHub alpha APK publication is independent of this listing task.
