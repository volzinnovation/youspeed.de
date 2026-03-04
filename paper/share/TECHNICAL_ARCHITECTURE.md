# YouSpeed High-Level Technical Architecture

This diagram captures the system components and data interactions described in `VISION.md`, including offline inference, crowdsourced observations, multi-source sync, and optional OSM feedback.

Detailed policy and UX behavior for local corrections is documented in:
- `paper/share/LOCAL_CORRECTIONS_STRATEGY.md`

Policy update: current implementation targets editor-mediated individual-contributor uploads (JOSM/Merkaartor), not direct app uploads and not centralized backend publishing.

## Current implementation status (2026-03-04)

- Production app path is local-first and offline-first: v3 bundle lookup, local overrides, editor-mediated export.
- Tunnel handling is per-fix and deterministic (`tunnel=yes` on the matched way toggles tunnel mode).
- In-city classification uses way-class precedence first (`residential`, `service`, `crossing`, `living_street`), then residential polygon containment.
- Country/region bundle routing is done by coverage bbox/poly metadata across downloaded bundles.
- The full cloud observation/corroboration stack in the diagram remains north-star architecture, not the current critical path.

Rendered variants for iteration:
- Full architecture PNG: `paper/share/TECHNICAL_ARCHITECTURE.png`
- Paper-scope PNG (highlighted): `paper/share/TECHNICAL_ARCHITECTURE_PAPER_SCOPE.png`

```mermaid
flowchart LR
  %% External data and publication interfaces
  subgraph EXT["External Systems"]
    OSM_SRC["OpenStreetMap snapshots and diffs"]
    RULES["Regulatory and rule datasets"]
    OSM_API["OSM contribution interface"]
  end

  %% Backend platform
  subgraph CLOUD["YouSpeed Backend Platform"]
    API["Sync and observation API"]
    INGEST["Baseline ingestion pipeline"]
    BUILD["Bundle and delta builder"]
    OBS_IN["Observation intake service"]
    TRUST["Device-ID trust and reputation service"]
    VALIDATE["Spatial and rule validation engine"]
    CONFIRM["Third-party corroboration engine"]
    MERGE["Conflict resolver and merge engine"]
    GLOBAL_DB["Global speed intelligence store"]
    EXPORT["OSM export and moderation queue"]
    RELEASE["Release artifact publisher"]
  end

  %% Device-side system
  subgraph DEVICE["User Device (No Account, Device ID Only)"]
    APP["YouSpeed iOS app shell"]
    LOC["Location and heading sensor input"]
    INFER["Offline inference engine"]
    BASE_DB["Baseline runtime database"]
    LOCAL_SIGNS["Local sign observation store"]
    OVERLAY["Local confidence overlay"]
    CV["On-device computer vision module"]
    VOICE["Voice input and speech recognition module"]
    NORM["Observation normalization layer"]
    QUEUE["Offline sync queue"]
    SYNC["Sync and update manager"]
  end

  %% Baseline data flow
  OSM_SRC --> INGEST
  RULES --> INGEST
  INGEST --> BUILD
  BUILD --> RELEASE
  RELEASE --> API
  API --> SYNC
  SYNC --> BASE_DB
  SYNC --> OVERLAY

  %% Inference path on device
  LOC --> INFER
  BASE_DB --> INFER
  OVERLAY --> INFER
  INFER --> APP

  %% Crowdsourcing capture path
  CV --> NORM
  VOICE --> NORM
  LOC --> NORM
  NORM --> LOCAL_SIGNS
  LOCAL_SIGNS --> OVERLAY
  NORM --> QUEUE
  QUEUE --> SYNC
  SYNC --> API

  %% Backend validation and confirmation
  API --> OBS_IN
  OBS_IN --> TRUST
  OBS_IN --> VALIDATE
  TRUST --> CONFIRM
  VALIDATE --> CONFIRM
  CONFIRM --> MERGE
  MERGE --> GLOBAL_DB
  GLOBAL_DB --> API

  %% Optional write-back loop
  GLOBAL_DB --> EXPORT
  EXPORT --> OSM_API
```

## Interaction Summary

1. Current critical path: external baseline data is packaged into regional v3 bundles and consumed on-device for offline inference.
2. Current critical path: local corrections are captured (voice/lock), reviewed, and exported as `.osc` for user upload in JOSM/Merkaartor.
3. Current critical path: app applies local-first overlay and bundle-based routing, then converges back through daily OSM diff ingestion.
4. Future path: optional device-observation sync, corroboration, and shared global cache layers can be activated once phase gates are met.
