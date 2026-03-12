# Track B: Karlsruhe Seed And Matcher Hardening

Window: `2026-03-12` to `2026-03-23`

Status: active

## Goal

Freeze a fresh Karlsruhe seed baseline, rebuild the bundled seed from it, and close launch-breaking recovery or continuity defects.

## Now

- regenerate the Karlsruhe full bundle and record exact artifact lineage
- rebuild the bundled seed DB from that accepted lineage
- run seed-specific regressions and prioritize failures affecting launch safety

## Next

- validate clean install bootstrap from the bundled seed
- validate full-bundle recovery without requiring `delta_index`
- fix or triage legal fallback, startup recovery, and route-continuity defects

## Human touchpoints

- drive the next field validation route with tunnel and continuity stress cases
- confirm which seed artifact is the accepted baseline for launch

## Outputs

- bundled seed DB in `iphone/SpeedConsumerApp/`
- Karlsruhe validation notes in `docs/`
- any launch-critical matcher fixes in `iphone/SpeedConsumerApp/`

## Exit criteria

- accepted Karlsruhe seed baseline exists
- bundled seed is rebuilt from that exact artifact lineage
- launch-critical seed and matcher failures are either fixed or explicitly cut from scope
