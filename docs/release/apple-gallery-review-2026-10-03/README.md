# Apple gallery upload review — 3 October 2026

All 40 selected screenshots were decoded and visually reviewed: German, English, French and Dutch; ten images per locale. Every upload file is an opaque RGB PNG at 1320 × 2868. Source and output SHA-256 hashes match the retained native-capture provenance. [The upload manifest](../APPLE_SCREENSHOT_READINESS_2026-10-03.json) records the ordered absolute paths, dimensions, byte sizes and hashes.

Upload each locale's files from `store/apple/screenshots/<locale>/iphone-6.9/`, in this order:

1. `01-safe-speed.png`
2. `02-camera-speed-limit.png`
3. `03-secondary-sign.png`
4. `04-dashcam.png`
5. `05-reference-signs-DE.png`
6. `06-reference-signs-FR.png`
7. `07-reference-signs-CH.png`
8. `08-reference-signs-BE.png`
9. `09-reference-signs-NL.png`
10. `10-reference-penalties-NLD.png`

The four contact sheets in this folder are review aids, not upload assets. The selected galleries combine concise benefit headlines with retained native captures. Five reference images use the same catalog layout to show the five supported sign countries. At the user's request, the four Dashcam images now place a genuine recorded frame in the originally empty camera pane. The surrounding UI is preserved; this is a marketing composition rather than a live capture of that session. The frame and final crops contain no visible people or cars. [The composite validation](../dashcam-composites-2026-10-03/validation.json) records the source and pixel-preservation checks.

[Apple's current screenshot specification](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/) accepts this 6.9-inch size, up to ten images, without transparency. Apple uses scaled versions for smaller display groups when dedicated sets are not provided.

The existing English preview is `store/apple/previews/en-US/iphone-6.9/youspeed-app-preview.mp4`: 30 seconds, 1920 × 886, H.264 High Level 4.0, 30 fps, approximately 10.93 Mbps video, AAC stereo at 48 kHz, 41,955,856 bytes. The retained render report passed all format checks, and [Apple's preview specification](https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications/) still accepts those specifications. Its contact sheet was reviewed. It is a native app demonstration draft with example recognition results labelled as such; actual calibration, recording interactions and Gallery playback still need device footage for a fully filmed demonstration. There are no localized German, French or Dutch previews. See the preview README for capture limitations.

This review records local asset readiness. Remote upload and processing are recorded by the App Store Connect update work.
