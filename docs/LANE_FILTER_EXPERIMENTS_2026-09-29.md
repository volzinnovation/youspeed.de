# Recorded lane-filter experiments, 2026-09-29

Small grayscale filters recover additional paint response, but preprocessing alone does not make the current lane extraction reliable. The strongest compatible grayscale contender was a horizontal white top-hat enhancement. Its improvement in final visible boundaries was much smaller than its improvement in dense pixel response. The experiment initially left the live algorithm unchanged. Following the owner’s explicit request to enable the best tested approach, the live TSR path now applies top-hat5 before lane geometry, ahead of sign inference. It retains the experimental evidence semantics and existing deadlines; no speed-reference rule changes.

## Reusable experiment tools

- `scripts/lanes/compare_recorded_filters.py`: generates raw, area-resampled, Gaussian3, median3, bilateral5, CLAHE, top-hat5/9/13, signed Sobel/Scharr paired-edge8/12 and Canny30/90/50/150 variants. It records input/output hashes and host timings, and can invoke the native baseline.
- `scripts/lanes/RecordedBoundaryBaseline.swift`: runs the unchanged production `RoadBoundaryDetector` and legacy `LaneDetector` on exact supplied bytes. It applies no preprocessing or temporal tracking. The road detector has a 50 ms host deadline; output includes geometry, timing and input hash.
- `scripts/lanes/score_recorded_filters.py`: scores final PAINT, EDGE and legacy polylines separately against partial manual annotations, optionally scores dense filter responses, and renders annotated comparisons. It can also score experimental native-compatible NDJSON, with disjoint supported fragments kept separate.

These tools are offline experiments. Generated media, manifests, annotations and diagnostic/device logs stay under ignored `android/app/build/reports/road-path/`; do not commit recordings, location data, generated binaries or private absolute input paths.

## Reproduction

Requires Python with NumPy/OpenCV; the recorded run used OpenCV 5.0.0 with one OpenCV worker. The native baseline requires macOS Swift. From the repository root:

```sh
python3 -m venv /private/tmp/lane-filter-env
/private/tmp/lane-filter-env/bin/pip install numpy opencv-python-headless
swiftc -O -module-cache-path /private/tmp/lane-filter-module-cache \
  scripts/lanes/RecordedBoundaryBaseline.swift \
  iphone/SpeedConsumerApp/LaneDetection.swift \
  iphone/SpeedConsumerApp/RoadBoundaryDetector.swift \
  -o /private/tmp/recorded-boundary-baseline

/private/tmp/lane-filter-env/bin/python scripts/lanes/compare_recorded_filters.py \
  --dataset /absolute/private/dataset.json --output /absolute/private/new-run \
  --native /private/tmp/recorded-boundary-baseline \
  --native-source scripts/lanes/RecordedBoundaryBaseline.swift \
  --native-source iphone/SpeedConsumerApp/LaneDetection.swift \
  --native-source iphone/SpeedConsumerApp/RoadBoundaryDetector.swift

/private/tmp/lane-filter-env/bin/python scripts/lanes/score_recorded_filters.py \
  --dataset /absolute/private/dataset.json \
  --input /absolute/private/new-run/native-baseline.ndjson \
  --run /absolute/private/new-run \
  --annotations /absolute/private/annotations-tuning.json \
  --annotations /absolute/private/annotations-heldout.json \
  --tuning-source fourth --output /absolute/private/new-score.json \
  --overlays /absolute/private/new-overlays
```

Use a fresh output path. The scorer accepts repeated `--input`, `--variant` and `--frame-id`; omit `--run` for a structural prototype without filter response images. It never chooses parameters automatically. Freeze configurations on tuning sources before inspecting held-out scores. Record installed package versions and the code revision with each run; source and executable hashes are included when the arguments above are supplied.

