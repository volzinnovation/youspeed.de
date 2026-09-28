"""Extract bounded, directed OSM context for OFFLINE exit-attribution experiments.

This is not a bundle writer or a legal routing engine. Original OSM node identity
defines connections, including internal way nodes. Missing/conditional direction
remains unknown. Current public OSM is a corrected-context counterfactual, never
silently substituted for the map snapshot recorded during a drive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROAD_CLASSES = {"motorway", "motorway_link", "trunk", "trunk_link", "service"}
TAGS = {"highway", "ref", "name", "oneway", "oneway:conditional", "junction",
        "lanes", "turn:lanes", "maxspeed", "maxspeed:lanes", "bridge", "tunnel", "layer", "access",
        "access:conditional", "service", "destination"}


def extract(data: bytes, *, source_url: str, site_id: str, fetched_at: str) -> dict:
    root = ET.fromstring(data)
    if root.tag != "osm":
        raise ValueError("Expected an OSM XML document")
    points = {n.attrib["id"]: {"id": n.attrib["id"], "latitude": float(n.attrib["lat"]),
                                "longitude": float(n.attrib["lon"])}
              for n in root.findall("node")}
    ways, edges, gaps = [], [], []
    owners: dict[str, set[str]] = {}
    for way in sorted(root.findall("way"), key=lambda w: int(w.attrib["id"])):
        tags = {t.attrib["k"]: t.attrib["v"] for t in way.findall("tag")}
        if tags.get("highway") not in ROAD_CLASSES:
            continue
        identity = way.attrib["id"]
        nodes = [n.attrib["ref"] for n in way.findall("nd")]
        if len(nodes) < 2 or any(n not in points for n in nodes):
            raise ValueError(f"Incomplete geometry for way {identity}")
        record = {"id": identity, "nodeIds": nodes,
                  "version": way.attrib.get("version"),
                  "lastEditedAt": way.attrib.get("timestamp"),
                  "tags": {k: tags[k] for k in sorted(TAGS & tags.keys())}}
        ways.append(record)
        for node in nodes:
            owners.setdefault(node, set()).add(identity)
        direction = tags.get("oneway")
        if "oneway:conditional" in tags:
            gaps.append({"wayId": identity, "reason": "conditional_direction_unresolved"})
            continue
        if direction in {"yes", "true", "1"}:
            orientations = (nodes,)
        elif direction == "-1":
            orientations = (list(reversed(nodes)),)
        elif direction in {"no", "false", "0"}:
            orientations = (nodes, list(reversed(nodes)))
        else:
            gaps.append({"wayId": identity, "reason": "explicit_direction_unavailable"})
            continue
        for oriented in orientations:
            edges.extend({"wayId": identity, "fromNode": left, "toNode": right}
                         for left, right in zip(oriented, oriented[1:]) if left != right)
    connected = []
    for node, ids in sorted(owners.items(), key=lambda row: int(row[0])):
        if len(ids) < 2:
            continue
        incoming = sorted({e["wayId"] for e in edges if e["toNode"] == node}, key=int)
        outgoing = sorted({e["wayId"] for e in edges if e["fromNode"] == node}, key=int)
        connected.append({"osmNodeId": node, "wayIds": sorted(ids, key=int),
                          "incomingWayIds": incoming, "outgoingWayIds": outgoing})
    used = {n for way in ways for n in way["nodeIds"]}
    return {
        "schemaVersion": 1, "siteId": site_id,
        "role": "offline_corrected_topology_counterfactual",
        "source": {"url": source_url, "fetchedAt": fetched_at,
                   "sha256": hashlib.sha256(data).hexdigest(),
                   "license": "ODbL-1.0", "attribution": "OpenStreetMap contributors",
                   "copyrightUrl": "https://www.openstreetmap.org/copyright"},
        "isAsDrivenBundle": False, "provesSignGoverningRoad": False,
        "nodes": [points[n] for n in sorted(used, key=int)], "ways": ways,
        "directedEdges": edges, "connections": connected, "capabilityGaps": gaps,
        "limitations": ["Topological connections do not prove sign applicability or ego lane.",
                        "Turn restrictions and conditional/access legality are not evaluated.",
                        "Missing explicit direction is not inferred from road class.",
                        "Current OSM can differ from imagery and recorded-drive map versions."]}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path)
    p.add_argument("--source-url", required=True)
    p.add_argument("--site-id", required=True)
    p.add_argument("--fetched-at", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = extract(a.input.read_bytes(), source_url=a.source_url,
                     site_id=a.site_id, fetched_at=a.fetched_at)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{a.site_id}: {len(result['ways'])} ways, "
          f"{len(result['connections'])} shared-node connections; offline context only")


if __name__ == "__main__":
    main()
