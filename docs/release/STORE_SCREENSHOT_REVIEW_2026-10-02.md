# Store screenshot review — 2 October 2026

The complete native reference collection contains **221 captures**: 68 iPhone images in English, French, German and Dutch, and 153 Android images in those four languages plus Spanish, Italian, Polish, Brazilian Portuguese and Swedish. Each locale includes sign catalogs for DE, FR, CH, BE and NL, and fine tables for DEU, FRA, CHE, BEL, NLD, GBR, LUX, LIE, MCO, ROU, SWE and ISL.

The references show existing shared pictograms, reviewed spoken names in English → French → German → Dutch order, and existing fines JSON. They add presentation, without authoring legal data. Missing speech and fine fields retain the application's explicit unavailable/unspecified labels. Both views show the localized not-legal-advice note.

## Upload gallery selection

Apple has ten selected images per locale, 40 total, each 1320×2868. Play has eight images per locale, 72 total, each 1080×1920. These gallery limits require selecting from the complete reference collection.

| Apple order | Content | Play order |
| --- | --- | --- |
| 01 | Safe speed/map display | — |
| 02 | Camera speed-limit reference | 01 |
| 03 | Shared secondary-sign pictogram | — |
| 04 | Dashcam workspace | 02 |
| 05 | German sign reference | 03 |
| 06 | French sign reference | 04 |
| 07 | Swiss sign reference | 05 |
| 08 | Belgian sign reference | 06 |
| 09 | Dutch sign reference | 07 |
| 10 | Dutch fine reference | 08 |

The Dutch iPhone gallery capture was refined to show the country, road context, administration fee, currency and table headings together. The all-country reference collection remains available for review independently of the selected upload gallery.

## Capture evidence and verification

The iPhone country-reference XCTest actually executed one test and passed with zero failures, producing 68 attachments. A second executed capture test passed with zero failures and produced four replacement Dutch fine captures with table headings visible. Source attachments and XCResults are retained under `/tmp/youspeed-reference-iphone-attachments/`, `/tmp/youspeed-reference-penalty-store-attachments/` and the screenshot-derived Logs/Test directory. Capture names and timestamps are retained in `store/reference-screenshots/apple/capture-report.json`.

Android captures came from the native emulator app through `scripts/release/capture_android_reference_screenshots.py`. Every image has a UIAutomator XML sidecar; all 153 country selectors match the requested country in the requested locale. The script restores the emulator's prior locale and logical display size. Screenshot country overrides are compiled out of release builds.

[Reference validation](REFERENCE_SCREENSHOT_VALIDATION_2026-10-02.json) checks all expected country/locale combinations, dimensions and file hashes: zero errors. Every Apple image is RGB. Lossless alpha-removal reports record identical decoded pixels and preserved color metadata; the opaque RGBA originals remain outside the repository. [Listing validation](STORE_PACKAGE_VALIDATION_2026-10-02.json) checks the 220 selected metadata/image files, including Fastlane mirrors and screenshot provenance: zero errors.

The upload layouts wrap the complete, unchanged native captures in localized headlines. `store/artwork/screenshot-layouts.json` records source/output hashes; the renderer proportionally scales the entire image. No synthetic road scene or recognition result was inserted into the app capture. Existing camera feature fixtures prove presentation, not inference accuracy. Their dashcam camera preview is empty. Generated road photography appears only in the separate Play feature graphic, with provenance in `store/artwork/source/generation.json`.

Native sign and fine captures, sample composed galleries and the refined Dutch fine page were visually inspected. Shared sign artwork was not redrawn or substituted. Existing model-lineage, licence and rollout gates remain documented in the [copyright audit](../license-audit-2026-09-10/README.md) and [Swiss readiness](../TSR_CH_PANORAMAX_READINESS.md); screenshot generation does not close those gates.

The selected new galleries are prepared locally. They have not yet replaced the inherited assets in either console. See [submission status](STORE_SUBMISSION_1.3_2026-10-02.md) for the current upload and device state.