Dataset schema is `{"schemaVersion":1,"frames":[...]}`. Each frame supplies `id`, `source`, `time` (source video PTS seconds), `grayPath`, `width`, `height`; optionally `rgbPath`, `fullGrayPath`, `rawWidth`, `rawHeight`. Gray files are packed UInt8, exactly width×height bytes. Paths may be absolute or relative to the manifest. Optional `graySha256`, `fullGraySha256`, `rgbSha256` are checked; actual hashes are always recorded for supplied inputs. Analysis dimensions must be admitted by the road detector: 64–384 by 64–216. Area-resampling is available only with full-resolution luma.

Annotation schema is `{"frames":[{"id":"sample","exhaustive":false,"boundaries":[{"kind":"paint","points":[[0.4,0.7],[0.3,0.9]]}]}]}`. Coordinates are normalized source-image coordinates after the same orientation/crop as the supplied gray image. Mark separate visible dashes as separate polylines. A `noPaintROI` polygon marks an explicitly unpainted negative control; optional `roadPolygon`/`ignorePolygons` restrict response scoring. The default evaluation band is y=0.50–0.94. Inspect original RGB before predictions and keep annotations non-exhaustive unless all paint is labeled.

Preserve decoded luma range, crop, orientation and resampling method across variants. A 16:9 recording is not automatically the same image geometry as a 4:3 live analysis frame. Source PTS identifies decoded frames; it does not independently verify original camera/GNSS synchronization or metric calibration. The scorer rasterizes one-pixel polylines at analysis resolution and allows a three-pixel elliptical tolerance. Coverage is summed covered labeled pixels divided by all labeled pixels, not an unweighted average of frames.

## Research directions and actual trials

