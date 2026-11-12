"""Build a private survey inventory from fresh raw evidence, then expose fixed WFS views.

Run as ``python -m scripts.inspector.batch_survey_inventory``. A raw source pack
is a hash-bound manifest of report/rays/ranks/mobile collection and intake receipts;
previous groups, inventory snapshots, and GeoPackages are never accepted inputs.
"""
from __future__ import annotations

import argparse
import copy
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

from shapely.geometry import Point, mapping, shape

from scripts.inspector.build_place_sign_review import (
    MAX_PRIVATE_INPUT_BYTES, RoadHeadingIndex, build_document, frozen_sources,
    read_private, read_sequence_ranks,
)
from scripts.inspector.build_city_sign_wfs import features, write_snapshot
from scripts.inspector.survey_scope import METRIC, WGS84, make_scope, project_geometry
from scripts.inspector.sign_wfs_views import create_view

ROOT = Path(__file__).resolve().parents[2]
RAW_NAMES = {"report", "rays", "sequence_ranks", "mobile_collection",
             "panorama_receipt", "normalization_receipt", "mobile_receipt"}
NORMALIZER_WRAPPER = """import importlib.util,json,sys
path,report,output,bbox=sys.argv[1:]
spec=importlib.util.spec_from_file_location('survey_normalizer',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if module.TARGET_BOXES != ((8.36,48.74,8.51,48.88),(8.58,48.81,8.82,49.00)):
    raise ValueError('backend normalizer geographic guard changed')
module.TARGET_BOXES=(tuple(json.loads(bbox)),)
sys.argv=[path,'--input',report,'--output',output,'--allow-forward-phone','--private-panoramax-review']
module.main()
"""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.stat().st_mode & 0o077:
        raise ValueError("private output directory must be owner-only")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def read_json(path):
    return json.loads(read_private(Path(path), MAX_PRIVATE_INPUT_BYTES))


def verify_source_pack(path, scope):
    """Check raw provenance before any grouping, fitting, or file export."""
    manifest = read_json(path)
    if (manifest.get("schema_version") != 1
            or manifest.get("source_kind") != "fresh_management_corpus"
            or manifest.get("no_previous_inventory_input") is not True
            or set(manifest.get("files", {})) != RAW_NAMES):
        raise ValueError("expected a fresh raw source pack; inventory/group snapshots are forbidden")
    files = {}
    for key, entry in manifest["files"].items():
        candidate = Path(entry["path"])
        candidate = candidate if candidate.is_absolute() else Path(path).parent / candidate
        data = read_private(candidate, MAX_PRIVATE_INPUT_BYTES)
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"source pack hash mismatch: {key}")
        files[key] = candidate
    coverage = shape(manifest["canonical_coverage_wgs84"])
    if not project_geometry(coverage).buffer(.02).covers(scope.canonical):
        raise ValueError("raw source pack does not cover the canonical context")
    records, report = frozen_sources(files["rays"], files["report"])
    if (len(report) < 2 or report[-1].get("record_type") != "corpus_complete"
            or report[-1].get("source_rows") != len(report) - 2):
        raise ValueError("raw report is incomplete")
    receipt = read_json(files["panorama_receipt"])
    normalized = read_json(files["normalization_receipt"])
    mobile_receipt = read_json(files["mobile_receipt"])
    ranks = read_json(files["sequence_ranks"])
    if (receipt.get("read_only") is not True or receipt.get("report_role_verified") != "youspeed_report"
            or receipt.get("report", {}).get("sha256") != sha(files["report"])
            or receipt.get("ranks", {}).get("sha256") != sha(files["sequence_ranks"])
            or receipt.get("source_metadata") != report[0]
            or normalized.get("inputs", {}).get("report_sha256") != sha(files["report"])
            or normalized.get("outputs", {}).get("rays_sha256") != sha(files["rays"])
            or normalized.get("outputs", {}).get("ranks_sha256") != sha(files["sequence_ranks"])
            or mobile_receipt.get("status") != "complete"
            or mobile_receipt.get("no_previous_observation_snapshot_used") is not True
            or mobile_receipt.get("output_sha256") != sha(files["mobile_collection"])):
        raise ValueError("fresh raw intake receipts do not bind the supplied artifacts")
    for key in ("corpus_discovery_snapshot_at", "corpus_crop_snapshot_at"):
        if ranks.get(key) != report[0].get(key):
            raise ValueError("report/rank corpus checkpoints differ")
    for key in ("controls_before", "controls_after"):
        if not isinstance(mobile_receipt.get(key), dict):
            raise ValueError("mobile intake is missing current control checks")
    collection = read_json(files["mobile_collection"])
    if "groups" in collection or not all(key in collection for key in ("collection", "rays", "bindings")):
        raise ValueError("expected raw mobile collection, never an inventory snapshot")
    return files, records, report, collection


