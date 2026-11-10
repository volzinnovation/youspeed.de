# Isolated iPhone classifier benchmark

This target installs `de.youspeed.ClassifierBenchmark`; it does not replace
`de.youspeed.SpeedConsumer.TestHost`, modify production model packs, or run
the speed-limit state machine. It accepts a frozen input package in its own
Documents directory and writes raw measurements there.

The manifest explicitly selects Core ML `computeUnits`: `cpuAndGPU` (the
backward-compatible default) excludes the Neural Engine but permits CPU
execution; `all` permits CPU, GPU and Neural Engine execution. The user has
requested that the Neural Engine be included, so retain a separate `all` run
and keep its identity distinct from any `cpuAndGPU` comparator. The report
includes `MLComputePlan` anticipated operation placement, not an observed
hardware trace. Neither mode guarantees execution exclusively on an accelerator.

Each round reverses baseline/candidate order. Each model is loaded and warmed
equally in every round. Measurements distinguish:

- Direct Core ML prediction on a predecoded canonical 224×224 RGB pixel buffer.
- Native PNG decoding, request setup, and Vision `.scaleFill` plus inference.
- Model loading and first prediction, with OS/filesystem-cache limitations.
- Sampled resident memory and thermal state, not true peak GPU memory.

The entire supplied native crop is classified. The harness does not fabricate
missing live-camera ROI context. It records full scores for numerical parity;
it never reads ground-truth labels or computes F1.

Generate and build from the repository root:

```sh
xcodegen generate --spec iphone/ClassifierBenchmark/project.yml
xcodebuild build \
  -project iphone/ClassifierBenchmark/ClassifierBenchmark.xcodeproj \
  -scheme ClassifierBenchmark -configuration Release \
  -destination 'generic/platform=iOS' \
  -derivedDataPath /private/tmp/youspeed-classifier-benchmark-build \
  -allowProvisioningUpdates -allowProvisioningDeviceRegistration
```

Run `scripts/iphone/run_classifier_benchmark.py --help` for staging and execution.
Use `--stage-only` before requesting an unlock, then `--already-staged` to launch
immediately when the device is unlocked. The runner requires a real device and
does not substitute simulator timing. The app disables auto-lock during the run.
`--wait-unlock 600` can wait up to ten minutes for the user to unlock the phone;
it only reads lock state and never changes passcode or trust settings. Do not
start another runner for the same app while an earlier run is active.

The input `manifest.json` declares `schemaVersion: 1`, optional `computeUnits`
(`cpuAndGPU` or `all` only), `warmupCount`, `rounds`,
`repeatsPerImage`, `models`, and `images`. Each model has `id`, `path`,
`classCount`, `classLabels`, and `sha256`; each image has `id`, `path`,
`canonicalPath`, `sha256`, `canonicalSha256`, `canonicalRGBSha256`, and `source`.
Paths are relative to the package. File hashes are ordinary SHA-256. Directory
model hashes cover sorted POSIX relative paths, NUL, lowercase file SHA-256,
and LF, concatenated as UTF-8. The RGB digest covers packed row-major RGB bytes
of the opaque canonical image. The app verifies these identities before timing.

After retrieving a result, run `scripts/iphone/validate_classifier_benchmark.py`
with `--result`, `--manifest`, and `--output`. It recomputes quantiles from the
raw measurements, validates counterbalanced order and exact image/model/class
identities, and checks GPU configuration. Human label approval and classifier
evaluation remain separate from this performance measurement.

`scripts/iphone/compare_classifier_gpu_reference.py` compares first-pass
canonical output vectors with a frozen CUDA NPZ reference. It verifies the
reference file hash, class order, exact RGB bytes and normalized float32 tensor
hashes before computing top-1/top-5 numerical agreement and probability error.
Its outputs must stay outside blind annotation folders. Numerical agreement is
not classifier accuracy or F1.

For preprocessing comparisons, supply the same frozen sign window to both
native and canonical paths. A whole stored crop may contain padding, background
or adjacent signs absent from the canonical sign window; output differences
then include ROI/context changes and cannot be attributed to resizing alone.
Neither fixture reconstructs the unavailable padded live-camera ROI.