1. **Smoothing and sampling.** Gaussian, median and bilateral kernels reduce noise differently; smoothing can also erase thin distant paint. Bilateral filtering is costlier than the simpler kernels. Compare unchanged nearest sampling with area resampling before adding more processing. [OpenCV filtering](https://docs.opencv.org/4.13.0/d4/d86/group__imgproc__filter.html).
2. **Bright paint ridges.** White top-hat is the input minus its morphological opening. A horizontal width-sensitive response can enhance paint with darker asphalt on both sides. It also enhances poles and vegetation; retain separate semantic and geometric checks. The tested enhancement is `min(255, gray + floor(1.5 * (gray − opening5x1)))`. [OpenCV morphology](https://docs.opencv.org/4.13.0/d9/d61/tutorial_py_morphological_ops.html), [Aly, IV 2008](https://arxiv.org/pdf/1411.7113).
3. **Signed gradients and Canny.** Preserve gradient sign in floating point to pair a rising and falling paint edge. The trials paired gaps of 2–10 pixels, then explicitly adapted binary responses into three-pixel bright ridges. These are altered representations, not ordinary grayscale inputs. Canny alone finds edges of many objects. [OpenCV gradients](https://docs.opencv.org/4.13.0/d5/d0f/tutorial_py_gradients.html), [Canny](https://docs.opencv.org/4.13.0/da/d22/tutorial_py_canny.html).
4. **Local contrast and color.** CLAHE may recover faded paint but also amplify texture. White/yellow color masks require actual chroma and lighting validation; luma cannot establish paint color. [OpenCV CLAHE](https://docs.opencv.org/4.13.0/d5/daf/tutorial_py_histogram_equalization.html), [color range masks](https://docs.opencv.org/4.13.0/da/d97/tutorial_threshold_inRange.html).
5. **Curves and causal tracking.** Aly's original pipeline combines width-sensitive filtering, perspective transformation and robust line/spline fitting. Metric perspective warping needs adequate camera/road assumptions. A separate prototype tested bounded quadratic consensus on dense image-space ridges and emitted observed fragments without joining unsupported gaps. Optical flow could later associate supported paint between nearby frames, with status/error checks and re-detection; it was not tested here. [Original paper](https://arxiv.org/pdf/1411.7113), [OpenCV sparse optical flow](https://docs.opencv.org/4.13.0/d4/dee/tutorial_optical_flow.html).
6. **Compact learned alternatives.** UFLDv2 and SwiftLane are possible research baselines, not validated Moto solutions. Official UFLDv2 CULane configuration uses ResNet18 and 1600×320 input, substantially different from this sidecar. Published desktop/Jetson throughput cannot establish Android latency or semantic accuracy on these recordings. No learned model was downloaded or run. [UFLDv2 paper](https://arxiv.org/abs/2206.07389), [official implementation](https://github.com/cfzd/Ultra-Fast-Lane-Detection-v2), [SwiftLane paper](https://arxiv.org/abs/2110.11779).

## Measured quality and limitations

The sweep used 154 decoded 384×216 video-range luma samples from four recordings: 2,310 native comparisons across 15 variants. Manual labels cover only 12 frames: six tuning frames from the fourth drive (five painted positives and one negative asphalt region), and six held-out earlier frames (four positives and two negatives). Labels are approximate, partial and not an accuracy benchmark. There are 492 tuning and 936 held-out rasterized paint pixels.

| Final PAINT polylines | Tuning coverage | Held-out coverage | False PAINT pixels in tuning / held-out negative asphalt regions |
|---|---:|---:|---:|
| Raw | 40.0% | 13.1% | 0 / 0 |
| Area resample | 38.0% | 13.1% | 0 / 0 |
| CLAHE | 33.3% | 12.4% | 0 / 0 |
| Top-hat5 enhanced gray | 60.8% | 25.7% | 0 / 0 |
| Scharr paired8, binary adapter | 64.2% | 63.7% | 0 / 69 |
| Canny30/90, binary adapter | 50.4% | 20.9% | 185 / 0 |
| Frozen dense quadratic, luma | 53.3% | 25.4% | 0 / 0 |
| Frozen dense quadratic, color gated | 52.0% | 27.2% | 0 / 0 |

Top-hat5 was selected from ordinary-gray-compatible variants using tuning labels before held-out scoring. Dense compatible-ridge coverage on held-out markings rose from 34.6% to 70.4%, while final PAINT coverage rose from 13.1% to 25.7% and legacy preview-boundary coverage only from 12.7% to 17.1%. This identifies substantial loss during grouping/support selection, without proving that every dense response is useful paint.

The quadratic configurations were frozen using tuning frames only. Their held-out result does not establish a clear winner over top-hat5. Fragment count is not physical boundary count. The prototype has no ego-path/corridor authority and its Python timings are not Android acceptance evidence.

Zero paint inside the three negative asphalt polygons does not establish general precision. Visual review found vegetation, posts and guardrails promoted into paint outside those limited regions. Canny produced many more image corridors without corresponding reliable markings. A production candidate needs more labeled negatives, curved/dashed/occluded scenes, and meaningful temporal evaluation. Do not use boundary/corridor counts as an accuracy score.

## Moto component timing

`LaneFilterExperimentInstrumentedTest.kt` compared raw and top-hat5 on all 154 exact decoded samples on the Moto g86. All 154 Android filter outputs matched OpenCV output SHA256. With filter plus detector sharing the 50 ms geometry deadline, raw p95/max was 5.93/50.16 ms; top-hat5 p95/max was 14.37/56.65 ms. Top-hat filtering alone had p95 5.58 ms and cold max 56.58 ms. Both cold deadline failures were retained: one raw and one top-hat geometry abort; none reached 200 ms.

This historical decoded-pixel component test is not full live-camera qualification. Its original experimental filter was uninterruptible and could exceed 50 ms before the detector returned empty geometry. The production filter checks cancellation during processing and shares the original 50 ms geometry deadline. The historical benchmark excludes live luma-copy/other sidecar work, and its 384×216 recording pixels differ from the current 288×216 live analysis sample. It does not establish lane accuracy or justify extending the live deadline.

## Production-filter verification, build 10017

The interruptible production kernel was rerun on the Moto against the same 154
recorded reference images: **154/154 exact OpenCV SHA256 matches**. Filter plus
detector p95 was **12.65 ms**, maximum **50.01 ms**, with one top-hat geometry
abort and zero 200 ms misses. This is component timing; the full two-phase
recorded-video replay is documented in the lane/trajectory implementation report.
