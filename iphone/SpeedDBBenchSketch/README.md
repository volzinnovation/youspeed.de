# SpeedDBBenchSketch (iPhone)

Minimal SwiftUI benchmark app sketch for running `v1`-`v4` runtime probes directly on an iPhone.

Project included in repo:
- `iphone/SpeedDBBench.xcodeproj`

Regenerate from spec:
```bash
./scripts/iphone/generate_xcode_project.sh
```

With explicit team (recommended for device runs):
```bash
DEVELOPMENT_TEAM=<YOUR_TEAM_ID> ./scripts/iphone/generate_xcode_project.sh
```

## What this sketch covers
- Copying a bundled `.sqlite` asset into writable app storage (`Application Support`).
- Optional remote asset download using `URLSessionDownloadTask`.
- Running repeated SQL benchmark probes against the SQLite DB using `SQLite3`.
- Exporting benchmark JSON to app `Documents` for retrieval.

## Dependencies on iPhone

Required:
- `libsqlite3.tbd` (system library, linked in Xcode).
- Swift module import: `import SQLite3`.

Not required for current benchmark logic:
- Runtime `mod_spatialite` loading.

Reason:
- The benchmark uses standard SQLite + `RTree` + optional `way_tile` tables.
- Variant matrix is executed as:
  - `v1`: bbox scan on `ways`
  - `v2`: tile-prefilter (`way_tile`) + `ways`
  - `v3`: `ways_rtree` + `ways`
  - `v4`: tile-prefilter + `ways_rtree` + `ways`
- Each variant is measured in `bbox`, `hybrid`, and `polyline` modes.

Optional (only if you need full SpatiaLite SQL functions on-device):
- Integrate `libspatialite` build artifacts and dependent geospatial C libs.

## Asset lifecycle recommendation

1. Ship a small seed DB in app bundle for first run (or no seed if download-first).
2. On first launch, copy seed DB from bundle to `Application Support`.
3. For updates, download new DB to a temp URL via `URLSessionDownloadTask`.
4. Atomically move/replace in `Application Support`.
5. Keep old DB as rollback until checksum validation passes.

## Open project in Xcode

1. Open:
   - `iphone/SpeedDBBench.xcodeproj`
2. Select scheme:
   - `SpeedDBBench`
3. Run on device or simulator.

Bundled benchmark DB assets:
- `speeds_v3.sqlite` (baseline SQLite fixture)
- `speeds_v4.sqlite` (fixture with `way_tile` table for full `v1`-`v4` matrix)

## Sources (web research)
- SQLite RTree module: <https://sqlite.org/rtree.html>
- SQLite compile options (including `ENABLE_RTREE`): <https://sqlite.org/compile.html>
- Apple file locations / `Application Support`: <https://developer.apple.com/documentation/foundation/accessing-files-and-directories>
- FileManager API used to resolve app directories: <https://developer.apple.com/documentation/foundation/filemanager/url(for:in:appropriatefor:create:)>
- iOS bundle is not writable (Apple guidance): <https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/FileSystemOverview/FileSystemOverview.html>
- `URLSessionDownloadTask` temporary file handling: <https://developer.apple.com/documentation/foundation/urlsessiondownloadtask>
- In-app background asset download (Apple): <https://developer.apple.com/documentation/backgroundassets/providing-assets-for-background-download-in-your-app>
- App Store Connect background assets upload reference: <https://developer.apple.com/help/app-store-connect/reference/background-assets>
- Geofabrik update cadence reference: <https://download.geofabrik.de/>
