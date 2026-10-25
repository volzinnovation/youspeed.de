# Documentation

This directory contains the public technical documentation for YouSpeed.

Historical links into `../output/` refer to local build and device evidence.
That directory was removed at the owner's request on 24 October 2026 to reclaim
disk space and is excluded from Git. The summaries and receipts in `docs/` and
the lightweight bundle metadata remain available.

- [`V1_5_DEVICE_INSTALL_10067_2026-10-25.md`](V1_5_DEVICE_INSTALL_10067_2026-10-25.md): build 10067 installation and physical checks on both phones, retained Android history and owner-confirmed iPhone journal deletion
- [`IPHONE_TRIP_AND_REFERENCE_REVIEW_2026-10-25.md`](IPHONE_TRIP_AND_REFERENCE_REVIEW_2026-10-25.md): persistent odometer entry after Stop, stored history metadata and owner-approved shared reference policy 1.2.0
- [`TURNAROUND_FIX_AND_TRIP_STOP_2026-10-24.md`](TURNAROUND_FIX_AND_TRIP_STOP_2026-10-24.md): historical build 10066 turnaround, camera/preview and selected-map repairs, plus the odometer flow superseded by build 10067
- [`TURNAROUND_DEVICE_LOG_REVIEW_2026-10-24.md`](TURNAROUND_DEVICE_LOG_REVIEW_2026-10-24.md): shared stale camera limit after turnaround, preview/map evidence and saved-trip diagnosis
- [`CITY_ENTRY_PRE_DRIVE_CHECK_2026-10-24.md`](CITY_ENTRY_PRE_DRIVE_CHECK_2026-10-24.md): city-entry 50 km/h previews checked against real bundle examples on both native readers, active phone maps and physical Android button follow-up
- [`FAHRTENBUCH_BUTTON_STATE_2026-10-24.md`](FAHRTENBUCH_BUTTON_STATE_2026-10-24.md): recording-off strike-through matching Panoramax, live recording-state updates and build 10065 verification
- [`V1_5_BUILD_10064_2026-10-24.md`](V1_5_BUILD_10064_2026-10-24.md): final device builds, optional Fahrtenbuch setup and disabled-status shortcut, derived town-entry previews, conditional map, verification and cleanup
- [`CONDITIONAL_RESTRICTIONS_2026-10-24.md`](CONDITIONAL_RESTRICTIONS_2026-10-24.md): OSM/camera restriction evaluation, inactive time windows, native OCR evidence and conditional-bundle deployment
- [`FAHRTENBUCH_TABLE_UI_2026-10-23.md`](FAHRTENBUCH_TABLE_UI_2026-10-23.md): five-column trip table, recording choice in normal Settings, optional saved-trip end odometer and white dialogs with X close controls
- [`V1_5_DEVICE_INSTALL_10060_2026-10-23.md`](V1_5_DEVICE_INSTALL_10060_2026-10-23.md): updated v1.5 build 10060 on the attached iPhone/Android, in-place data preservation and parked test scope
- [`V1_5_IMPLEMENTATION_CONTINUATION_2026-10-23.md`](V1_5_IMPLEMENTATION_CONTINUATION_2026-10-23.md): current iPhone/Android Fahrtenbuch, preview, city/source priority, conditional-rule and opt-in roadworks implementation, validation and remaining release gates
- iPhone user guide for regional maps, voice corrections, OSC export, and reviewed OSM uploads:
  [English](USER_GUIDE.md) · [Deutsch](USER_GUIDE_DE.md) · [Français](USER_GUIDE_FR.md) · [Nederlands](USER_GUIDE_NL.md)
