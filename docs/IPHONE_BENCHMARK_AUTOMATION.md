# iPhone Benchmark Automation (Sketch)

This document explains how to run the benchmark sketch on a physical iPhone and automate execution through Xcode command-line tooling.

## 1) Prepare the app

1. Regenerate project (optional, deterministic from spec):
   - `DEVELOPMENT_TEAM=<YOUR_TEAM_ID> ./scripts/iphone/generate_xcode_project.sh`
2. Open:
   - `iphone/SpeedDBBench.xcodeproj`
3. Ensure `libsqlite3.tbd` remains linked (already configured by project spec).
4. Optional: replace bundled fixture DB with a larger benchmark DB (same file name `speeds_v4.sqlite` or adjust app code).

## 2) Connect iPhone

1. Connect the device via USB.
2. Enable developer mode on iPhone.
3. Trust this Mac and allow code signing for your team.
4. Get device UDID:
   - `xcrun xctrace list devices`

## 3) Run benchmark automatically

```bash
./scripts/iphone/run_device_benchmark.sh \
  /Users/raphaelvolz/Github/youspeed.de/iphone/SpeedDBBench.xcodeproj \
  SpeedDBBench \
  <DEVICE_UDID> \
  Release \
  /tmp/speeddbbench
```

Output:
- `.xcresult` bundle for test execution logs.
- extracted `.xcresult.json` for machine parsing.

Behavior:
- The script first tries the physical device destination.
- If signing/provisioning blocks device execution, it automatically falls back to iOS Simulator (`iPhone 16`) and runs `SpeedDBBenchTests`.
- `run mode` is printed at the end (`device` or `simulator`).

## 4) Capture benchmark JSON from app sandbox

The sketch writes benchmark JSON files to app `Documents` as:
- `benchmark_report_<timestamp>.json`

Recommended retrieval options:
- Xcode Devices window -> Download container.
- Add a tiny debug endpoint in-app to share file via Files app / AirDrop.

## 5) Notes on dependencies and updates

- For current v1-v4 probing, only system SQLite is required.
- Runtime SpatiaLite extension loading is not required in this setup.
- For independent map updates, download DB assets with `URLSessionDownloadTask` and atomically move into `Application Support`.
