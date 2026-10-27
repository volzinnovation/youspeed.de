#!/usr/bin/env python3
"""Build a full-region, reference-complete spatial comparator PBF.

Select every canonical admitted way by exact OSM ID and every generic speed
node by exact OSM ID. Pyosmium BackReferenceWriter pulls all referenced way nodes
from the original PBF with original IDs, coordinates and tags. This is a spatial
candidate index: app rules, boundary evidence and certified connectivity remain
in the common canonical sidecar, and are included in reported bundle cost.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import osmium


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class Select(osmium.SimpleHandler):
    def __init__(self, writer, way_ids, node_ids):
        super().__init__()
        self.writer, self.way_ids, self.node_ids = writer, way_ids, node_ids
        self.ways = self.nodes = 0

    def node(self, node):
        if node.id in self.node_ids:
            self.writer.add_node(node)
            self.nodes += 1

    def way(self, way):
        if way.id in self.way_ids:
            self.writer.add_way(way)
            self.ways += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pbf", type=Path, required=True)
    ap.add_argument("--source-sqlite", type=Path, required=True)
    ap.add_argument("--source-nodes", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    started = time.monotonic()
    source_nodes = json.loads(args.source_nodes.read_text())
    source_sha = sha256(args.pbf)
    if source_sha != source_nodes["source_pbf_sha256"]:
        raise RuntimeError("PBF differs from the generic node source snapshot")
    db = sqlite3.connect("file:" + str(args.source_sqlite.resolve()) + "?mode=ro", uri=True)
    way_ids = {row[0] for row in db.execute("SELECT way_id FROM way_geom")}
    node_ids = {node["osm_node_id"] for node in source_nodes["nodes"]}
    # remove_tags=False preserves original tag bytes on referenced road nodes.
    # No parent relations are inferred; they remain in the common semantic pack.
    with osmium.BackReferenceWriter(str(args.output), str(args.pbf),
                                   remove_tags=False) as writer:
        selected = Select(writer, way_ids, node_ids)
        selected.apply_file(str(args.pbf), locations=False,
                            filters=[osmium.filter.EmptyTagFilter()])
        if selected.ways != len(way_ids) or selected.nodes != len(node_ids):
            raise RuntimeError("Not every requested source ID was found in PBF")
    report = {"schema": "youspeed.geodesk-runtime-spatial-pbf.v1",
              "source_pbf_sha256": source_sha, "source_way_count": len(way_ids),
              "source_generic_node_count": len(node_ids),
              "output_bytes": args.output.stat().st_size,
              "output_sha256": sha256(args.output),
              "elapsed_seconds": time.monotonic() - started,
              "scope": "All canonical roads and generic speed nodes across BW, with all original referenced way-node IDs/coordinates/tags. App-specific rules, boundaries and certified adjacency remain in the counted common semantic sidecar."}
    args.output.with_suffix(".manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
