# OSM Upload Strategy Assessment (Editor-Mediated Publication)

Date: 2026-02-27

## Decision
Use an editor-mediated publication workflow:
- app exports `.osc` change files,
- user reviews and uploads in JOSM/Merkaartor with their individual OSM account.

No direct app upload to OSM API.

## Rationale

- Matches OSM management guidance: publication by individual contributors.
- Matches established editor behavior: local edit -> explicit review -> user upload.
- Keeps driving UX simple and safe (no auth/upload flow in driving context).
- Avoids building and maintaining direct upload/conflict machinery in-app.

## Implementation Impact

### Keep
- driving-safe capture (voice/lock/review),
- local overlay priority over baseline where confidence supports it,
- local audit trail and evidence packaging.

### Remove from critical path
- app-side direct OAuth upload flow,
- app-managed changeset lifecycle in production path,
- centralized backend publication authority.

### Add
- deterministic `.osc` export,
- editor handoff package (`.osc` + metadata),
- optional return-link field for user-provided changeset ID.

## User Publication Flow

1. Capture correction in app.
2. Review correction post-drive.
3. Export `changes.osc` package.
4. Open in JOSM/Merkaartor.
5. User uploads with own OSM account.
6. Optional: user enters resulting changeset ID in app for traceability.

## Operational Rules

1. Never upload from app while driving.
2. Never auto-publish raw observations.
3. Require review before export.
4. One logical correction per export item by default for auditability.
5. Preserve trace metadata for every export package.

## Sources
- JOSM upload workflow: https://josm.openstreetmap.de/wiki/Help/Action/Upload
- JOSM authentication settings: https://josm.openstreetmap.de/wiki/Help/Preferences/Connection
- Merkaartor documentation: https://wiki.openstreetmap.org/wiki/Merkaartor/Documentation
- Merkaartor 0.20.0 release: https://github.com/openstreetmap/merkaartor/releases/tag/0.20.0
- OSM API v0.6: https://wiki.openstreetmap.org/wiki/API_v0.6
