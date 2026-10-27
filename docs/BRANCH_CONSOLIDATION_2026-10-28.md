# Active 1.5 development branch consolidation

The product owner requested that ongoing work be consolidated into
`codex/youspeed-v1.5-mobidata-bw` and that both apps remain at marketing version
**1.5**. The branch is now the active checkout. Build numbers continue forward
to **10076**; this does not publish a store release.

## Branch audit and integration

Remote references were refreshed without pruning or deleting branches. The
audit compared commit ancestry and patch equivalence against `origin/main`
(`d0e3f1b3`), rather than commit dates alone. All local and fetched remote branch
tips are ancestors of the consolidated development branch. Source branch names
and the other worktrees were preserved.

| Source | Audited tip | Result |
| --- | --- | --- |
| Packed runtime draft | `01403142` | Merge `7c0b8e27`; includes ten commits beyond the previous dev tip |
| Current main | `d0e3f1b3` | Merge `e0079147`; includes seven commits missing from the dev lineage |
| Lane corpus/semantic guidance | `6659dd0b` | Merge `379dcae8`; retain research tools, semantic hints and native traces |
| Crop review/exit context | `98e359e4` | Merge `b65b1669`; union review, localization and phone-way context with newer capture metadata |
| Driving-photo branch | `692573d3` | Merge `1b25fc37`; retain newer runtime/controls and integrate remaining CI checks |
| Website 1.4/OCR | `e346ca9d` | Merge `9f4ad75d`; patch-equivalent release was already in main; preserve newer shared sign entries |

The other named branches (TSR applicability, F-Droid shrinking, dashcam lanes,
startup review, store marketing, Swiss penalties, Data Manager, Panoramax header,
initial Android, secondary announcements and README roadmap) were already
contained in these histories. The local Data Manager commit was already
explicitly retained by earlier integration history. No additional branch work
remains outside the consolidated branch.

## Conflict decisions

- Preserve the current 20 km/h driving-photo controls, stationary settings gate,
  camera sequencing, deterministic photo-test clock, packed runtime and journal
  behavior when integrating older shutter work.
- Keep camera direction, captured-frame time, crop selection and supplementary
  OCR metadata together with the crop branch's frozen phone road match. The
  existing shared collection schema already contains both sets of fields; its
  lock and manifest hash remain unchanged.
- Keep exact class/device/Panoramax filters alongside crop review, exit-context,
  phone-way and live/legacy filters. Keep both lane and review write endpoints
  in one server dispatcher. Preserve the newer official shared pictogram entry
  in both generated website trees.
- Restore all 48 pre-existing modified/untracked source/report files. Pending
  compact exports, Android Panoramax parity, OSM service frontend and hotspot
  prototype source are retained on the active branch. Local private reports
  and generated evidence remain excluded from commits. A local stash and
  `/private/tmp/youspeed-consolidation-20261027/` preserve recovery snapshots.

## App version and packed compatibility

The authoritative XcodeGen configuration, generated Xcode project and Android
Gradle defaults are 1.5/build10076. The prior device installation of
1.6/build10075 remains an historical event in the compact-export note.

Published packed manifests remain byte-immutable with `min_app_version: 1.6`.
Both already-implemented v4 readers now declare a separate internal reader
compatibility level 1.6. That gate is evaluated for v4 only, independently of
marketing version; strict legacy marketing-version checks and rejection of
future reader requirements (e.g. 1.7) remain. No published bundle, catalog,
publisher threshold or governed speed-reference policy was changed.

## Validation

- Combined Inspector Node suite: 136 passed.
- Inspector backend crops/review/lane HTTP checks: 51 passed.
- Offline sign localization/association/identity and research: 184 passed plus
  eight subtests; lightweight lane contracts/plans: 55 passed plus 49 subtests.
- Shared collection contract: 28 pinned files and native payload limits pass;
  full Swift collection host checks and 20 production Swift capability cases pass.
- Frozen speed-reference policy: 39 scenarios, 171 steps, all 16 transitions and
  five states; country-rule packaging inputs: 12 authoritative countries pass.
- Android full JVM suite: 897 tests, zero failures/errors, one skipped; debug
  APK built successfully and its metadata confirms 1.5-debug/build10076.
- iPhone full app/test compilation succeeded; 72 focused tests passed across
  packed bundles, compact exports, lane geometry, frozen phone-road context and
  driving-photo controls. Four fixture tests skipped in the normal container
  were rerun successfully in the required isolated TestHost; none remains
  untested. The built app metadata confirms 1.5/build10076.
- `git diff --check` and regenerated Xcode project validation pass. All 48
  original local files remain present; only the expected merged/configuration
  files differ from their recovery-snapshot bytes.

Image/ML lane experiments requiring unavailable OpenCV/PyTorch were not run;
three duplicate native-execution cases were omitted from the lightweight
Python lane run while the complete app builds run separately. No live/private
trip data, ML downloads, OSM uploads or server deployments were needed for this
branch consolidation.

This consolidation is local. No push, store publication, branch deletion or
merge into main is performed by this work.
