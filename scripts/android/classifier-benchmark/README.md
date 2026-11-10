# Isolated Android classifier GPU benchmark

This separate `de.youspeed.classifierbenchmark` APK does not modify YouSpeed's
application, preferences, class mappings, model packs, or runtime policies. Its
LiteRT 1.4.2 dependencies match the native app. It has no network/camera permission.

Build with the repository's Gradle wrapper and a JDK17-or-newer runtime:

```sh
JAVA_HOME='/Applications/Android Studio.app/Contents/jbr/Contents/Home' \
ANDROID_HOME=/Users/raphaelvolz/Library/Android/sdk \
./android/gradlew -p scripts/android/classifier-benchmark --offline --no-daemon :app:assembleDebug
```

Stage a private directory containing `manifest.json`, model files, and PNG crops.
The schema matches the iPhone benchmark's image contract; artifact paths differ
by platform:

```json
{
  "schemaVersion": 1,
  "runId": "de136-gpu-run-unique-id",
  "warmupCount": 20,
  "rounds": 3,
  "repeatsPerImage": 1,
  "modes": ["gpu"],
  "models": [{
    "id": "candidate136",
    "path": "models/candidate136.tflite",
    "sha256": "EXACT_MODEL_SHA256",
    "classCount": 136,
    "classLabels": ["EXACT_ORDER_FROM_FROZEN_CHECKPOINT"]
  }],
  "images": [{
    "id": "stable-blind-image-id",
    "source": "android",
    "path": "images/native.png",
    "canonicalPath": "canonical/image.png",
    "sha256": "EXACT_NATIVE_PNG_SHA256",
    "canonicalSha256": "EXACT_CANONICAL_PNG_SHA256"
  }]
}
```

The illustrative label array must be replaced by every exact ordered label.
The shared prefix must match across models; city start/end occupy 134/135 in
models with at least 136 outputs. Append-only expanded models are supported and
their actual output width must match the hash-bound manifest's class count.
All image inputs must be opaque, orientation-normalized RGB PNGs. Canonical PNGs
must be exactly224×224. Native images are the supplied diagnostic crop, resized as
a whole; missing side/top context from the live camera ROI is not manufactured.

```sh
bash scripts/android/classifier-benchmark/run-benchmark.sh INPUT_DIRECTORY OUTPUT_DIRECTORY ADB_SERIAL
python3 scripts/android/validate_classifier_benchmark.py \
  --run OUTPUT_DIRECTORY/RUN_ID --inputs INPUT_DIRECTORY
```

Only GPU modes are accepted. `gpu` permits reduced precision and requests
`FAST_SINGLE_ANSWER`, matching the current Android startup path; `gpu_fp32`
disables reduced-precision GPU computation. A delegate load/inference failure
fails the trial. There is no whole-interpreter CPU fallback. Native logcat is
retained and independently parsed for delegated/total node counts and graph
partitions; partial GPU execution must be reported as such.

Three rounds reverse model order on alternate rounds. Each fresh interpreter
records load and first-inference time, then excludes warmups. Every measured crop
is tested through both canonical input and native preprocessing. Canonical
forward timing excludes PNG decoding and tensor preparation. Native measurements
separate Canvas scale-fill/RGB÷255 encoding, forward invocation, and their actual
combined duration. Output inspection/serialization is outside those timers.
Input decoding is measured separately while loading the corpus. Model invocation
includes the runtime's input/output transfers and synchronization.

Cold load means a new interpreter within the same process, without flushing OS
file caches. Results include raw sample durations, output vectors on the first
measured round, repeated argmax results, thermal/power/battery state, PSS/heap
snapshots, device/runtime versions and byte hashes. Saved native224PNG and tensor
hashes allow reference inference on the exact Android-preprocessed pixels.

These are real-device classifier-only measurements. They exclude detection,
camera scheduling, OCR and full-frame costs. No ground-truth labels are consumed,
so the harness does not calculate accuracy or F1. Keep its prediction artifacts
separate from a blind human-review queue. The validator recomputes every timing
summary and validates input hashes, output shape/argmax, trial completeness and
GPU coverage without using labels.
