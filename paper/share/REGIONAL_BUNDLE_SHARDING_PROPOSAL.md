# Regional Bundle Sharding Proposal (Country PBF > 1 GB)

## Goal
Keep on-device runtime data practical when country-scale PBF input becomes too large, while preserving offline speed-limit inference quality and deterministic updates.

## Trigger rule
- If country PBF size is `<= 1,000,000,000` bytes: build one country bundle.
- If country PBF size is `> 1,000,000,000` bytes: build bundles from Geofabrik child regions (for example German Bundeslaender).

This rule is implemented in:
- `scripts/map/plan_country_region_bundles.py`

## Data-side design
### 1) Sharding plan
- Input: Geofabrik index metadata + country PBF size.
- Output: region list with `pbf_url` and `poly_url`.
- Format: `youspeed.v3.country.bundle.plan`.

### 2) Regional bundle publication
Each region is published as a normal v3 bundle manifest, extended with optional coverage metadata:
- `coverage.bbox` for quick prefilter.
- `coverage.poly` artifact (Geofabrik `.poly` file) for exact containment.

This is implemented in:
- `scripts/map/publish_v3_bundle.py` (`--coverage-poly`)
- `mapdata/spec/v3_bundle_manifest.schema.json` (coverage schema extension)

### 3) Country-level catalog
Optional catalog to list all region manifests for a country:
- Format: `youspeed.v3.bundle.catalog`
- Contains region list, per-region manifest artifact, and coverage summary.

Implemented in:
- `scripts/map/build_v3_country_bundle_catalog.py`
- `mapdata/spec/v3_bundle_catalog.schema.json`

## App-side design
### 1) Multiple local DB bundles supported
- App no longer assumes one bundle directory per version only.
- Internal bundle directories are region-aware (`<region>-<version>`).
- Legacy lookup remains backward compatible for preexisting layout.

### 2) Runtime DB routing by GPS location
- Router scans downloaded bundle manifests with `coverage` metadata.
- Fast prefilter: `coverage.bbox` containment.
- Exact check: point-in-polygon against `.poly` rings.
- If multiple regions match: choose the smallest bbox footprint (more specific coverage).
- If no region matches: keep current DB as fallback.

Implemented in:
- `iphone/SpeedConsumerApp/V3BundleManager.swift` (`resolveLocalBundleRoute(...)`)
- `iphone/SpeedConsumerApp/DriveSessionViewModel.swift` (automatic DB switch before lookup)

### 3) Coexistence policy
- Pruning no longer deletes valid non-active bundles.
- This allows users to keep several downloaded regional bundles locally.

## Update and release strategy
1. Build plan from country size + Geofabrik index.
2. Build and publish regional bundles with `coverage.poly`.
3. Build and publish country catalog (optional but recommended).
4. App sync/download can remain per-manifest; runtime routing chooses correct local DB among downloaded bundles.
5. Existing single-bundle countries remain unchanged.

## Operational tradeoffs
- Pros:
  - lower per-bundle size and download/storage pressure,
  - better practical scaling for large countries,
  - deterministic regional routing fully offline.
- Cons:
  - more release assets,
  - border transitions require robust routing hysteresis (future refinement),
  - delta strategy becomes region-scoped and should be managed per region.

## Recommended next rollout step
Run first real shard rollout for Germany with 2-3 pilot regions (for example Baden-Wuerttemberg, Bayern, Nordrhein-Westfalen) before enabling all Bundeslaender in production release automation.

## Automation extension
- `scripts/map/generate_v3_country_bundles.py` now supports:
  - single-region generation via `--bundle-region <geofabrik-id>`,
  - chained generation for the ranking head via `--top-n 10` (ranking CSV from the technical-report appendix dataset).
- This keeps generation modular for manual region builds and enables batch production for top-coverage countries without hand-editing workflow files.
