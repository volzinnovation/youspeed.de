# SGBlur YOLO26s candidate, 20 October 2026

Recommendation: keep YOLO11n as the bundled detector. The additional
[dashcam replay](SGBLUR_YOLO26_DASHCAM_REPLAY_2026-10-20.md) did not justify an
automatic switch at the current 1024 input size; native phone performance also
remains unmeasured.
The initial known-box comparison improves recall but does not establish release
readiness. Compatible Core ML and LiteRT candidate exports have been produced
and exercised locally. No app bundle, server configuration or device install
was changed.

## Source and comparison

[Upstream commit fa832620](https://github.com/cquest/sgblur/commit/fa83262033b6addb9c8085caa5a0fd82d212f16a),
dated 6 October 2026, adds only `models/yolo26s_face_plate_sign.pt`.
It does not select the model in the detection service or supply a controlled
comparison with the older detector.

| Property | Bundled YOLO11n | Candidate YOLO26s |
| --- | ---: | ---: |
| Original checkpoint bytes | 5,979,923 | 20,663,557 |
| Original, unfused parameter count | 2,590,425 | 9,950,186 |
| Saved training `imgsz` | 2048 | 2048 |
| Known mobile-window sign boxes found | 10 / 16 | 13 / 16 |
| Mac CPU `predict` median | 60.06 ms | 108.25 ms |

Both checkpoints have `0=sign`, `1=plate`, `2=face`. Their SHA-256 values are:

```text
YOLO11n 698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a
YOLO26s 86e2380d9dd13541280f74fac9e416618a4cdd1541ada02ae93d103195c524be
```

The comparison uses the 13 existing learning/validation scenes from the lecture
review, excluding every reserved scene. Each source image is hash checked.
Preparation approximates the current mobile window: full image height scaled
to 1024, rightmost 1024 columns, RGB-114 left padding for narrow portrait images.
Only the 16 known sign boxes entirely inside that window enter the denominator.
Confidence is 0.25, NMS IoU is 0.7, and one-to-one GT matching requires IoU 0.5.
YOLO26s gains three matches and loses none of YOLO11n's ten matches. Its
end-to-end branch also finds 13/16, but the table reports the compatible
one-to-many branch used by the candidate mobile exports.

These are partial, assistant-reviewed annotations on previously used learning
images. They cannot establish precision, mAP, generalization, face/plate quality
or the quality of the downstream classifier. The 1.8× timing ratio comes from
ten repeated `predict` calls on the same window after three warmups, four CPU
threads, Torch 2.7.0 and Ultralytics 8.4.56 on this Mac. It includes Python
prediction preprocessing/postprocessing and is not an iPhone/Android benchmark.

Full predictions, matches, hashes, timings and conversion checks are retained in
[the machine-readable evidence](../lectures/tsr-sgblur-de-2026-10-26/source/yolo26-candidate-review-2026-10-20.json).
Upstream training metrics are not compared as a common test: their datasets,
evaluation procedures and exact splits have not been shown to be identical.

## Compatibility with both apps

The original YOLO26 checkpoint has `end2end=true`. Its default raw output is
`[1,300,6]`, containing `xyxy, score, class_index`. Android currently requires
`[1,7,21504]`, with normalized `xywh` and three class scores. iPhone expects a
Vision recognized-object model with a Core ML NMS pipeline. Renaming and copying
the checkpoint or using the existing exporter without checking this distinction
would not preserve those contracts.

Separate local conversion experiments explicitly selected YOLO26's
`end2end=false` one-to-many head for both platforms, verified the raw output
shape, and exported Core ML with NMS and LiteRT without NMS. Their recorded
checks below describe those local artifacts. The versioned mobile exporter
remains the YOLO11n baseline; the optional YOLO26 exporter changes are outside
this lecture-materials commit. These checks do not establish the performance
benefits of an NMS-free integration or a production model replacement.

Local candidate checks completed:

- Core ML export and Xcode compilation at 1024, plus actual macOS Vision
  `VNRecognizedObjectObservation` results labeled `sign` on both bundled photos.
- Core ML CPU versus PyTorch on those photos: maximum top-sign-score difference
  0.000690.
- LiteRT float32 external tensors `[1,1024,1024,3]` to `[1,7,21504]`, with FP16
  stored weights, loaded and invoked by the LiteRT CPU interpreter.
- LiteRT versus float32 checkpoint on seeded random RGB and both photos:
  maximum class-score difference 0.000932 and normalized-coordinate difference
  0.003171, each within the existing 0.05 comparison tolerance.

The candidate files remain in ignored local staging under
`.codex-tmp/yolo26-review-20261020/`, with separate `ios/`, `compiled/` and
`android/` outputs. The `.pt` source is retained unchanged and all generated
files can be reproduced. These are evaluation artifacts, not accepted app packs.

## Completing a switch

1. Evaluate fully reviewed driving scenes, including small/distant signs, both
   bright and dark conditions, and false proposals. Keep the existing thresholds
   and country classifiers for this comparison.
2. Exercise the same fixed window and complete detector/classifier flow on both
   attached phones. Measure latency, GPU/CPU fallback, sustained thermals and
   memory. The new model's larger weights are not a RAM measurement.
3. If accepted, replace the shared detector in all five country packs on each
   platform. Update component/source/artifact IDs, hashes, export records,
   parity/calibration bindings, shadow identities and any registry signatures
   that bind those manifests. Run the existing pack checks and device startup
   probes. Do not change classifiers, thresholds or speed-reference policy to
   make the candidate pass.
4. Deployment and publication remain separate, explicitly approved actions.

The lecture leaves fine-tuning and evaluation to the students. These
measurements compare published pretrained checkpoints; they are not outcomes
of the student assignment.

## Reproduction

From the repository root, with the pinned checkpoints and local lecture images:

```sh
python scripts/tsr/compare_sgblur_detectors.py \
  --baseline PATH_TO_VERIFIED_YOLO11N.pt \
  --candidate PATH_TO_VERIFIED_YOLO26S.pt \
  --review PATH_TO_INSTRUCTOR_LOCAL_TARGET_REVIEW.json \
  --images-root lectures/tsr-sgblur-de-2026-10-26/.build/student-collection-2026-10-19/collection/inbox/detector \
  --output NEW_COMPARISON.json

```

The target-review JSON is an instructor-local input; the portable evidence retains
its hash and known boxes. It is not a student training-result export.

The recorded local conversion used
Torch 2.7.0, Ultralytics 8.4.56, CoreMLTools 9.0, ONNX 1.17.0, onnx2tf 1.28.8,
TensorFlow 2.19.0 and Python LiteRT 1.3.0. Ultralytics also downloads its public
sample array during TensorFlow export. This FP16 export does not calibrate INT8
or establish detector confidence calibration.
