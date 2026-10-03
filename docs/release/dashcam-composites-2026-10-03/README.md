# Real Dashcam artwork — 3 October 2026

The black recording preview in the store artwork now uses a real empty-road frame from the user's iPhone Dashcam recording. No visible people or cars appear in the source crop or final Apple and Android views. The crop also removes the recording car's mirror, dashboard and hood.

The frame is retained at `store/artwork/source/real-dashcam-5.5s.png`. Its SHA-256 and archive provenance, timestamp, crop and native viewport geometry are in `store/artwork/dashcam-preview.json`. The original video SHA-256 is `f622d4746220f98b9ac66b8a323e51d0c2dcb44a3b51068b4e842fcf99577402`; the frame SHA-256 is `d9b504dc1ca06a9f144d83ef65e18c40b9880425b386ff1d24128ec7701a5e7f`.

The user requested a composition of genuine recording pixels into retained native demonstration UI. It is not a live screenshot of the depicted recording session. Native borders, caption capsules, controls and other UI pixels remain intact, and raw source captures are unchanged. Both apps' centered aspect-fill camera behavior is used.

Four Apple images at 1320 × 2868 and nine Android images at 1920 × 1080 were regenerated. Android's nine Fastlane mirrors are byte-identical to their corresponding gallery images. Other gallery, web, social, onboarding and video assets do not contain this camera viewport and were left unchanged.

[Pixel validation](validation.json) passed for 13 composites and 314 baseline image hashes. It verifies dimensions, opaque RGB output, original/output hashes, mirror equality, and zero changes outside the final mapped pane or to native UI/caption pixels. [Package validation](store-package-validation.json) also passed without errors. The small baseline records reference temporary review evidence and can be regenerated from a retained pre-edit snapshot for a future comparison.

Re-render with `node scripts/release/generate_store_screenshot_layouts.mjs --only-dashcam`, providing `YOUSPEED_SHARP_MODULE` if Sharp is outside the normal module path. Apple contact sheets and the upload manifest are under `docs/release/apple-gallery-review-2026-10-03/` and `docs/release/APPLE_SCREENSHOT_READINESS_2026-10-03.json`.

All four Apple replacements were uploaded after the user authorized returning version 1.3 to its editable draft. Each locale was revisited to verify ten screenshots in order 01–10 and inherited smaller-display media. [Remote verification](../apple-listing-update-2026-10-03/remote-verification.json) records the saved changes. Version 1.3 remains in Prepare for Submission; no final review submission or publication was performed. No Play Console upload was attempted by this artwork task.
