# BW v1.5 local runtime test bundle

This is the implemented runtime bundle, requiring app version 1.5. It is distinct
from the older disabled pilot. See the repository's
`docs/MOBIDATA_BW_V1_5_IMPLEMENTATION.md` for build and installation instructions.

- Manifest: `baden-wuerttemberg_manifest.json`.
- Download: `baden-wuerttemberg_speeds.sqlite.gz` (695,751,651 bytes).
- Materialized DB: 2,122,903,552 bytes.
- Materialized SHA256: `e1a36e56cc4809cc69d2d5161b993eff21a1c08264e8d9300e79ec7546ccd00b`.
- 163,504 MobiData signs plus 8,800 attributed OSM town stations.
- 118,400 directed intervals, 37,807 continuation proofs.
- Structural and optional runtime gates pass with no errors; structural warnings 0.

Secondary signs use 10 m, town signs 30 m. Town passage resets prior references;
DE:278/282 retain existing enclosing-zone semantics. Both apps implement local
camera confirmation logs and a mutually exclusive inventory-sign capture mode.
Proximity never constitutes visual confirmation and never turns on the camera.

`runtime-diagnostics.json` has source-backed inspection targets and coverage.
`sign-pictograms/` contains 49 official SVG/PNG pairs with provenance/notices.
The apps package the full 117-pair shared set. Typed grade/mass/dimension fields
are supported, but this source contains none. Town signs, numeric 90 and other
unsupported classifier classes log their limitations; no new model is claimed.

Use the repository's Android emulator installer or documented iPhone simulator
bundle layout. Loading this artifact is local acceptance, not a measured physical
drive. The pinned road PBF is from September 13; MobiData snapshot is October 17.

`implementation-validation.json`, platform receipts, both validation reports and
`checksums.sha256` record the final artifact and tests. No release was uploaded.
