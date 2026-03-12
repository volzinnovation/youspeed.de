# Karlsruhe Track B Validation 2026-03-12

## Seed lineage

- Candidate launch baseline manifest: `mapdata/bundles/v3/karlsruhe-regbez/latest/karlsruhe-regbez_manifest.json`
- Bundle version: `2026-03-11-shared-node-corridor-hmm`
- Manifest timestamp: `2026-03-11T23:05:15Z`
- Full DB SHA-256: `90b8fa6148f002d2bfcfc4e2f4bcfa32c785fc9979775b8de097a5da049b7a79`
- Inflated bundled seed from `iphone/SpeedConsumerApp/karlsruhe-regbez_speeds.sqlite.zlib` matches the same SHA-256 exactly.

Verification note:
- The older dated snapshot `mapdata/bundles/v3/karlsruhe-regbez/2026-03-11-geomlinks-unlimited/karlsruhe-regbez_speeds.sqlite` differs (`92ad18b408838d632e1050a36117f6030a241f3072d29f912bbc8a218d88a17e`) and is not the current bundled lineage.

## Launch-critical matcher fixes

1. Motorway legal fallback hardening
- Unsigned motorway and motorway-link matches no longer invent a mandatory `130 km/h` limit from inherited or highway-class fallback alone.
- Residential area fallback no longer collapses unsigned motorway matches to generic `100` or `50`.

2. Tunnel continuity hardening
- Shared-ref tunnel portal transitions remain selectable when `way_links` continuity exists but corridor-progress metadata is absent.
- This restores the launch-relevant same-ref surface-to-tunnel handoff at the portal without weakening the stricter corridor-state path when corridor metadata is available.

## Focused validation

Focused iOS regression run on 2026-03-12:
- `xcodebuild test -project iphone/SpeedDBBench.xcodeproj -scheme SpeedConsumer -destination 'platform=iOS Simulator,id=4515E460-ADF8-45DA-86DC-6ACBF322C629' -derivedDataPath /tmp/SpeedConsumerDerivedData-trackb-focused ...`
- Result: `17` selected tests passed, `0` failures.
- Coverage of the focused set:
  - seed bootstrap from bundled resource
  - startup recovery from staging and downloaded cache
  - zlib delta-chain application
  - motorway unlimited and unsigned fallback behavior
  - tunnel entry rejection, promotion, persistence, and same-ref continuity

Artifacts:
- Test result bundle: `/tmp/SpeedConsumerDerivedData-trackb-focused/Logs/Test/Test-SpeedConsumer-2026.03.12_13-39-56-+0100.xcresult`

## Remaining human decision

- Confirm whether `2026-03-11-shared-node-corridor-hmm` is the accepted Karlsruhe launch baseline. The bundled seed already matches it byte-for-byte.
