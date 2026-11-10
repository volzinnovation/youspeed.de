# German town-sign detector trial

The Debug builds can select the one-class YOLO26n checkpoint
`f02bf99483c5ad2b79f254b1623b18593ed780c8f3c2df7051331633bb1a2a36`
at detector confidence **0.840783**. The classifier has its own thresholds.
SGBlur remains bundled and is selected when the local trial artifact is absent
or fails verification or startup. YouSpeed on Android also returns to SGBlur
if the trial runtime repeatedly fails during live analysis.

| Platform | App-private artifact | SHA-256 |
| --- | --- | --- |
| Android | `files/town_yolo26n_trial_float16.tflite` | `9bf554f86b0e8e695430905e97bfd7eabdb713941d94c5ea1dcaaab7cb692041` |
| iPhone | `Documents/town_yolo26n_trial.mlmodelc` | `73a2818194be58673ba63fa7c92f6c12f9d0ef046f39649bd97d89e65578c026` |

The Core ML digest covers sorted relative paths and file bytes, with a NUL
after each path and payload. Both artifacts were verified in the device app
containers. The release builds do not accept the local override. A repeat LiteRT export
on KI produced a different artifact digest and identical raw tensors on four
checked corpus images. Use the listed binaries for this trial. Verify and
explicitly pin a different digest before installing a re-export.

Use `../export_town_trial_detector.py` with `--checkpoint`, `--architecture`
(the pinned upstream YOLO26n weights) and `--output`. Run the `coreml` and
`tflite` exports in the pinned conversion environments. Core ML Tools 9.0
exports the Vision object pipeline. The LiteRT chain uses ONNX 1.17.0,
onnx2tf 1.28.8, TensorFlow 2.19.0 and Python LiteRT 1.3.0. Both use Ultralytics
8.4.56 and produce FP16 1024-square exports. Compile the Core ML package with
`xcrun coremlcompiler compile` on the Mac.

## Paired replay

- Run `prepare_replay.py OUTPUT VIDEO ...` to sample three six-second windows
  at 4 Hz per long video. Alternatively, pass the frozen scene manifest and
  original image directory using `--scene-manifest` and `--scene-images`.
  The resulting image files and `frames.json` are the common phone inputs.
- On Android, copy the fixture to the Debug app's `files/town-trial-replay`
  and run `TownDetectorTrialInstrumentedTest#replayOnGpu` on the selected Moto.
  Retrieve `files/town-trial-results.json` from the same app container.
- On iPhone, generate the benchmark project with XcodeGen and build it for
  the attached device. Copy the fixture to the benchmark's `Documents/replay`
  and the compiled detectors to `Documents/sgblur.mlmodelc` and
  `Documents/town.mlmodelc`. Launch the app and retrieve
  `Documents/results.json`. The benchmark records Core ML's preferred device
  placement when the OS supports compute plans.

The 10 November 2026 trial was installed as YouSpeed 1.5 build 10092. On 64
reviewed scenes, both phones found 6/23 town signs and 22/48 other signs with
YOLO26n, versus 2/23 and 27/48 with SGBlur. YOLO26n produced 7 false positives
on each phone. SGBlur produced 14 on the Moto and 15 on the iPhone.

On 84 archived road frames the Moto detector p50/p95 was 149.7/165.8 ms for
SGBlur and 152.8/165.5 ms for YOLO26n. The iPhone measured 18.9/20.2 ms and
16.8/17.8 ms respectively. LiteRT delegated the whole YOLO26n detector on the
Moto. The Core ML compute plan preferred the Neural Engine for 264 candidate
operations. These detector timings exclude the live camera, classifier and lane
pipeline. Fresh drive encounter metrics remain pending.
