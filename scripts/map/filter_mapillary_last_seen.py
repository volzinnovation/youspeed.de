#!/usr/bin/env python3
"""Create a local bundle source containing only dated Mapillary observations."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime
import hashlib
import json
import math
import re
from pathlib import Path
import shutil
import sqlite3


def valid_last_seen(value):
    if type(value) in (int, float):
        return math.isfinite(value) and 0 < value <= 8_640_000_000_000_000
    if not isinstance(value, str):
        return False
    try:
        normalized = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value.replace("Z", "+00:00"))
        parsed = datetime.fromisoformat(normalized)
        return parsed.tzinfo is not None
    except ValueError:
        return False


def filter_source(source: Path, output: Path):
    if output.exists():
        raise ValueError(f"Choose a new output path: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Keep the existing immutable source available to installed generations.
    staging = output.with_name(output.name + ".filtering")
    if staging.exists():
        raise ValueError(f"An interrupted filter exists: {staging}")
    try:
        shutil.copyfile(source, staging)
        with closing(sqlite3.connect(staging)) as db, db:
            db.execute("PRAGMA foreign_keys=ON")
            rejected = []
            for key, raw in db.execute(
                "SELECT record_key,raw_properties_json FROM traffic_sign_inventory WHERE source_id='mapillary-eval' ORDER BY record_key"
            ):
                try:
                    value = json.loads(raw).get("last_seen_at")
                except (AttributeError, ValueError):
                    value = None
                if not valid_last_seen(value):
                    rejected.append(key)
            before = db.execute("SELECT count(*) FROM traffic_sign_inventory WHERE source_id='mapillary-eval'").fetchone()[0]
            if rejected:
                if db.execute("""SELECT count(*) FROM traffic_sign_way_rule r JOIN traffic_sign_runtime s USING(sign_id)
                                 WHERE s.source_id='mapillary-eval'""").fetchone()[0]:
                    raise ValueError("Mapillary source has directed rules; cannot filter as display-only inventory")
                previous = db.execute("SELECT snapshot_sha256 FROM traffic_sign_source WHERE source_id='mapillary-eval'").fetchone()[0]
                snapshot = hashlib.sha256(json.dumps(
                    {"previous_snapshot": previous, "admission": "last_seen_required_v1", "removed_record_keys": rejected},
                    sort_keys=True, separators=(",", ":"),
                ).encode()).hexdigest()
                db.execute("CREATE TEMP TABLE rejected_mapillary(record_key TEXT PRIMARY KEY)")
                db.executemany("INSERT INTO rejected_mapillary VALUES(?)", ((key,) for key in rejected))
                db.execute("""DELETE FROM traffic_sign_association WHERE sign_id IN
                    (SELECT sign_id FROM traffic_sign_runtime WHERE source_id='mapillary-eval'
                     AND record_key IN (SELECT record_key FROM rejected_mapillary))""")
                db.execute("""DELETE FROM traffic_sign_runtime WHERE source_id='mapillary-eval'
                              AND record_key IN (SELECT record_key FROM rejected_mapillary)""")
                db.execute("""DELETE FROM traffic_sign_inventory_rtree WHERE row_id IN
                    (SELECT row_id FROM traffic_sign_inventory WHERE source_id='mapillary-eval'
                     AND record_key IN (SELECT record_key FROM rejected_mapillary))""")
                db.execute("""DELETE FROM traffic_sign_inventory WHERE source_id='mapillary-eval'
                              AND record_key IN (SELECT record_key FROM rejected_mapillary)""")
                db.execute("UPDATE traffic_sign_source SET snapshot_sha256=?,record_count=? WHERE source_id='mapillary-eval'",
                           (snapshot, before - len(rejected)))
                db.execute("UPDATE traffic_sign_runtime SET snapshot_sha256=? WHERE source_id='mapillary-eval'", (snapshot,))
                db.execute("UPDATE traffic_sign_capability SET value=? WHERE key='mapillary_eval_snapshot'", (snapshot,))
                row = db.execute("SELECT value FROM traffic_sign_capability WHERE key='report_json'").fetchone()
                if row:
                    report = json.loads(row[0])
                    report["signs"] = db.execute("SELECT count(*) FROM traffic_sign_runtime").fetchone()[0]
                    report["source_snapshots"]["mapillary-eval"] = snapshot
                    if "inventory_only" in report.get("associations", {}):
                        report["associations"]["inventory_only"] -= len(rejected)
                    db.execute("UPDATE traffic_sign_capability SET value=? WHERE key='report_json'",
                               (json.dumps(report, sort_keys=True, separators=(",", ":")),))
            assert db.execute("PRAGMA foreign_key_check").fetchone() is None
            assert db.execute("PRAGMA quick_check").fetchone() == ("ok",)
        staging.replace(output)
        return {"policy": "last_seen_required_v1", "source": str(source), "output": str(output),
                "mapillary_before": before, "mapillary_retained": before - len(rejected),
                "missing_or_invalid_last_seen_removed": len(rejected),
                "removed_record_keys": rejected}
    except BaseException:
        staging.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    result = filter_source(args.source, args.output)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
