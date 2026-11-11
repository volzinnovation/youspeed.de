"""Collect all spatially scoped mobile crop and sighting records for place review."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import time

REVIEW_FIELDS = ("review_revision", "verdict", "corrected_classification", "crop_digest",
                 "observation_sha256", "manifest_sha256")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("backend-root", "database-file", "review", "assumptions", "catalog", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--db-port", type=int, required=True)
    args = parser.parse_args()
    import psycopg
    from psycopg.rows import dict_row

    sys.path.insert(0, str(args.backend_root.resolve()))
    from commercial_backend.youspeed import contracts
    from commercial_backend.youspeed.crop_analysis import live_crop_eligibility
    from scripts.youspeed import mobile_sign_rays as crop, mobile_sighting_rays as sight
    from scripts.youspeed.crop_exit_batch import require_fresh_controls

    review = json.loads(crop.private_file(args.review, 16 * 1024**2))
    shape = json.dumps({"type": "Polygon", "coordinates": [review["place"]["bounds_ring_wgs84"]]})
    profile, taxonomy = crop.load_profile(args.assumptions), crop.load_taxonomy(args.catalog)
    dsn = crop.private_file(args.database_file, 8192).decode().strip()

    # Source admission retains the existing lifecycle conditions. Geometry is
    # checked after collection, including for legacy records and singleton crops.
    crop_sql = crop.SOURCE_SQL.replace(
        " AND e.payload#>>'{event,observer_version}'='sighting-observer-2'\n", ""
    )
    crop_sql = crop_sql.replace("JOIN youspeed.events e ON", "LEFT JOIN youspeed.events e ON")
    crop_sql = crop_sql.replace("  CASE WHEN jsonb_typeof", "  COALESCE(CASE WHEN jsonb_typeof")
    crop_sql = crop_sql.replace("  END,%s))", "  END,e.vehicle),%s))")
    sight_sql = sight.SOURCE_SQL.replace(
        "   AND e.payload#>>'{event,observer_version}'='sighting-observer-2'\n", ""
    )
    start = sight_sql.index(" AND NOT EXISTS (SELECT 1 FROM youspeed.media m")
    end = sight_sql.index("ORDER BY", start)
    sight_sql = sight_sql[:start] + sight_sql[end:]
    if "observer_version" in crop_sql or "observer_version" in sight_sql:
        raise ValueError("source adapter query changed")

    rows, rays, bindings, counts = [], [], {}, Counter()
    with psycopg.connect(
        dsn, host="127.0.0.1", port=args.db_port, user="youspeed_report",
        dbname="youspeed", connect_timeout=8, row_factory=dict_row,
        options="-c default_transaction_read_only=on -c statement_timeout=60000",
    ) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        require_fresh_controls(db, time.time())
        for module, sql, kind in ((crop, crop_sql, "crop"), (sight, sight_sql, "sighting")):
            for row in db.execute(sql, ([shape], 100, None)):
                event, manifest = row["observation"], row.get("manifest")
                ray, reason = module.normalize_row(row, profile, taxonomy, contracts, live_crop_eligibility)
                identifier = crop.key("crop" if manifest else "sighting-event", row["installation"],
                                      row["epoch"], row["crop_id"] if manifest else row["event_id"])
                rows.append({"evidence_id": identifier, "kind": kind, "pose_exclusion": reason,
                             "sighting": event, "crop": manifest})
                counts[kind] += 1
                if not isinstance(event, dict):
                    continue
                binding = {"installation": row["installation"], "epoch": row["epoch"],
                           "event_id": event["event_id"], "event_sha256": crop.digest(event)}
                if manifest:
                    binding.update(crop_id=row["crop_id"], crop_digest=row["digest"],
                                   manifest_sha256=crop.digest(manifest),
                                   review_sha256=crop.digest({key: row.get(key) for key in REVIEW_FIELDS}))
                axis = (manifest or event).get("camera_viewing_direction") or {}
                bindings[identifier] = {
                    "source_binding": binding, "first_seen_at": event.get("first_seen_at"),
                    "last_seen_at": event.get("last_seen_at"), "camera_heading_deg": axis.get("azimuth_degrees"),
                }
                if ray:
                    rays.append(ray)
                    counts[kind + "_with_ray"] += 1
        require_fresh_controls(db, time.time())
    with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump({"collection": rows, "rays": rays, "bindings": bindings, "counts": dict(counts)},
                  stream, ensure_ascii=False, allow_nan=False)
    print(json.dumps(dict(counts), sort_keys=True))


if __name__ == "__main__":
    main()
