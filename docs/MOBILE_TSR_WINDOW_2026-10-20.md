# Mobile traffic-sign recognition window

iPhone and Android use the same fixed recognition input, independently of saved
mounting or lane calibration:

1. Orient the camera image upright.
2. Scale proportionally to a height of 1024 pixels.
3. Retain the rightmost 1024 columns, producing a 1024 × 1024 image.

For example, a 3840 × 2160 frame retains the original region
`x = 1680..<3840`, at full height. The implementation renders the transformed
region directly, without allocating a scaled full-width intermediate. Android
reuses the destination bitmap. Portrait sources narrower than 1024 after scaling
are right-aligned and padded with RGB `(114, 114, 114)` on the left.

Detection, classification and local OCR use the 1024 window. Results stay in
window coordinates; there is no conversion back to full-camera coordinates.
Classifications continue through the existing display, tracking and
speed-reference pipeline.

Consented upload crops use the same window at native resolution: for a 4K
landscape source this is the original rightmost 2160 × 2160 pixels. Normalized
window boxes also address these original pixels, so no box remapping or image
resizing is needed. iPhone retains the original exposure and renders only a
requested crop rectangle after collection selection. Android owns a native
window only when crop collection requests evidence, with one outstanding frame
at a time. PNG encoding and upload metadata retain the existing server contract.

Full-frame lane detection remains separate. Its shadow sign-position association
is skipped for mobile window results. Window boxes are also excluded from
projection onto full-size Panoramax JPEGs; sign-crop collection uses the matching
window image. Original driving photos and dashcam video retain their resolution.

Server-side code, image processing, model packs and inference behavior are
unchanged. The mobile Core ML and LiteRT detectors are re-exported from the same
pinned SGBlur checkpoint with fixed 1024 × 1024 inputs. Android's raw output has
21,504 proposals instead of 33,600. No second enlargement of the window is
needed; classifiers retain their existing 224 × 224 inputs and weights.

Regression coverage checks crop pixels, full-height retention, EXIF orientation,
resolution independence, portrait padding, Android buffer reuse, calibration
independence and isolation from full-frame photo annotations. An Android
instrumentation test also runs the bundled reference sign through the real
detector and classifier.

## Validation

- iPhone simulator: 9 tests passed, including actual CPU Core ML inference at
  1024, every EXIF orientation, 16 mount/calibration combinations, native pixel
  retention and isolation from full-frame photo/lane coordinates.
- Android: 141 focused unit tests and 4 emulator instrumentation tests passed,
  including the real LiteRT model and native-resolution PNG crop generation.
- Shared model-pack checks: 45 tests passed. Existing offline Swift collection
  checks passed, including PNG provenance, repeat crops and upload contracts.
- All ten mobile packs have verified detector hashes and 1024 inputs.
  Classifier artifacts, classifier metadata and confidence thresholds are unchanged.
- Core ML export parity on two bundled images: maximum absolute sign-score
  difference from the original checkpoint was 0.01444 (limit 0.05).
- LiteRT versus float32 ONNX on seeded RGB input: maximum sign-score difference
  was 0.00001325; maximum normalized coordinate difference was 0.0004373.

The distant portrait reference `tsr-panoramax-49e25e66.jpg` yields a proposal
score around 0.29 at 1024, below the existing 0.70 confirmation threshold. The
nearer `0906fc23` reference remains above that threshold. Reduced distant-sign
confidence is retained as a measured limitation; thresholds were not lowered.

Each mobile pack includes `provenance/mobile-detector-1024.json` with checkpoint,
export-environment identities, artifact hashes and parity measurements. The
conversion entry point is `scripts/tsr/export_mobile_detector.py`.