def scoped_sql(sql, bbox):
    """Replace only the known geographic clause; retain every admission predicate."""
    from scripts.inspector.survey_scope import validate_bbox
    west, south, east, north = validate_bbox(bbox)
    known = """    AND (
      ((i.metadata#>>'{picture,geometry,coordinates,0}')::double precision BETWEEN 8.36 AND 8.51
      AND (i.metadata#>>'{picture,geometry,coordinates,1}')::double precision BETWEEN 48.74 AND 48.88)
      OR
      ((i.metadata#>>'{picture,geometry,coordinates,0}')::double precision BETWEEN 8.58 AND 8.82
      AND (i.metadata#>>'{picture,geometry,coordinates,1}')::double precision BETWEEN 48.81 AND 49.00)
    )"""
    if sql.count(known) != 1:
        raise ValueError("backend report geographic clause changed; refusing broad SQL replacement")
    # Finite validated float literals preserve export_report's single SOURCE
    # parameter contract; no user-controlled SQL text is interpolated.
    replacement = ("    AND ((i.metadata#>>'{picture,geometry,coordinates,0}')::double precision "
                   f"BETWEEN {west!r} AND {east!r}\n"
                   "      AND (i.metadata#>>'{picture,geometry,coordinates,1}')::double precision "
                   f"BETWEEN {south!r} AND {north!r})")
    return sql.replace(known, replacement)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_helper(argv, log):
    with log.open("x") as stream:
        log.chmod(0o600)
        result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=stream, check=False)
    if result.returncode:
        raise ValueError(f"source helper failed; inspect owner-only {log.name}")


