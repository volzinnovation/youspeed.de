# YouSpeed feature videos — production notes

## Deliverables

- Feature film: 76 seconds, English, 1920 × 1080, 30 fps, captioned, original quiet ambient instrumental.
- iPhone App Store format preview draft: English, 1920 × 886 landscape, 30 seconds, H.264 High Profile Level 4.0, progressive yuv420p, measured 10.927 Mbps; AAC stereo, target 256 kbps, 48 kHz, MP4 with fast-start metadata. Intended for the modern iPhone preview size well.

The companion film includes the supplied real-world mounted-phone photographs. Those photographs show Android, and are excluded from the iPhone preview. The preview uses native iPhone app captures, showing mounting choices, recorder configuration, picture cadence, and example traffic-sign results. It has no filmed device, external browser, price, or download call-to-action. Apple makes the final content-review decision.

## What is actually demonstrated

Current native app settings and navigation are captured from build 10031 / version 1.3 in an isolated iPhone simulator. Native gallery media was prepared solely for filming: the restored real iPhone Dashcam excerpt, two stills from that excerpt, and the requested public Panoramax photograph. The Mac became locked before Gallery interactions could be captured. The feature film instead presents real saved footage and the Panoramax scene with precise Gallery instructions; it does not invent a Gallery interface. No media was captured by a simulator camera.

The camera-limit and additional-sign screens are genuine captures of the app's existing native screenshot fixtures. They show example result layouts, not live model inference, and are captioned accordingly. The physical iPhone was unavailable. Live camera calibration could not be filmed; the film explains the actual viewfinder, horizon/lane-guide, and Save workflow using the app's dashboard. There are no generated app screens, invented signs, or synthesized road scenes.

Panoramax upload is explicit after the drive and requires a connected account. No upload, App Store submission, deployment, or publication is performed by this task.

## Empty-road selection

- The restored 30.368-second source contains a parked trailer during its middle portion, which is excluded.
- Allowed excerpts are source 0.5–7.5 seconds and 25.0–30.0 seconds, rendered upright at 1920 × 1080 / 30 fps. Reviewed contact sheets and full-resolution spot frames show no other cars or people.
- First requested Panoramax scene 976ae770-f064-405d-8c8b-58e8629f80c8 passes full-frame visual review; second requested scene 33af490e-ea24-4a12-99af-2f375a248ee5 is excluded because it contains cars.
- The two user photographs are tightly cropped after honoring EXIF orientation, eliminating background vehicles. Motion stays inside those approved crops.

## Sources and credits

Real iPhone Dashcam source: private Hugging Face dataset loffenauer/youspeed.de, revision bd12056313e00acc790d25ebe5486aac11f4cf79; remote object device-backups/2026-10-01/objects/f622d4746220f98b9ac66b8a323e51d0c2dcb44a3b51068b4e842fcf99577402.mov. Restored source SHA-256 f622d4746220f98b9ac66b8a323e51d0c2dcb44a3b51068b4e842fcf99577402. Raw restored evidence is outside the repository.

Panoramax imagery: admin / panoramax.woladen.de, CC BY-SA 4.0. The selected image is cropped, scaled, and gently animated in the feature film. Attribution is visible in the relevant scenes. Adapted Panoramax imagery remains under CC BY-SA 4.0. The source and license references accompany the video; no blanket license is asserted over independently supplied app UI, photographs, or Dashcam footage. The iPhone preview contains no standalone Panoramax image.

- Source photo: https://panoramax.woladen.de/?focus=pic&pic=976ae770-f064-405d-8c8b-58e8629f80c8&seq=7bd211ad-ebe3-4013-a5d8-f2c5d396aa20
- Source metadata: https://panoramax.woladen.de/api/collections/7bd211ad-ebe3-4013-a5d8-f2c5d396aa20/items/976ae770-f064-405d-8c8b-58e8629f80c8
- License: https://creativecommons.org/licenses/by-sa/4.0/

The music is an original synthesized ambient composition created for these videos, without third-party samples or recordings.

## Apple references checked

- https://developer.apple.com/help/app-store-connect/manage-app-information/upload-app-previews-and-screenshots
- https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications
- https://developer.apple.com/app-store/app-previews/
- https://developer.apple.com/app-store/review/guidelines/#accurate-metadata

## Local sources

Work files, source hashes, image review, native media seed, intermediate renders and renderer are preserved under /Users/raphaelvolz/YouSpeedVideoWork/2026-10-02/. The final video timeline and export report record inputs and encoding checks.

## Validation

Both final MP4s passed a full audio/video decode. The feature film is 76.000 seconds and 69,254,920 bytes. The preview is 30.000 seconds, 900 frames, and 41,955,856 bytes; its encoding, dimensions, frame rate, duration, file size, and fast-start structure passed the recorded Apple-format checks. Final contact sheets and full-resolution posters were visually reviewed for orientation, caption readability, and the empty-road selection. Content approval is subject to Apple's review.
