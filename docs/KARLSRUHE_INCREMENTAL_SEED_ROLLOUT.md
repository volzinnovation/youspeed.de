# Karlsruhe Incremental Seed Rollout

Seed-first rollout to validate daily incremental maintenance before enabling the full country list.

## Dedicated Actions

1. `Karlsruhe PBF Diff Update And Release`
- Maintains `karlsruhe-regbez-latest.osm.pbf` in release tag `karlsruhe-regbez-pbf`.
- Downloads full PBF only when no prior snapshot exists.
- Applies Geofabrik daily replication changes from `karlsruhe-regbez-updates`.
- Publishes updated PBF, state, latest diff report, and daily `.osc.gz` delta asset.

2. `Karlsruhe Incremental Bundle Build And Release`
- Consumes maintained PBF snapshot from tag `karlsruhe-regbez-pbf`.
- Builds and validates `speeds_v3.sqlite` bundle only when `changed==1` (or `force_publish=true`).
- Generates SQL patch batches from the daily `.osc.gz` delta (`build_v3_delta_pack.py`).
- Rolls delta index (`roll_v3_delta_index.py`) and publishes full bundle + incrementals to tag `karlsruhe-regbez`.

## Implementation Tasks

1. Seed pipeline hardening
- Verify PBF release assets exist and remain readable across reruns.
- Verify daily `.osc.gz` naming and retention policy.

2. Incremental contract verification
- Enforce `validate_v3_release_regressions.py` before bundle publish.
- Confirm delta index always references existing released delta manifests and patch SQL files.

3. App-update compatibility
- Confirm app sync resolves Karlsruhe manifest and applies latest incremental patch path from index.
- Confirm up-to-date state in UI when bundle version already matches.

4. Scale-out preparation (after seed is stable)
- Parameterize workflows by region/country id.
- Reuse the same two-phase pattern (PBF maintenance + incremental bundle release) for remaining supported targets.