def collect_sources(scope, directory, *, backend_root, database_file, db_port, python, assumptions, catalog):
    """Reuse existing report/normalization/mobile adapters under read-only controls."""
    import psycopg
    from psycopg.conninfo import make_conninfo

    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    backend_root = Path(backend_root).resolve()
    exporter_path = backend_root / "scripts/youspeed/query_private_panoramax_rays.py"
    exporter = load_module(exporter_path, "survey_report_exporter")
    # Keep the established exporter unchanged except for the measured tunnel
    # connection timeout. Do not mutate the global psycopg module.
    def connect_report(*args, **kwargs):
        return psycopg.connect(*args, **{**kwargs, "connect_timeout": 20})
    exporter.psycopg = SimpleNamespace(connect=connect_report)
    sql_file = directory / "scoped-panoramax.sql"
    query = scoped_sql(exporter.SQL.read_text(), scope.query_bbox)
    sql_file.write_text(query)
    sql_file.chmod(0o600)
    exporter.SQL = sql_file
    dsn = make_conninfo(read_private(database_file, 8192).decode().strip(), host="127.0.0.1", port=str(db_port))
    report_file = directory / "panoramax-corpus.jsonl"
    ranks_file = directory / "panoramax-sequence-ranks.json"
    started = datetime.now(timezone.utc).isoformat()
    exporter.export_report(dsn, None, report_file)
    with report_file.open() as stream:
        metadata = json.loads(next(stream))
    prefix, separator, _ = query.partition("\nSELECT jsonb_build_object(")
    if not separator:
        raise ValueError("backend report CTE changed")
    rank_sql = prefix + """
SELECT i.picture_id, entry->>'id', entry->'rank'
FROM candidates i CROSS JOIN LATERAL jsonb_array_elements(i.collections) AS entry
ORDER BY entry->>'id', (entry->>'rank')::integer, i.picture_id;
"""
    with psycopg.connect(dsn, connect_timeout=20) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        db.execute("SET LOCAL statement_timeout = '45s'")
        if db.execute("SELECT current_user,session_user,current_setting('transaction_read_only')").fetchone() != ("youspeed_report", "youspeed_report", "on"):
            raise ValueError("read-only youspeed_report role required")
        visibility, discovery, crop, read_at = db.execute(
            "SELECT visibility_scope,discovery_snapshot,crop_snapshot,transaction_timestamp() FROM youspeed.panoramax_sources WHERE source_id=%s",
            (exporter.SOURCE,)).fetchone()
        for key, value in (("corpus_discovery_snapshot_at", discovery), ("corpus_crop_snapshot_at", crop)):
            if (value.isoformat() if value else None) != metadata[key]:
                raise ValueError("corpus checkpoint changed between report and rank reads; collect again")
        frames = [{"sequence_id": sequence, "image_id": str(image), "rank": rank}
                  for image, sequence, rank in db.execute(rank_sql, (exporter.SOURCE,))
                  if sequence and type(rank) is int and rank >= 0]
    save(ranks_file, {"schema_version": 1, "source_id": exporter.SOURCE, "frames": frames,
                     "corpus_read_at": read_at.isoformat(),
                     **{key: metadata[key] for key in ("corpus_discovery_snapshot_at", "corpus_crop_snapshot_at")}})
    read_sequence_ranks(ranks_file)
    panorama_receipt = directory / "panoramax-read-receipt.json"
    save(panorama_receipt, {"schema_version": 1, "started_at": started,
         "finished_at": datetime.now(timezone.utc).isoformat(), "read_only": True,
         "report_role_verified": "youspeed_report", "source_metadata": metadata,
         "report": {"sha256": sha(report_file)}, "ranks": {"sha256": sha(ranks_file)},
         "query_sha256": sha(sql_file), "rank_query_sha256": hashlib.sha256(rank_sql.encode()).hexdigest(),
         "exporter_sha256": sha(exporter_path), "source_camera_bbox_wgs84": scope.query_bbox,
         "connection_timeout_seconds": 20,
         "limitations": ["Current synchronized management corpus; no new upstream discovery/import.",
                         "Report/ranks use separate repeatable-read transactions with equal corpus checkpoints."]})
    normalizer = backend_root / "scripts/youspeed/panoramax_rays.py"
    rays_file = directory / "panoramax-rays.json"
    run_helper([str(python), "-c", NORMALIZER_WRAPPER, str(normalizer), str(report_file), str(rays_file),
                json.dumps(scope.query_bbox)], directory / "normalizer.log")
    normalization_receipt = directory / "panoramax-normalization-receipt.json"
    save(normalization_receipt, {"normalizer_sha256": sha(normalizer), "inputs": {"report_sha256": sha(report_file)},
         "normalizer_wrapper_sha256": hashlib.sha256(NORMALIZER_WRAPPER.encode()).hexdigest(),
         "source_camera_bbox_wgs84": scope.query_bbox,
         "outputs": {"rays_sha256": sha(rays_file), "ranks_sha256": sha(ranks_file)}})
    # Collector's 'boundary_wgs84' input denotes its SQL geometry only; this
    # scope object is never exported as an official municipality boundary.
    mobile_scope = directory / "mobile-scope.json"
    save(mobile_scope, {"place": {"boundary_wgs84": scope.canonical_wgs84}})
    from inspector.server import CropStore, arguments
    store = CropStore(arguments(["--db-host", "127.0.0.1", "--db-port", str(db_port), "--database-file", str(database_file)]))
    def controls():
        with store.connection() as db:
            store.require_live_controls(db)
            return dict(db.execute("SELECT clock_timestamp()::text AS db_checked_at, watermark,contiguous_sequence FROM youspeed.control_state WHERE singleton").fetchone())
    before = controls()
    mobile_file = directory / "mobile-collection.json"
    collector = ROOT / "scripts/inspector/collect_place_mobile_evidence.py"
    run_helper([str(python), str(collector), "--backend-root", str(backend_root), "--database-file", str(database_file),
                "--db-port", str(db_port), "--review", str(mobile_scope), "--assumptions", str(assumptions),
                "--catalog", str(catalog), "--output", str(mobile_file)], directory / "mobile-collector.log")
    mobile_receipt = directory / "mobile-collection-provenance.json"
    save(mobile_receipt, {"status": "complete", "no_previous_observation_snapshot_used": True,
         "controls_before": before, "controls_after": controls(), "output_sha256": sha(mobile_file),
         "collector_sha256": sha(collector), "assumptions_sha256": sha(assumptions), "catalog_sha256": sha(catalog)})
    files = dict(report=report_file, rays=rays_file, sequence_ranks=ranks_file, mobile_collection=mobile_file,
                 panorama_receipt=panorama_receipt, normalization_receipt=normalization_receipt, mobile_receipt=mobile_receipt)
    pack = directory / "source-pack.json"
    save(pack, {"schema_version": 1, "source_kind": "fresh_management_corpus", "no_previous_inventory_input": True,
                "canonical_coverage_wgs84": scope.canonical_wgs84,
                "files": {key: {"path": str(value), "sha256": sha(value)} for key, value in files.items()}})
    return pack


