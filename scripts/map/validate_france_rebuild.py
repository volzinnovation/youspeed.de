#!/usr/bin/env python3
"""Validate a rebuilt French regional DB and package, recording branch provenance."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def validate_database(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise ValueError(f"SQLite integrity failure: {integrity[:5]}")
        metadata = dict(db.execute("SELECT key,value FROM metadata"))
        if metadata.get("road_geometry_policy") != "source_vertices_v1":
            raise ValueError("Full source road geometry is required")
        if metadata.get("settlement_country_code") != "FR" or not metadata.get("settlement_context_version"):
            raise ValueError("French settlement context is required")
        tables = ("ways", "ways_rtree", "way_geom", "way_endpoints", "way_links", "settlement_segment")
        counts = {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in tables}
        if not counts['ways'] or any(counts[name] != counts['ways'] for name in ('ways_rtree', 'way_geom', 'way_endpoints')):
            raise ValueError(f"Missing road geometry or search index: {counts}")
        return {"integrity": "ok", "metadata": metadata, "row_counts": counts}


def sha256(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region', required=True)
    parser.add_argument('--bundle-version', required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    db = Path('mapdata/dist-v3') / args.region / 'speeds_v3.sqlite'
    package = Path('mapdata/bundles/v3') / args.region / args.bundle_version
    report = validate_database(db)
    if not (package / 'FRA-rules.json').is_file() or not (package / f'{args.region}_manifest.json').is_file():
        raise ValueError('Missing manifest or French rules')
    report.update({"region": args.region, "bundle_version": args.bundle_version, "source_commit": args.commit,
                   "built_at": datetime.now(timezone.utc).isoformat(),
                   "input_pbf_sha256": sha256(Path('mapdata/raw') / f'{args.region}-latest.osm.pbf'),
                   "files": {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
                             for p in sorted(package.iterdir()) if p.is_file() and p.name != 'build-provenance.json'}})
    (package / 'build-provenance.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({"region": args.region, "commit": args.commit, "row_counts": report['row_counts']}))


if __name__ == '__main__':
    main()
