# Local Corrections Strategy (Editor Export Workflow)

This document defines the simplified implementation strategy: the app prepares change files for JOSM and Merkaartor (Mercatoor), and users upload from those editors with their own OSM accounts.

## Scope
- Keep driving-safe local correction capture.
- Keep local-first inference improvement.
- No direct app upload to OSM API.
- Export editor-ready files (`.osc`) plus context metadata.

## 1) Product Constraints

- No upload while driving.
- Runtime usage remains account-free.
- Publication is explicit and user-driven in JOSM/Merkaartor.

## 2) Driving-Safe UI

Capture lanes:
1. `Voice command` while driving.
2. `Lock current speed` quick action fallback.
3. `Post-drive review` inbox.

Post-drive review is mandatory before export.

## 3) Local Data and State

Core fields:
- `observation_id`
- `modality`
- `intent_type`
- `value`
- `lat`, `lon`, `heading_deg`
- `road_candidate_ids`
- `city_context`, `street_context`
- `captured_at`
- `confidence_calibrated`
- `source_version`
- `state`

State machine:
- `local_only`
- `needs_review`
- `approved_for_export`
- `exported_osc`
- `editor_imported` (optional user confirmation)
- `uploaded_to_osm` (optional user confirmation)
- `discarded`

Local stores:
- `local_observation_store`
- `local_overlay_cache`
- `osm_editor_export_outbox`

## 4) Local Priority Rules (Inference)

Inference order:
1. User explicit override.
2. Active local overlay.
3. Baseline `maxspeed` in local DB.
4. Rule fallback (city/rural dependent).

Overlay activation requires map-match confidence, non-expired evidence, and no stronger contradiction.

## 5) Export Workflow (No Direct Upload)

## 5.1 Candidate generation

For each approved observation:
- map-match to target OSM object(s),
- build minimal tag diff proposal,
- attach evidence context.

## 5.2 File generation

Export package includes:
- `changes.osc` (OsmChange XML diff),
- `review.json` (context, confidence, source trace),
- `README.txt` (import steps for JOSM/Merkaartor).

## 5.3 User publication path

1. User opens `changes.osc` in JOSM or Merkaartor.
2. User reviews and optionally edits.
3. User uploads with their own OSM account.
4. User optionally pastes back changeset ID for local traceability.

## 6) Synchronization Strategy

- No private backend write authority is required for OSM publication.
- Convergence comes from later OSM-derived snapshot/diff ingestion.
- Local overlays are retired when upstream baseline reflects the edit.

Optional backend remains non-authoritative:
- artifact delivery,
- diagnostics,
- analytics.

## 7) Safety and Policy Rules

1. Never auto-publish from app.
2. Never publish while driving.
3. Require explicit post-drive review before export.
4. Keep full local audit trail: observation -> exported package -> optional changeset ID.

## 8) Minimal Module Slice

- `captureVoiceCommand(...)`
- `lockCurrentSpeed(...)`
- `buildOsmProposal(observation_id)`
- `reviewAndApproveProposal(...)`
- `exportProposalAsOscPackage(...)`

## 9) Rollout Plan

1. `Capture-only`
2. `Review mode`
3. `Editor export beta`
4. `General availability`

## 10) Metrics

- Capture success rate.
- Review acceptance rate.
- Export success rate.
- Editor import success rate (user-reported).
- Time from capture to export.
- Local overlay retirement rate after upstream baseline refresh.
