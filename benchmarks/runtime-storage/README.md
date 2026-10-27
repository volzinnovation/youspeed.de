# Isolated full-BW runtime storage benchmark

The native benchmark compares one storage-query kernel across packed binary,
optimized SQLite and a GeoDesk spatial-query adapter. It does not replace the
production matcher, evaluate the protected speed-reference policy, or install
over the normal driving application.

The iPhone runner uses the separate application identifier
`de.youspeed.StoragePrototypeBenchmark`. It reads a JSON configuration and data
from its own `Documents` directory and atomically writes `report-BACKEND.json`.
Each backend is measured in a fresh process. Android runs the equivalent native
executable from `/data/local/tmp` and keeps its reports/data in that isolated
directory. Device deployment is an explicit part of the requested experiment.

Shared readers/builders are under `shared/runtime-storage-prototype/`; the
GeoDesk adapter is under `shared/runtime-storage-geodesk/`; corrections are
under `shared/runtime-corrections-prototype/`, and the generic speed-sign node
index is under `shared/runtime-sign-nodes-prototype/`.

Configuration fields are `backend`, `directory`, `path`, `queries`, `node_path`,
`node_queries`, `write_road_results` and `repetitions`. Query CSV contains
`lat,lon,radius_m`. No device location, camera,
normal application preferences, trips, or active-map pointer is changed.

First-pass timing is a first application pass over the corpus, not a claim that
the operating system's filesystem caches were purged. Record warm quantiles,
opening time, resident/physical memory and the result digest separately.

The completed two-phone comparison is documented in
`docs/BW_RUNTIME_STORAGE_BENCHMARK_2026-10-26.md`. Device reports, complete
summary, compressed raw road exports and their hashes live in `results/` here;
full-source receipts live in the individual module directories. Large data is
staged in the isolated phone containers. Host build/data caches under
`/private/tmp/youspeed-storage-prototype-20261026/` are temporary and may need
regeneration.

Replay all six backend/device checks without attached phones or build caches:

```sh
python3 benchmarks/runtime-storage/replay_evidence.py
```

One gzip archive per platform retains its three byte-identical backend exports.
Replay checks each archive against every recorded raw SHA-256 and every report
against its saved hash, then reruns the strict full numerical comparison. Both
compressed exports together occupy about 658 KB. Android's recovered exports
also match the original durable receipts, preserving the original timing runs.

## Build the common native runner

Use the official SQLite 3.51.0 amalgamation in both phone builds, with the
source pins and local GeoDesk dependencies from its adapter README. For host:

```sh
cmake -S benchmarks/runtime-storage -B /private/tmp/youspeed-storage-prototype-20261026/phone-host \
  -DCMAKE_BUILD_TYPE=Release \
  -DSQLITE_AMALGAMATION_DIR=/private/tmp/youspeed-storage-prototype-20261026/sqlite/sqlite-amalgamation-3510000 \
  -DGEODESK_SOURCE_DIR=/private/tmp/youspeed-storage-prototype-20261026/geodesk/libgeodesk \
  -DGTL_SOURCE_DIR=/private/tmp/youspeed-storage-prototype-20261026/geodesk/gtl
cmake --build /private/tmp/youspeed-storage-prototype-20261026/phone-host --parallel 4
```

For Android use the same configuration plus the NDK toolchain,
`-DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-34 -DANDROID_STL=c++_static`,
with a separate `phone-android` output directory. This experiment used NDK
30.0.16248370. Stage the executable and five hot data files, common globals,
manifest and corpora under `/data/local/tmp/youspeed-storage-prototype`.

Build the iOS static GeoDesk adapter as described in its README, then use:

```sh
python3 benchmarks/runtime-storage/build_iphone.py \
  --workspace /private/tmp/youspeed-storage-prototype-20261026 \
  --sqlite-source /private/tmp/youspeed-storage-prototype-20261026/sqlite/sqlite-amalgamation-3510000 \
  --geodesk-library /private/tmp/youspeed-storage-prototype-20261026/geodesk/build-ios/libstorage_geodesk.a \
  --team YOUR_DEVELOPMENT_TEAM
```

This requires Xcode and Ruby `xcodeproj` (tested 1.21.0). Install that separate
app with `devicectl`; copy data/configurations into its `Documents/data`.
Configuration paths are relative to that directory. GeoDesk uses a pipe-joined
pair: `bw-runtime.gol|runtime.sqlite` and `bw-runtime.gol|nodes.sqlite`.
The iPhone CSV is named `queries.csv`; the Android copy is `stratified.csv`.

## Run and compare

The runner takes an explicit device identifier and runs each backend in a fresh
process. The iPhone must be physically unlocked. Its per-launch configuration
nonce prevents accepting an old report; no passcode or lock-setting change is
attempted. Road result exports occur outside the timed/memory phases.

```sh
python3 benchmarks/runtime-storage/run_devices.py android --device ANDROID_SERIAL \
  --output /private/tmp/youspeed-storage-prototype-20261026/device-reports
python3 benchmarks/runtime-storage/run_devices.py iphone --device COREDEVICE_ID \
  --output /private/tmp/youspeed-storage-prototype-20261026/device-reports
python3 benchmarks/runtime-storage/compare_reports.py \
  /private/tmp/youspeed-storage-prototype-20261026/device-reports \
  /private/tmp/youspeed-storage-prototype-20261026/complete-sizes.json \
  /private/tmp/youspeed-storage-prototype-20261026/phone-summary.json
```

Use `--platforms android` for an explicitly incomplete one-phone receipt.
Validation requires 6,446 road hits across 586 queries, recomputes each native
road-export digest against its timed run, and checks every exact ID, speed code,
geometry/semantic checksum and numeric projection (absolute tolerance 1e-7).
Within each phone all backend digests must match; cross-platform libm formatting
may differ. Node digests must match the independently verified full corpus.
All correction, disk-reopen and actual-source amendment checks must pass.
Acceptance checks remain enabled under Python optimization.
