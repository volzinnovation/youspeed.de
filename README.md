# youspeed.de

`youspeed.de` contains the consumer apps, shared v3 map-bundle pipeline, replay/benchmark tooling, and the paper artifacts that justify the current matcher/runtime design.

## Current status (March 13, 2026)

- iPhone remains the reference `ConsumerSpeed` implementation.
- Android now lives on `main` as the parallel port, using the same v3 bundle contract, shared seed bundle strategy, matcher/replay harness, and offline local speed-capture workflow.
- Android voice capture no longer depends on Google on-device speech packages. It uses bundled offline Vosk assets plus a DIN-like bundled font for the sign UI.
- The shared map pipeline still builds and publishes v3 SQLite bundles plus delta manifests from this repo.
- Paper and benchmark work stay in-tree, but are separate from app-release work.

## Repository layout

- [android](/Users/raphaelvolz/Github/youspeed.de/android): Android app, Gradle project, emulator/device test helpers
- [iphone](/Users/raphaelvolz/Github/youspeed.de/iphone): iPhone app, benchmark app, Xcode project
- [scripts/map](/Users/raphaelvolz/Github/youspeed.de/scripts/map): bundle builders, query tools, publishing helpers
- [docs/launch_threads](/Users/raphaelvolz/Github/youspeed.de/docs/launch_threads): active launch-track notes
- [inspector](/Users/raphaelvolz/Github/youspeed.de/inspector): matcher/log inspection tooling
- [paper](/Users/raphaelvolz/Github/youspeed.de/paper): ITSC and technical-report sources
- [sites](/Users/raphaelvolz/Github/youspeed.de/sites): web landing page assets

## Shared prerequisites

- `python3`
- `sqlite3`
- `jq`
- Xcode 16+ for the iPhone targets
- Android Studio / SDK + Java 17 for the Android target
- optional: `gh` for embedding a GitHub release read token into local app builds
- optional: `osmium-tool`; the maintained scripts primarily use `pyosmium`

## Android

The Android app is an internal parallel port of the consumer app. Current highlights:

- shared `BundleTargets.top10.json` contract and live GitHub release bootstrap
- Karlsruhe seed bundle bundled into the APK
- offline bundled Vosk German speech recognition for speed capture
- replay regression suite for recorded traces and Karlsruhe matcher windows
- connected-device UI/instrumentation coverage

Quick verification:

```bash
cd android
./gradlew :app:testDebugUnitTest :app:assembleDebug
./gradlew :app:connectedDebugAndroidTest
./scripts/run_replay_regressions.sh
```

Build/install with a GitHub token for live bundle access:

```bash
cd android
export YOUSPEED_RELEASE_READ_TOKEN="$(gh auth token)"
./gradlew :app:assembleDebug :app:installDebug
```

More Android-specific notes live in [android/README.md](/Users/raphaelvolz/Github/youspeed.de/android/README.md) and [TRACK_E_ANDROID_ALPHA.md](/Users/raphaelvolz/Github/youspeed.de/docs/launch_threads/TRACK_E_ANDROID_ALPHA.md).

## iPhone

The iPhone app remains the source implementation for the consumer workflow and matcher behavior.

Useful entry points:

- app source: [iphone/SpeedConsumerApp](/Users/raphaelvolz/Github/youspeed.de/iphone/SpeedConsumerApp)
- app scheme: `SpeedConsumer`
- benchmark scheme: `SpeedDBBench`

Quick verification:

```bash
xcodebuild test \
  -project iphone/SpeedDBBench.xcodeproj \
  -scheme SpeedConsumer \
  -destination 'platform=iOS Simulator,name=iPhone 16'
```

Token-aware local consumer build:

```bash
./scripts/iphone/build_consumer_app.sh --use-gh-token
```

Additional app notes live in [iphone/SpeedConsumerApp/README.md](/Users/raphaelvolz/Github/youspeed.de/iphone/SpeedConsumerApp/README.md).

## Map bundles and release tooling

The shared runtime format is `v3`: SQLite speed DB, regional manifest, optional multipart DB assets, optional delta index/patches, and shared target metadata for top-country rollout.

Core tooling lives under [scripts/map](/Users/raphaelvolz/Github/youspeed.de/scripts/map). The active launch threads for bundle generation, release surface, iPhone launch, and Android rollout are in [docs/launch_threads](/Users/raphaelvolz/Github/youspeed.de/docs/launch_threads).

## Paper and scientific track

The architecture evaluation, benchmark replication, and publication artifacts stay in-tree:

- [paper/itsc2026](/Users/raphaelvolz/Github/youspeed.de/paper/itsc2026)
- [paper/techreport](/Users/raphaelvolz/Github/youspeed.de/paper/techreport)
- [iphone/SpeedDBBenchSketch](/Users/raphaelvolz/Github/youspeed.de/iphone/SpeedDBBenchSketch)

This track should stay reproducible, but it is no longer the main day-to-day release surface.