def assign_jurisdictions(rows, boundary_file):
    """Assign only actual municipality polygons; never use a survey area as AGS."""
    polygons = []
    data = json.loads(Path(boundary_file).read_text())
    for feature in data["features"]:
        properties = feature.get("properties", {})
        if properties.get("kind") != "gemeinde_ags":
            continue
        ags = properties.get("id", "")
        geometry = shape(feature["geometry"])
        if not re.fullmatch(r"\d{8}", ags) or not geometry.is_valid or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError("invalid official jurisdiction boundary")
        polygons.append((ags, project_geometry(geometry)))
    if not polygons:
        raise ValueError("jurisdiction file has no municipality polygons")
    for row in rows:
        point = shape(row["geometry"])
        matches = {ags for ags, polygon in polygons if polygon.covers(point)}
        if len(matches) > 1:
            raise ValueError("ambiguous overlapping municipality boundaries")
        ags = next(iter(matches), None)
        row["properties"].update(gemeinde_ags=ags, kreis_ags=ags[:5] if ags else None)


def refresh_scope_summary(document, export_geometry, feature_count):
    """Describe the selected evidence; retain full-fit counters under an explicit name."""
    from scripts.inspector.apply_sign_review_decisions import effective_pose

    canonical_summary = copy.deepcopy(document.get("summary", {}))
    groups = document["groups"]
    poses = [effective_pose(group) for group in groups]
    positions = Counter(pose["position_status"] if pose else "unresolved" for pose in poses)
    cameras = [observation for group in groups
               for observation in group["observations"] + group.get("follow_on_observations", [])
               if export_geometry.covers(project_geometry(Point(observation["longitude"], observation["latitude"])))]
    document["canonical_summary"] = canonical_summary
    document["summary"] = {
        "source_snapshot_at": canonical_summary.get("source_snapshot_at"),
        "groups": len(groups), "groups_with_proposal": sum(pose is not None for pose in poses),
        "position_status_counts": dict(sorted(positions.items())),
        "groups_with_follow_ons": sum(bool(group.get("follow_on_observations")) for group in groups),
        "follow_on_observations": sum(len(group.get("follow_on_observations", [])) for group in groups),
        "camera_views_in_window": len({row["annotation_id"] for row in cameras}),
        "camera_images_in_window": len({row["image_id"] for row in cameras}),
        "located_wfs_features": feature_count,
        "scope": "Evidence view of the same canonical fit; unlocated groups have no WFS point.",
    }


