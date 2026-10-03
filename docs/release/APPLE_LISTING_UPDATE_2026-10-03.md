# Apple listing update — 3 October 2026

App Store Connect's iOS 1.3 draft now contains the refreshed German, English, French and Dutch listing text, all 40 selected screenshots, and the new English 30-second preview. Build **10032** remains selected. No review submission or publication was performed.

## Why the name changed

Yesterday's listing optimization, commit `ee4c19f2` (`Refresh localized store listings and screenshot artwork with source provenance`), changed the draft listing names as part of the marketing update. This was a metadata change made during release preparation. The public App Store listing still displayed **YouSpeed.de** when checked today.

Today's saved draft names preserve the requested domain identity. Each was verified after revisiting its locale:

| Locale | App name | Subtitle |
| --- | --- | --- |
| German (`de-DE`) | Youspeed.de | Tempolimits & Dashcam |
| English (`en-US`) | Youspeed.de: Driver Assistance | Speed limits & dashcam |
| French (`fr-FR`) | Youspeed.de | Limites de vitesse et dashcam |
| Dutch (`nl-NL`) | Youspeed.de | Snelheidslimieten en dashcam |

The English name occupies Apple's 30-character limit; the other names contain 11 characters. The subtitles match the respective local metadata files.

## Saved text and uploaded media

All **16 version-text fields**—description, promotional text, release notes and keywords in each of the four locales—matched the local source exactly when initially saved and revisited. The revised descriptions use direct, human-readable language about speed limits, traffic-sign recognition, alerts and recording. Subsequent human UI edits to listing text were observed during the Dashcam work and preserved. The earlier exact-match evidence is a snapshot, not a claim that later human edits still match the local files.

All **40 screenshots** were uploaded to the 6.9-inch display group, ten per locale, in filename order **01–10**. The upload images are opaque RGB PNGs at **1320 × 2868**; their native-source and output hashes were verified locally. [The screenshot manifest](APPLE_SCREENSHOT_READINESS_2026-10-03.json) records the ordered files and checksums, and [the contact sheets](apple-gallery-review-2026-10-03/README.md) document visual review.

The old German 6.5-inch screenshots and old preview were removed. The 6.5-inch group in every locale now inherits that locale's refreshed 6.9-inch media. The new English preview, `store/apple/previews/en-US/iphone-6.9/youspeed-app-preview.mp4`, was uploaded. Its local format checks passed: 30 seconds, 1920 × 886, H.264/AAC. It remains an English native-app demonstration with recognition examples labelled as examples; the [preview README](../../store/apple/previews/en-US/iphone-6.9/README.md) records its capture limitations.

Remote verification JSON and screenshots for this update belong in `docs/release/apple-listing-update-2026-10-03/`. This report records the completed draft changes independently of yesterday's submission-preparation reports.

## Corrected Dashcam images uploaded

The black camera pane was replaced locally in all **13 localized Dashcam layouts**: four Apple portrait images and nine Android landscape images, plus nine matching Fastlane upload copies. The frame comes from 5.5 seconds of a verified genuine iPhone recording. A crop excludes the recording car's mirror and dashboard; the frame and final views contain no visible people or cars. The raw native screenshots remain unchanged. [Composite validation](dashcam-composites-2026-10-03/validation.json) passed for all 13 layouts against 314 baseline image hashes, with zero changed pixels outside the mapped camera pane and zero changed native UI/caption pixels. [Package validation](dashcam-composites-2026-10-03/store-package-validation.json) passed without errors. The contact sheets and local Apple manifest now reflect these corrected files.

The **four corrected Apple Dashcam replacements are now uploaded**, in German, English, French and Dutch. During the earlier work the version moved to **Ready for Review**, locking media editing. The user then explicitly authorized uploading and replacing the images. The version was returned from its submission draft to **Prepare for Submission**, and each old `04-dashcam.png` was replaced with that locale's corrected file. The English gallery was also missing `09-reference-signs-NL.png`; that selected reference image was restored.

Each locale was revisited after upload. All four galleries retain ten screenshots in order **01–10**, and their 6.5-inch groups inherit their respective updated 6.9-inch media. The uploaded German image was opened in Apple's image viewer and visually verified to show the genuine empty road. [Remote verification](apple-listing-update-2026-10-03/remote-verification.json) records the replacement file hashes, ordered galleries and saved UI proof. [The uploaded-image proof](apple-listing-update-2026-10-03/apple-dashcam-upload-verified.png) shows the actual Apple-hosted replacement. No final review submission or publication was performed.

The English preview was visible with a poster-frame editing control and no processing error before media editing became locked. Its poster frame was not changed. The portrait Dashcam screenshot does not occur in either video timeline, so this still-image correction requires no video rebuild. Publication and final review submission were not performed by this agent.
