# YouSpeed High-Level Technical Architecture

This diagram captures the system components and data interactions described in `VISION.md`, including offline inference, crowdsourced observations, multi-source sync, and optional OSM feedback.

Detailed policy and UX behavior for local corrections is documented in:
- `paper/share/LOCAL_CORRECTIONS_STRATEGY.md`

Policy update: current implementation targets editor-mediated individual-contributor uploads (JOSM/Merkaartor), not direct app uploads and not centralized backend publishing.

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

1. External baseline data enters through ingestion, is transformed into bundle and delta artifacts, and is published for device sync.
2. The app performs offline inference from baseline runtime data plus a local confidence overlay.
3. Drivers contribute candidate observations through vision and voice; observations are normalized and stored locally first.
4. Candidate observations are synced by device ID (without user accounts) and pass trust, validation, corroboration, and merge steps before entering the global store.
5. Confirmed global intelligence flows back to devices as updates and can optionally be exported upstream to OSM through a moderated contribution path.
