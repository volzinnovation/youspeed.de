# Track D: iPhone Germany Launch Path

Window: `2026-03-20` to `2026-05-01`

Status: active

## Goal

Ship an iPhone launch candidate that discovers Germany shards from bundled targets and works safely with full bundles only.

## Now

- remove Karlsruhe-first configuration drift from launch defaults
- confirm bundled Germany shard discovery is the primary path
- keep explicit manifest URL handling as a dev override only

## Next

- validate bundle picker, expected size display, activation, and recovery flows
- validate border-crossing coverage routing across multiple German states
- freeze launch UX and launch-facing copy by `2026-05-01`

## Human touchpoints

- run on-device validation across at least three state-border scenarios
- sign off on launch candidate behavior and UX wording

## Outputs

- iPhone app changes in `iphone/SpeedConsumerApp/`
- test coverage in `iphone/SpeedConsumerApp/SpeedConsumerTests.swift`
- launch notes in `docs/`

## Exit criteria

- bundled Germany targets are the default discovery path
- full-bundle launch flow works without `delta_index`
- launch candidate is stable enough for App Store submission work
