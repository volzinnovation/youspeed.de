# Documentation

This directory contains the public technical documentation for YouSpeed.

- iPhone user guide for regional maps, voice corrections, OSC export, and reviewed OSM uploads:
  [English](USER_GUIDE.md) · [Deutsch](USER_GUIDE_DE.md) · [Français](USER_GUIDE_FR.md) · [Nederlands](USER_GUIDE_NL.md)
- [`MANUAL_ORIENTATION.md`](MANUAL_ORIENTATION.md): shared Android/iPhone mounting settings, landscape layout and dashcam button behavior
- [`TILE_SEGMENT_ASSET_SPEC.md`](TILE_SEGMENT_ASSET_SPEC.md): segmented map-asset contract
- [`TILE_ASSET_MIGRATION_PLAN.md`](TILE_ASSET_MIGRATION_PLAN.md): migration notes for the tile format
- [`KARLSRUHE_INCREMENTAL_SEED_ROLLOUT.md`](KARLSRUHE_INCREMENTAL_SEED_ROLLOUT.md): incremental seed-bundle design
- [`VIDEO_TRAFFIC_SIGN_RECOGNITION_YOLO_SPEC.md`](VIDEO_TRAFFIC_SIGN_RECOGNITION_YOLO_SPEC.md): optional traffic-sign recognition design
- [`YOUSPEED_1_4_SPEC.md`](YOUSPEED_1_4_SPEC.md): version 1.4 app specification for global sign collection, buffered one-way uploads, corrections, capture and future paid/contribution access; paired server specification in `Woladen.de-analytics`
- [`YOUSPEED_1_4_APP_IMPLEMENTATION.md`](YOUSPEED_1_4_APP_IMPLEMENTATION.md): app foundation branch, pinned backend contracts, UUID/consent/queue/crop components, validation and remaining runtime integration
- [`LANE_DETECTION.md`](LANE_DETECTION.md): optional dashcam lane overlay, camera integration and validation protocol
- [`TSR_LANE_TRAJECTORY_IMPLEMENTATION_2026-09-29.md`](TSR_LANE_TRAJECTORY_IMPLEMENTATION_2026-09-29.md): experimental visual path/trajectory fusion, dashcam diagnostics and live/replay overlays
- [`ROAD_PATH_ANDROID_BENCHMARK.md`](ROAD_PATH_ANDROID_BENCHMARK.md): reproducible Moto g86 component benchmark and limits of its performance claim
- [`release/STORE_RELEASE_CHECKLIST.md`](release/STORE_RELEASE_CHECKLIST.md): public mobile-store release checks

Platform setup and testing instructions live beside each implementation in [`../android/README.md`](../android/README.md) and [`../iphone/SpeedConsumerApp/README.md`](../iphone/SpeedConsumerApp/README.md).

Research notes, paper sources, reviews, CV material, and conference submissions belong in the separate [youspeed.de-paper repository](https://github.com/volzinnovation/youspeed.de-paper).

- [Traffic-sign reference pages](TRAFFIC_SIGN_DOCUMENTATION.md): country catalogues, shared pictograms and four-language spoken names behind Info on both apps.
