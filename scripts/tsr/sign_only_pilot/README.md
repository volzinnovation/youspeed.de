# Sign-only detector experiments

These scripts preserve the d5–d10 research workflows and their frozen inputs,
training definitions, development-only model selection, and evaluation records.
They are experiment tooling, not the mobile detector release pipeline.

- `select_pilot.py`, `assemble_reviews.py`, `pseudo_admission.py`, and
  `full_source_eligibility.py` define review queues and conservative label intake.
- `prepare_*`, `freeze_*`, and `assemble_*` freeze datasets and experiment inputs
  before training. `balanced_views.py` defines the paired phone/tile schedules.
- `train_*`, `launch_*`, and `replay_*` train on KI and replay the recorded phone
  geometry. Swift rendering is in `NativeDetectorRender.swift`.
- `mapillary_auto_sample.py` and `benchmark_*` compare against incomplete
  automatic references. Unmatched predictions are not verified false positives.
- `package_*`, `snapshot_*`, and `publish_*` retain per-experiment publication
  recipes. The publisher variants intentionally preserve their historical paths,
  allowed prefixes, and payload handling; they default to dry runs.

Some entry points use the original KI paths and require the corresponding frozen
artifacts. Reading or testing these sources does not authorize training or
publication. Raw media, weights, credentials, generated reports, and runtime
logs remain outside Git.

See [the experiment plan](../../../docs/tsr/DETECTOR_NEXT_EXPERIMENT_2026-11-14.md)
and [the completed comparisons](../../../docs/tsr/DETECTOR_BALANCED_AND_MAPILLARY_2026-11-15.md)
for source revisions, limitations, and published results. Unit coverage is under
`tests/tsr/test_sign_only_pilot_*`, `test_balanced_views.py`,
`test_full_pseudo_policy.py`, `test_pseudo_admission.py`,
`test_mixed_detector_manifest.py`, `test_mobile_detector_replay.py`, and
`test_mapillary_*`.
