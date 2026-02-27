# OSM Editor Export Package Spec v1

Purpose: define the file package produced by the app for import into JOSM/Merkaartor.

## Package format

Single ZIP per export action:
- `changes.osc`
- `review.json`
- `README.txt`

Recommended filename:
- `osm-export-<UTC_ISO8601>-<short_id>.zip`

## 1) `changes.osc`

- Format: OsmChange XML (`<osmChange version="0.6" generator="youspeed-export-v1">`).
- Typical operation: `<modify>` of way tags (`maxspeed`, related speed tags).
- Keep edits minimal: only required tags and targeted objects.

## 2) `review.json`

Required keys:
- `export_id` (UUID)
- `created_at_utc`
- `app_version`
- `data_bundle_version`
- `observation_ids` (array)
- `target_objects` (array of `{type,id}`)
- `street_context`
- `city_context`
- `suggested_changeset_comment`
- `suggested_changeset_source`
- `confidence_summary`

Optional keys:
- `notes`
- `user_acknowledged_risk` (bool)
- `returned_changeset_id`

## 3) `README.txt`

Must include:
- import steps for JOSM,
- import steps for Merkaartor,
- reminder that final upload is performed by user account in editor,
- warning that user is responsible for review before upload.

## Validation rules before export

1. `changes.osc` must parse as XML.
2. Every edited object must appear in `target_objects`.
3. No empty changes (`create/delete/modify` all empty) allowed.
4. File size cap per package (default 5 MB).
5. Default to one logical correction per package.

## Traceability

App stores:
- `export_id`
- package filename and hash
- included `observation_ids`
- optional user-supplied `returned_changeset_id`

This supports later reconciliation when baseline updates are ingested from OSM snapshots/diffs.