- [`MANUAL_ORIENTATION.md`](MANUAL_ORIENTATION.md): shared Android/iPhone mounting settings, landscape layout and dashcam button behavior
- [`UPCOMING_SPEED_LIMIT_SPEC.md`](UPCOMING_SPEED_LIMIT_SPEC.md): lower speed-limit previews within a 30-second speed-dependent window, portrait/landscape placement, passage/departure lifecycle, measured offline lookup cost and topology requirements
- [`UPCOMING_SPEED_LIMIT_ADAPTIVE_HORIZON_2026-10-23.md`](UPCOMING_SPEED_LIMIT_ADAPTIVE_HORIZON_2026-10-23.md): adaptive range implementation, longer BW approach coverage, shared boundary tests and remaining limits on advance notice
- [`UPCOMING_SPEED_LIMIT_IMPLEMENTATION.md`](UPCOMING_SPEED_LIMIT_IMPLEMENTATION.md): native preview integration, shared conformance checks and the separately versioned BW 1.5 lookahead test bundle
- [`UPCOMING_SPEED_LIMIT_PHYSICAL_VALIDATION_2026-10-23.md`](UPCOMING_SPEED_LIMIT_PHYSICAL_VALIDATION_2026-10-23.md): build 10059 device installation, full-bundle measurements and first-drive visibility investigation
- [`UPCOMING_SPEED_LIMIT_NO_PREVIEW_INVESTIGATION_2026-10-23.md`](UPCOMING_SPEED_LIMIT_NO_PREVIEW_INVESTIGATION_2026-10-23.md): complete-controller replay, early main-limit transitions, short approach windows and town-entry coverage behind the first-drive report
- [`MAP_RUNTIME_ENCODING_INVESTIGATION_2026-10-23.md`](MAP_RUNTIME_ENCODING_INVESTIGATION_2026-10-23.md): measured bundle storage, compact encoding samples, alternative map formats and a staged binary runtime recommendation
- [`TILE_SEGMENT_ASSET_SPEC.md`](TILE_SEGMENT_ASSET_SPEC.md): segmented map-asset contract
- [`TILE_ASSET_MIGRATION_PLAN.md`](TILE_ASSET_MIGRATION_PLAN.md): migration notes for the tile format
- [`KARLSRUHE_INCREMENTAL_SEED_ROLLOUT.md`](KARLSRUHE_INCREMENTAL_SEED_ROLLOUT.md): incremental seed-bundle design
- [`VIDEO_TRAFFIC_SIGN_RECOGNITION_YOLO_SPEC.md`](VIDEO_TRAFFIC_SIGN_RECOGNITION_YOLO_SPEC.md): optional traffic-sign recognition design
- [`CONDITIONAL_SPEED_LIMITS_OCR_SPEC.md`](CONDITIONAL_SPEED_LIMITS_OCR_SPEC.md): time-window and wet-road restriction evaluation contract, reference selection, conservative authority gating and iPhone/Android acceptance cases, grounded in public Panoramax OCR annotations
- [`CONDITIONAL_MAXSPEED_BW_MAPPING_SPEC.md`](CONDITIONAL_MAXSPEED_BW_MAPPING_SPEC.md): measured Baden-Württemberg OSM restriction inventory, conditional/mode/direction/lane mappings, core bundle generation and delta/interpreter requirements
- [`YOUSPEED_1_4_SPEC.md`](YOUSPEED_1_4_SPEC.md): version 1.4 app specification for global sign collection, buffered one-way uploads, corrections, capture and future paid/contribution access; paired server specification in `Woladen.de-analytics`
- [`YOUSPEED_1_4_APP_IMPLEMENTATION.md`](YOUSPEED_1_4_APP_IMPLEMENTATION.md): app foundation branch, pinned backend contracts, UUID/consent/queue/crop components, validation and remaining runtime integration
- [`FAHRTENBUCH_SPEC.md`](FAHRTENBUCH_SPEC.md): automatic trip journal with per-trip GPS/TSR logs, app kilometre/usage counters, deletable read-only trips with optional vehicle odometer, track/log exports and direct Panoramax photo/dashcam-session links; includes the German formal-Fahrtenbuch scope limitation
- [`FAHRTENBUCH_IMPLEMENTATION.md`](FAHRTENBUCH_IMPLEMENTATION.md): implemented native history/detail, recording/recovery, private exports, encrypted backup and validation limits
- [`MOBIDATA_BW_ROADWORKS_LIVE_SERVICE_SPEC.md`](MOBIDATA_BW_ROADWORKS_LIVE_SERVICE_SPEC.md): BEMaS source assessment, server caching and ingestion, public API contract, and GPS-based roadworks presentation with iPhone/Android parity
- [`PANORAMAX_CROP_DATABASE_INTEGRATION_SPEC_2026-10-14.md`](PANORAMAX_CROP_DATABASE_INTEGRATION_SPEC_2026-10-14.md): complete Panoramax sign-crop backfill and nightly synchronization, downward-expanded crops, metadata and country-specific reverse class mappings
- [`LANE_DETECTION.md`](LANE_DETECTION.md): optional dashcam lane overlay, camera integration and validation protocol
- [`TSR_LANE_TRAJECTORY_IMPLEMENTATION_2026-09-29.md`](TSR_LANE_TRAJECTORY_IMPLEMENTATION_2026-09-29.md): experimental visual path/trajectory fusion, dashcam diagnostics and live/replay overlays
- [`ROAD_PATH_ANDROID_BENCHMARK.md`](ROAD_PATH_ANDROID_BENCHMARK.md): reproducible Moto g86 component benchmark and limits of its performance claim
- [`release/STORE_RELEASE_CHECKLIST.md`](release/STORE_RELEASE_CHECKLIST.md): public mobile-store release checks

Platform setup and testing instructions live beside each implementation in [`../android/README.md`](../android/README.md) and [`../iphone/SpeedConsumerApp/README.md`](../iphone/SpeedConsumerApp/README.md).

Research notes, paper sources, reviews, CV material, and conference submissions belong in the separate [youspeed.de-paper repository](https://github.com/volzinnovation/youspeed.de-paper).

- [Traffic-sign reference pages](TRAFFIC_SIGN_DOCUMENTATION.md): country catalogues, shared pictograms and four-language spoken names behind Info on both apps.
