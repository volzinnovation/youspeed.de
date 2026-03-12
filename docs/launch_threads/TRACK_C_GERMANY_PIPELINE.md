# Track C: Germany Shard Data Pipeline

Window: `2026-03-12` to `2026-04-20`

Status: active

## Goal

Generate and validate the Germany-wide full-bundle shard release set without taking on non-Germany scope before launch.

## Now

- enumerate the Germany shard release tags implied by `BundleTargets.top10.json`
- verify manifest naming, coverage metadata, and multipart DB handling for each shard
- prepare publish and validation runs for full bundles only

## Next

- publish the full-bundle release set for all Germany shards
- validate every manifest against the current app contract
- document any shard-specific exceptions before they surprise Track D

## Human touchpoints

- review shard publish results and storage budget
- decide whether any Germany shard must be cut for launch risk reasons

## Outputs

- Germany shard manifests and bundle assets on GitHub releases
- bundle generation and publish scripts in `scripts/map/`
- validation notes in `docs/`

## Exit criteria

- all Germany shards are published as full-bundle releases
- manifest correctness and coverage metadata are validated
- no non-Germany country work remains on the pre-launch critical path
