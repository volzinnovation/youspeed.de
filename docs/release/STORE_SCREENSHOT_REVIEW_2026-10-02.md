# Store screenshot review — 2 October 2026

## Apple capture set

The iPhone set contains **ten ordered screenshots per locale** for `de-DE`, `en-US`, `fr-FR` and `nl-NL`: **40 PNGs**, each **1320 × 2868**, under `store/apple/screenshots/<locale>/iphone-6.9/`. Each selected screenshot demonstrates one state or flow. The set replaces the earlier repeated German fine/points/driving-ban examples with current camera, dashcam, secondary-sign and country presentations.

| Order / file | Presentation checked | Fixture |
| --- | --- | --- |
| `01-safe-speed.png` | 50 km/h map limit; 47 km/h telemetry | `warn-level-0` |
| `02-camera-speed-limit.png` | 30 km/h camera reference and its evidence marker; stationary controls | `camera-limit-active` |
| `03-secondary-sign.png` | Shared give-way pictogram alongside 50 km/h limit | `traffic-sign-pictogram`, `give_way` |
| `04-dashcam.png` | Upright portrait dashcam workspace and recorder controls | `camera-limit-active`, `YOUSPEED_SCREENSHOT_DASHCAM=1` |
| `05-france-fine.png` | **135 EUR** French money-fine example | `FR`, limit 50, excess 3, urban residential road |
| `06-switzerland-fine.png` | **250 CHF** Swiss money-fine example | `CH`, limit 50, excess 11, urban residential road |
| `07-belgium-fine.png` | **58 EUR** Belgian money-fine example | `BE`, limit 50, excess 5, urban residential road |
| `08-netherlands-fine.png` | Contextual **Review** indication; no invented money amount | `NL`, limit 50, excess 12, urban residential road |
| `09-pedestrian-zone.png` | Shared walking-zone artwork and 5 km/h telemetry | `pedestrian-zone` |
| `10-autobahn-unlimited.png` | Unlimited motorway sign and 142 km/h telemetry | `autobahn-unlimited-above-130` |

The France example was refined from excess 20 (which visibly selects two points) to excess 3 so that the store image itself shows the requested money fine. This changes screenshot input only. Belgian rule details additionally state the 2026 administrative fee; the selected primary presentation displays the base fine. The Dutch rules intentionally provide contextual consequences without a fixed tariff. The linked country report separately documents the official Dutch monetary reference (corrected +12: EUR 140 + EUR 9 fee) and the measurement-correction distinction; that reference is not rendered app output. See [the country-example report](COUNTRY_STORE_EXAMPLES_2026-10-02.md) for exact source-backed inputs, caveats and translated rule output.

## Authenticity and image checks

All images are **native simulator captures of the actual application UI**, using the repository's explicit screenshot fixtures. No image generation, replacement traffic-sign drawing, synthetic road footage or retouching was used in this capture set. The dashcam fixture does not start a physical camera or record a movie, so its live preview is empty. Camera/sign fixtures replay interpreted observations; they prove presentation, not model inference accuracy.

All four complete contact sheets were inspected for upright orientation, readable primary labels, correct sign states, unclipped controls and localized output. The simulator originally encoded all 40 captures as RGBA, with every alpha sample equal to 255. They were losslessly re-encoded as RGB for App Store compatibility; decoded RGB SHA-256 values, dimensions, sRGB metadata and EXIF are identical before and after. Originals are preserved outside the repository in `screenshots-rgba-final-originals/`; `screenshot-rgb-normalization.json` records the comparison and `screenshot-inventory-final.json` now records the RGB deliverables. A raw landscape simulator frame was initially sideways; the final dashcam capture uses the real portrait interface and requires no pixel rotation. The common fixture was repaired to seed its map/walking/unlimited input through the unchanged speed-reference runtime; this prevents startup callbacks from replacing a demonstration sign with unknown.

Evidence is retained outside the repository at `/private/tmp/youspeed-appstore-readiness-2026-10-02-iphone/`:

- `screenshot-inventory-final.json`: dimensions and SHA-256 for all 40 final images.
- `screenshot-reports-final/`: sixteen country reports and four give-way reports; every country and language resolved as requested.
- `contact-final-<locale>.jpg`: inspection-only contact sheets.
- `screenshots-final.log` and `france-fine-final.log`: successful captures, including the money-fine refinement.
- `screenshots-before/`: preserved original store images.

The capture script supports a prebuilt application, an external capture-report directory and a single-file filter, so individual fixtures can be regenerated without repeating the other images. It now invokes `scripts/iphone/normalize_store_screenshot.py` after capture, using the Pillow version declared in `scripts/iphone/requirements-screenshots.txt`; `SCREENSHOT_PYTHON` selects its Python environment and `RAW_CAPTURE_BACKUP_DIR` can select an external directory for originals. The normalizer refuses non-opaque alpha and verifies pixel/color-metadata equality before replacing a PNG. The local listing validator passed with zero errors after normalization. The script contains the final reproducible country inputs.

## Existing asset and model release gates

The screenshots consume the application's existing shared sign assets. Numeric speed signs retain the repository's approved schematic rendering exception. The sign sources, licence declarations and attribution requirements remain documented in [the shared pictogram README](../../shared/tsr/sign-pictograms/README.md) and [the existing copyright audit](../license-audit-2026-09-10/README.md). This screenshot work does not provide additional legal clearance.

The existing audit still requires a documented assessment of the Panoramax classifier's CC BY-SA training-data lineage and Ultralytics/AGPL distribution obligations. Adding credits or generating screenshots does not approve that model-release gate. The country registry records DE as shadow and FR/BE/NL as evaluation, with calibration, device/legal-action and runtime-manifest gates; [Swiss readiness](../TSR_CH_PANORAMAX_READINESS.md) likewise records a staged evaluation/shadow pack with production rollout blocked. These are internal release classifications and should not be substituted for the user-facing camera-recognition name.

The iPhone UI's remaining “experimental” labels apply only to the separate opt-in lane preview. Camera recognition is presented without that label. Store wording must describe available behavior without claiming validation or rollout beyond the accepted evidence.

## Android and submission handoff

Android capture/build verification is recorded separately in [Android readiness](ANDROID_READINESS_2026-10-02.md). Its set is limited to the Play Console phone-screenshot allowance. Apple screenshots and the verified local IPA are described in [iPhone readiness](IPHONE_READINESS_2026-10-02.md).

Review the selected screenshots and metadata together in the authenticated consoles before submission. No screenshot was uploaded, no listing was published and no physical device was deployed during this preparation.
