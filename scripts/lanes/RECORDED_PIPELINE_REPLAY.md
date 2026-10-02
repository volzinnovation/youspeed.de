# Offline recorded lane-pipeline replay

`replay_recorded_pipeline.py` compiles a snapshot of the native Swift production
pipeline and runs supplied raw luma through `RoadPathSession.prepare/evaluate`.
This includes the production filter, detector, temporal tracker, presentation gate
and their existing deadlines. It does not open a camera or communicate with a
device. macOS and `swiftc` are required; Python uses only its standard library.

```sh
python3 scripts/lanes/replay_recorded_pipeline.py \
  --manifest /absolute/path/to/dataset.json \
  --output-dir /absolute/path/to/new-replay-output \
  --variant baseline
```

The output directory must not already exist. To compare an archived baseline or
experimental implementation, pass `--source-dir /path/to/swift-sources`. That
directory must contain the nine production source filenames listed in the Python
runner. Every run copies those files and the harness into its own `sources/`
directory and records their hashes, so later edits do not change completed runs.

## Input contract

```json
{
  "schemaVersion": 1,
  "frames": [
    {
      "id": "clip-a-000001",
      "sequenceId": "clip-a",
      "grayPath": "clip-a-000001.gray",
      "graySha256": "optional lowercase SHA256 of the supplied bytes",
      "width": 384,
      "height": 216,
      "decodedWidth": 1280,
      "decodedHeight": 720,
      "time": 10.004344444444444,
      "source": "recording-a"
    }
  ]
}
```

Remove `graySha256` if no hash is available; the runner computes and freezes it.
Gray paths may be absolute or relative to the manifest. The file must contain
exactly `width * height` raw, row-major 8-bit luma bytes. Supply unfiltered input;
the production filter runs inside the session. Preserve and document the decoded
luma range and sampling method in the dataset. The runner performs no resampling
or range normalization. Width must be 64–384 and height 64–216; decoded dimensions
default to these analysis dimensions and must have a compatible aspect ratio.

`time` is the actual encoded-video PTS in seconds, not the requested extraction
time. The existing `actualVideoSeconds`, `rawSha256` and `clipId` field aliases are
also accepted. Frame IDs are unique. Frames from each sequence must be contiguous
and have strictly increasing PTS; changing `sequenceId` creates a fresh session.
Sparse inputs retain their real gaps and cannot establish temporal continuity.

No GPS, road context, sign observations, metric calibration or visual calibration
is supplied. A relative PTS clock establishes ordering only; the runner does not
invent UTC alignment or transfer a 4:3 live-camera calibration to 16:9 video.

## Outputs and interpretation

- `frames.ndjson` contains raw and confirmed boundary polylines, visible boundary
  indices and presentation IDs, provenance, presentation/motion diagnostics,
  operation counts, publication suppression, component timings and input hashes.
  `road.boundaries` also exposes raw output in the existing annotation scorer's
  format; `visibleRoad.boundaries` exposes only published mature boundaries.
- `summary.json` reports counts and timing quantiles overall and per sequence.
- `metadata.json`, `input.normalized.json`, `sources/`, compile/run logs and the
  executable preserve the inputs and implementation used for the run.

Boundary counts are availability diagnostics, not accuracy scores. Score geometry
against annotations made from original imagery without inspecting predictions.
Separate moving-road and parked-camera intervals. Host timings exclude decoding,
luma sampling, file IO, hashing and result serialization; they are not mobile
device latency or full camera-decision latency. Encoded video is not a substitute
for the original camera-analysis exposures.

## Frozen-label comparison

`score_recorded_pipeline.py` uses the existing `score_response` definition to score
raw and published PAINT separately. It requires NumPy and OpenCV. Supply partial
manual annotations in the existing `boundaries` / `noPaintROI` format; optional
`condition` and `split` fields produce separate aggregates. Never relabel frames
after inspecting predictions to improve a candidate's score.

```sh
python3 scripts/lanes/score_recorded_pipeline.py \
  --dataset /absolute/path/to/dataset.json \
  --annotations /absolute/path/to/frozen-annotations.json \
  --input /absolute/path/to/baseline/frames.ndjson \
  --input /absolute/path/to/candidate/frames.ndjson \
  --output-dir /absolute/path/to/new-score-output \
  --render
```

The default tolerance is three analysis pixels. Only explicit `noPaintROI`
polygons are negative labels; off-annotation responses elsewhere remain
unclassified. `scores.json` contains per-frame, condition, split and overall
results with input hashes. Optional RGB comparison sheets use 640×360 panels:
manual paint is magenta, explicit no-paint regions cyan, and predicted PAINT
green. Raw and published output occupy separate rows. These small partial-label
audits establish neither complete lane accuracy nor correct corridor geometry.
