# Android Alpha Contract

Date: `2026-03-12`

Track E keeps Android real, but narrow. The Android alpha consumes the same launch contract as iPhone and must not introduce a new wire format before the iPhone Germany launch.

## Canonical contract

- bundled target config: `iphone/SpeedConsumerApp/BundleTargets.top10.json`
- iPhone reference models: `iphone/SpeedConsumerApp/ConsumerModels.swift`
- bundle manifest schema: `mapdata/spec/v3_bundle_manifest.schema.json`
- delta manifest schema stays optional for launch safety: `mapdata/spec/v3_delta_manifest.schema.json`

## Android alpha scope

- load the bundled target config without changing country or region identifiers
- derive manifest endpoints with the same `regional_shards` and `single_country` rules as iPhone
- fetch and parse shard manifests that follow `youspeed.v3.bundle.manifest`
- complete full-bundle bootstrap for `db` and `db_parts`
- verify bytes and `sha256` before activation
- persist active bundle metadata so later Android parity can align with iPhone bundle activation

## Shared fixture references

- bundled targets source of truth: `iphone/SpeedConsumerApp/BundleTargets.top10.json`
- current seed reference for Android parity work: `iphone/SpeedConsumerApp/karlsruhe-regbez_speeds.sqlite.zlib`
- current published bundle reference in repo: `mapdata/bundles/v3/karlsruhe-regbez/latest/karlsruhe-regbez_manifest.json`

## Non-goals before iPhone launch

- no Android-specific manifest format
- no Android public release surface
- no requirement that Android release parity be finished by `2026-05-22`
- no contract churn that forces iPhone launch-path rewrites
