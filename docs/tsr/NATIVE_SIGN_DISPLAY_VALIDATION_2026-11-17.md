# Native sign display validation, 17 November 2026

Both attached apps were updated in place to marketing version 1.5, build 10106
(Android displays `1.5-debug`). Existing app data and logs were retained.

## Installed Mapillary generations

| Region | Bundle version | Mapillary records |
| --- | --- | ---: |
| Baden-Württemberg | `2026-11-15-v1.5-mapillary-state-azimuth-backfill` | 534,305 |
| Rheinland-Pfalz | `2026-11-17-v1.5-mapillary-last-seen` | 220,407 |
| Nordrhein-Westfalen | `2026-11-17-v1.5-mapillary-last-seen` | 691,484 |

All records have `last_seen_at` and `aligned_direction`. Rheinland-Pfalz was
rebuilt without one missing-date record; Nordrhein-Westfalen without 50.
Older dated records remain in the inventory and are excluded by the runtime
age check. Each installed generation has six manifest/artifact files: all 18
files passed SHA-256 and size verification on Android and a device-to-host
roundtrip verification on iPhone.

Baden-Württemberg is the selected generation on both devices. Both live
dashboards became ready and matched the current road; runtime evidence confirms
the selected version and context SHA-256
`8551d98ea340ed2a1a747cec50f956d45e567b6f9993fdda7b5253bd5675864b`.
The other two regions were installed and checked byte for byte; this rollout
did not include a live drive in those regions.

## Verification

- Both native device builds succeeded and their installed build numbers were
  read back. The iPhone dashboard was viewed through QuickTime.
- The Mapillary regressions passed on iPhone (five tests) and Android (three
  tests); Android inventory runtime tests (68) and SQLite instrumented tests
  (five) also passed. Coverage includes the strict 30° boundary, north wrap,
  absent/invalid metadata, date formats, calendar-year expiry, and retention.
- The Bernbach replay passed 64 scenarios per platform using the real packed
  road data and fixed clocks. Way `966531279` retains base 50 and
  `30 @ (Mo-Fr 06:30-17:30)` in the installed Mapillary generation.
- Before committing, 101 Python tests and five subtests passed across the
  changed bundle tools, attribution generation, metadata audit, and detector
  experiment helpers. Python syntax, JSON, and Git whitespace checks passed.

Machine-local rollout receipts and diagnostic excerpts are under
`output/device-rollout-2026-11-17/`; Bernbach replay evidence is under
`output/bernbach-conditional-2026-11-17/`. Bundles, device logs, media, weights,
and build products are not included in these commits. The runtime reference
policy remains unchanged.
