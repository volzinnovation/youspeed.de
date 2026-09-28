# Added TSR decision budget — 28 September 2026

The product constraint is **at most 200 ms of additional decision work** on the
slow Android phone. The recommended first implementation is a cached directed
map interval and candidate/track gate, targeting **under 5 ms**. An optional
low-resolution road-boundary stage should target **under 50 ms**, run at a bounded
cadence, and reuse only sufficiently fresh geometry. These are engineering
targets, not measured device results. Enforce the 200 ms added-work deadline;
expired visual geometry must not be represented as current evidence.

No attached device was queried, restarted or installed during this analysis.
Android's ongoing Panoramax upload was left undisturbed. Earlier device reviews
identify the phone as a moto g86 5G, Mali-G615 MC2 GPU / MT6878 chipset.

## Historical cost that informs the design

Recomputed from the preserved `traffic_sign_inference` records in
`inspector/logs/2026-09-28-fr-de-review/android/sep28.ndjson`:

| Historical measurement | Samples | Median | p95 |
| --- | ---: | ---: | ---: |
| Camera receipt to result, all sampled results | 9,768 | 395.03 ms | 696.93 ms |
| Camera receipt to result, classified detections present | 4,444 | 539.60 ms | 794.51 ms |
| Detector inference, all sampled results | 9,768 | 267.45 ms | 321.42 ms |
| Frame conversion, all sampled results | 9,768 | 23.92 ms | 36.13 ms |
| Backend queue wait, all sampled results | 9,768 | 0.17 ms | 2.10 ms |

All 9,768 records report GPU execution. Diagnostics are sampled, not an inventory
of every camera frame. The numbers are historical recognition costs, **not added
applicability latency**. Stage durations and percentiles must not be summed as if
they described the same frame or exclusive timing intervals.

| Classifier calls in a frame | Samples | Median inference | Median classifier time |
| ---: | ---: | ---: | ---: |
| 0 | 5,260 | 327.52 ms | 0 ms |
| 1 | 2,172 | 438.89 ms | 116.20 ms |
| 2 | 1,715 | 542.64 ms | 232.94 ms |
| 3 | 345 | 677.54 ms | 357.80 ms |
| 4 | 183 | 784.04 ms | 470.70 ms |

These groups contain different scenes. They demonstrate proposal-dependent cost,
not a controlled causal benchmark. Confidently rejecting an unrelated-road
proposal before classification could avoid roughly one classifier invocation;
the real saving and recall effect need measurement.

Both clients currently classify up to 12 proposals sequentially. Android's
detector has a fixed 1280 × 1280 input and its classifier uses 224 × 224.
Blanking an image region or cropping and resizing back to the same detector
shape does not remove detector graph work. A geometry-aware candidate gate can
improve attribution without a second full-image neural inference. New GPU lane
inference needs profiling under recording/preview load; the earlier
[latency review](ANDROID_PROCESSING_LATENCY_REVIEW_2026-09-14.md) documented GPU
contention in this phone.

Relevant implementations:

- iPhone reference: `iphone/SpeedConsumerApp/TrafficSignRuntime.swift:734` and
  `iphone/SpeedConsumerApp/TrafficSignApplicability.swift:396`.
- Android detector/classifier: `android/app/src/main/java/de/youspeed/android/alpha/AndroidTrafficSignRuntime.kt:395`.
- Android applicability integration: `android/app/src/main/java/de/youspeed/android/alpha/TrafficSignRecognitionOrchestrator.kt:672`.
- Candidate/track bounds: 32 candidates, 24 tracks, 12 history samples in
  `android/app/src/main/java/de/youspeed/android/alpha/TrafficSignApplicability.kt:44`.

## Reproduction and definitions

The full local summary is
`inspector/logs/2026-09-28-fr-exit-experiment/latency-summary.json`.
Its input SHA-256 is
`e37fa0e2298ab4c9f2a0add9519d5652bb1957ea0122f22b209452d9b1f1fdae`.
The log remains local because it contains drive locations. From the repository
root, reproduce the principal numbers without accessing a device:

```sh
python3 - <<'PY'
import json, math, statistics
from pathlib import Path
source = Path('inspector/logs/2026-09-28-fr-de-review/android/sep28.ndjson')
rows = [row for line in source.open()
        if (row := json.loads(line)).get('event') == 'traffic_sign_inference']
for name, group in [('all', rows), ('classified_detections', [
        row for row in rows if row.get('classifiedDetectionCount', 0) > 0])]:
    for key in ['cameraReceiptToResultMs', 'detectorInferenceMs',
                'frameConversionMs', 'backendQueueWaitMs']:
        values = sorted(row[key] for row in group)
        print(name, key, len(values), round(statistics.median(values), 2),
              round(values[math.floor((len(values)-1)*.95)], 2))
for calls in range(5):
    group = [row for row in rows if row.get('classifierInvocationCount') == calls]
    print('classifier_calls', calls, len(group), *[
        round(statistics.median(row[key] for row in group), 2)
        for key in ['inferenceMs', 'classifierInferenceMs']])
PY
```

Percentiles use the element at `floor((N-1)*q)` after ascending sort; the median
uses `statistics.median`. Added-work validation must separately time map/context
acquisition, geometry estimation, association/gating and scheduling delay under
sustained device load. A Mac replay cannot certify the phone's 200 ms deadline.