def build_inventory(scope, source_pack, directory, *, road_graph, id_key_file, name="Survey",
                    road_side="right", review_decisions=None, media_dir=None, jurisdiction_boundaries=None,
                    adapter_root=None):
    adapter_root = Path(adapter_root or ROOT.parent / "Woladen.de-analytics").resolve()
    if not (adapter_root / "scripts/youspeed/panoramax_rays.py").is_file():
        raise ValueError("--adapter-root must contain the existing Panoramax normalization adapters")
    sys.path.insert(0, str(adapter_root))
    files, records, report, collection = verify_source_pack(source_pack, scope)
    directory = Path(directory).resolve()
    if directory.exists():
        raise ValueError("batch output must be a new directory; existing inventories never seed builds")
    roads = RoadHeadingIndex.load(road_graph)
    centroid = shape(scope.canonical_wgs84).centroid
    document = build_document(records, report, roads, read_private(id_key_file, 4096), name=name,
                              center=(centroid.x, centroid.y), scope_geometry=scope.canonical_wgs84,
                              sequence_ranks=read_sequence_ranks(files["sequence_ranks"]), road_side=road_side)
    from scripts.inspector.link_place_mobile_evidence import attach_mobile_evidence, attach_collection_context
    from scripts.inspector.refine_place_sign_pose import attach_refinements
    attach_mobile_evidence(document, collection["rays"], collection["bindings"])
    attach_refinements(document)
    attach_collection_context(document, collection)
    audit_reports = {}
    if review_decisions:
        from scripts.inspector.apply_sign_review_decisions import apply_decisions
        from scripts.inspector.resolve_reviewed_sign_poses import resolve_document
        document, review_report = apply_decisions(document, read_json(review_decisions), media_dir=media_dir)
        audit_reports["review-report.json"] = review_report
        document, pose_report = resolve_document(document, roads=roads)
        audit_reports["pose-report.json"] = pose_report
    directory.mkdir(mode=0o700, parents=True)
    for filename, audit_report in audit_reports.items():
        save(directory / filename, audit_report)
    save(directory / "groups-canonical.json", document)
    export_document = copy.deepcopy(document)
    for group in export_document["groups"]:
        group["sign_code"] = group.get("benchmark_review", {}).get("reviewed_sign_code", group["sign_code"])
    # Geographic geometry clips the canonical rows once. No fabricated AGS is
    # assigned to an arbitrary survey polygon or GPX corridor.
    rows, counts = features(export_document, None, shape(scope.canonical_wgs84), {})
    if jurisdiction_boundaries:
        assign_jurisdictions(rows, jurisdiction_boundaries)
    canonical = directory / "wfs-canonical"
    write_snapshot(canonical, rows)
    selected = sorted(row["properties"]["id"] for row in rows if scope.export.covers(shape(row["geometry"])))
    create_view(canonical, directory / "wfs-area")
    create_view(canonical, directory / "wfs-scope", selected)
    save(directory / "scope-wfs-ids.json", selected)
    evidence_view = copy.deepcopy(document)
    evidence_view["groups"] = [group for group in document["groups"] if group["id"] in selected or any(
        scope.export.covers(project_geometry(Point(observation["longitude"], observation["latitude"])))
        for observation in group["observations"] + group.get("follow_on_observations", []))]
    evidence_view["default_group_id"] = next((group["id"] for group in evidence_view["groups"]), None)
    refresh_scope_summary(evidence_view, scope.export, len(selected))
    save(directory / "groups-scope.json", evidence_view)
    save(directory / "scope.json", scope.as_dict())
    summary = {"schema_version": 1, "canonical_groups": len(document["groups"]), "canonical_features": len(rows),
               "scope_features": len(selected), "export_counts": counts, "one_canonical_fit": True,
               "source_pack_sha256": sha(source_pack), "road_graph_sha256": sha(road_graph),
               "scope": scope.as_dict(), "created_at": datetime.now(timezone.utc).isoformat()}
    if jurisdiction_boundaries:
        summary["jurisdiction_boundaries_sha256"] = sha(jurisdiction_boundaries)
    save(directory / "batch.json", summary)
    return summary


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    scope_args = parser.add_mutually_exclusive_group(required=True)
    scope_args.add_argument("--gpx", type=Path)
    scope_args.add_argument("--bbox", type=float, nargs=4, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    context_args = parser.add_mutually_exclusive_group()
    context_args.add_argument("--context-bbox", type=float, nargs=4, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    context_args.add_argument("--context-geometry", type=Path, help="Exact canonical WGS84 GeoJSON Polygon/MultiPolygon (or Feature)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-pack", type=Path)
    source.add_argument("--backend-root", type=Path, help="Collect fresh raw evidence using these existing backend adapters")
    for name in ("road-graph", "id-key-file", "output-directory"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("database-file", "assumptions", "catalog", "review-decisions", "media-dir", "jurisdiction-boundaries"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--db-port", type=int, default=18780)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--adapter-root", type=Path,
                        help="Existing backend normalization adapters (default: sibling Woladen.de-analytics)")
    parser.add_argument("--name", default="Survey")
    parser.add_argument("--road-side", choices=("left", "right"), default="right")
    args = parser.parse_args()
    scope = make_scope(gpx=args.gpx, bbox=args.bbox, context_bbox=args.context_bbox, context_geometry=args.context_geometry)
    source_pack = args.source_pack
    if args.backend_root:
        if not all((args.database_file, args.assumptions, args.catalog)):
            parser.error("fresh collection requires --database-file, --assumptions, and --catalog")
        source_pack = collect_sources(scope, args.output_directory.resolve().with_name(args.output_directory.name + "-sources"),
            backend_root=args.backend_root, database_file=args.database_file, db_port=args.db_port,
            python=args.python, assumptions=args.assumptions, catalog=args.catalog)
    summary = build_inventory(scope, source_pack, args.output_directory, road_graph=args.road_graph,
        id_key_file=args.id_key_file, name=args.name, road_side=args.road_side,
        review_decisions=args.review_decisions, media_dir=args.media_dir, jurisdiction_boundaries=args.jurisdiction_boundaries,
        adapter_root=args.adapter_root or args.backend_root)
    print(json.dumps({key: summary[key] for key in ("canonical_groups", "canonical_features", "scope_features", "one_canonical_fit")}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Database driver messages may include connection details; expose only
        # a safe error class/SQLSTATE. Non-driver validation errors are local.
        if type(error).__module__.split(".")[0] == "psycopg":
            raise SystemExit(f"Read-only intake failed ({type(error).__name__}, {getattr(error, 'sqlstate', None)}).") from None
        raise
