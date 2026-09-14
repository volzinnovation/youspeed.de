"""Opt-in, source-backed settlement context for the German generation pilot.

Legal road context is independent of numeric limits and municipal labels. Signs
only constrain their explicitly associated way/direction; there is no graph fill.
All original evidence is retained so consumers can explain unknown/conflict states.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
from collections import defaultdict

import osmium
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import substring
from shapely.strtree import STRtree

from settlement_geometry import simplify_polygon

VERSION = "1"
LANDUSES = {"residential", "commercial", "retail", "industrial"}
SIGN_RE = re.compile(r"(?:^|[;,|\s])DE:(310|311)(?=[^0-9]|$)", re.I)
SCHEMA = """
CREATE TABLE settlement_area (
 area_id TEXT PRIMARY KEY, osm_type TEXT NOT NULL, osm_id INTEGER NOT NULL,
 kind TEXT NOT NULL, inside_city INTEGER CHECK(inside_city IN (0,1)), source TEXT NOT NULL,
 confidence TEXT NOT NULL, tags_json TEXT NOT NULL,
 min_lon REAL NOT NULL, min_lat REAL NOT NULL, max_lon REAL NOT NULL, max_lat REAL NOT NULL
);
CREATE TABLE settlement_ring (
 area_id TEXT NOT NULL, ring_index INTEGER NOT NULL, outer_index INTEGER NOT NULL,
 is_hole INTEGER NOT NULL, points_json TEXT NOT NULL,
 PRIMARY KEY(area_id, ring_index)
);
CREATE TABLE settlement_sign (
 sign_id TEXT PRIMARY KEY, osm_type TEXT NOT NULL, osm_id INTEGER NOT NULL,
 sign_code TEXT NOT NULL, inside_city INTEGER CHECK(inside_city IN (0,1)), direction INTEGER NOT NULL,
 way_id INTEGER, lon REAL, lat REAL,
 association TEXT NOT NULL, tags_json TEXT NOT NULL
);
CREATE TABLE settlement_segment (
 segment_id INTEGER PRIMARY KEY, way_id INTEGER NOT NULL, segment_index INTEGER NOT NULL,
 direction INTEGER NOT NULL CHECK(direction IN (-1,0,1)),
 inside_city INTEGER CHECK(inside_city IN (0,1)),
 source TEXT NOT NULL CHECK(source IN ('zone_traffic','maxspeed_type','source_maxspeed','traffic_sign','urban_polygon','landuse','conflict','missing')),
 confidence TEXT NOT NULL CHECK(confidence IN ('high','low','unknown')),
 evidence_json TEXT NOT NULL, points_json TEXT NOT NULL
);
CREATE INDEX idx_settlement_segment_way ON settlement_segment(way_id);
CREATE INDEX idx_settlement_sign_way ON settlement_sign(way_id);
"""


def _inside_city(state):
    return {"inside": 1, "outside": 0}.get(state)


def _json(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _evidence_json(value):
    # Explanatory evidence follows the same single nullable boolean contract.
    def convert(item):
        if isinstance(item, dict):
            return {("inside_city" if k == "state" else k):
                    (_inside_city(v) if k == "state" else convert(v)) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [convert(v) for v in item]
        return item
    return json.dumps(convert(value), separators=(",", ":"), sort_keys=True)


def _state(value):
    return {"de:urban": "inside", "de:rural": "outside"}.get(str(value or "").strip().lower())


def _opposite(state):
    return {"inside": "outside", "outside": "inside"}.get(state, "unknown")


def _signs(tags):
    """Return explicitly directed sign observations; numeric bearings stay raw.

    Forward/backward here means OSM-way direction, not camera heading. A generic
    sign without an explicit OSM-relative direction cannot establish road state.
    """
    directional = []
    for suffix, direction in (("forward", 1), ("backward", -1)):
        raw = tags.get(f"traffic_sign:{suffix}")
        if raw:
            directional.append((suffix, raw, direction))
    raw = tags.get("traffic_sign")
    if raw:
        direction_raw = tags.get("traffic_sign:direction", tags.get("direction", ""))
        direction = {"forward": 1, "backward": -1}.get(str(direction_raw).lower(), 0)
        directional.append(("main", raw, direction))
    out = []
    for suffix, raw, direction in directional:
        codes = sorted(set(SIGN_RE.findall(raw)))
        if not codes:
            if raw.strip().lower() == "city_limit":
                kind = tags.get("city_limit", "both").strip().lower()
                if kind in ("begin", "end"):
                    out.append((suffix, f"city_limit:{kind}", "inside" if kind == "begin" else "outside", direction))
                elif kind == "both" and direction:
                    # OSM's generic city_limit direction names ENTERING traffic.
                    out.extend([(f"{suffix}:begin", "city_limit:begin", "inside", direction),
                                (f"{suffix}:end", "city_limit:end", "outside", -direction)])
                else:
                    out.append((suffix, "city_limit", "unknown", 0))
            continue
        states = {"inside" if code == "310" else "outside" for code in codes}
        state = next(iter(states)) if len(states) == 1 else "unknown"
        out.append((suffix, ";".join(f"DE:{c}" for c in codes), state, direction))
    return out


def typed_evidence(tags, direction):
    out = []
    suffix = "forward" if direction == 1 else "backward"
    for tag, source in (("zone:traffic", "zone_traffic"), ("maxspeed:type", "maxspeed_type"), ("source:maxspeed", "source_maxspeed"), ("maxspeed", "maxspeed_type")):
        key = f"{tag}:{suffix}" if f"{tag}:{suffix}" in tags else tag
        state = _state(tags.get(key))
        if state is None and source in ("maxspeed_type", "source_maxspeed"):
            # Bare semantic values occur in German legacy tagging. The builder
            # explicitly gates this interpretation to the DE jurisdiction.
            state = {"urban": "inside", "rural": "outside"}.get(str(tags.get(key, "")).strip().lower())
        if state:
            out.append({"source": source, "state": state, "confidence": "high", "tag": key, "value": tags[key]})
    return out


def resolve(evidence):
    high = [item for item in evidence if item["confidence"] == "high"]
    if high:
        states = {item["state"] for item in high}
        if len(states) != 1 or "unknown" in states:
            return "unknown", "conflict", "unknown"
        priorities = {"zone_traffic": 0, "maxspeed_type": 1, "source_maxspeed": 2, "traffic_sign": 3, "urban_polygon": 4}
        chosen = min(high, key=lambda item: priorities.get(item["source"], 9))
        return chosen["state"], chosen["source"], "high"
    if any(item["source"] == "landuse" for item in evidence):
        return "inside", "landuse", "low"
    return "unknown", "missing", "unknown"


class Extractor(osmium.SimpleHandler):
    def __init__(self, conn, tolerance_m):
        super().__init__()
        self.conn = conn
        self.tolerance_m = tolerance_m
        self.signs = []
        self.sign_node_ids = set()
        self.sign_ways = defaultdict(set)
        self.sign_way_endpoints = defaultdict(dict)
        self.area_geometries = []
        self.area_evidence = []
        self.invalid_areas = 0
        self.incomplete_ways = 0
        self.way_count = 0
        conn.execute("CREATE TEMP TABLE settlement_source_way(way_id INTEGER PRIMARY KEY, tags_json TEXT, points_json TEXT)")

    def node(self, node):
        # Most PBF nodes are untagged geometry. Iterating pyosmium TagList to
        # construct dicts for every node is expensive; inspect only the three
        # keys the sign parser consumes before touching locations or raw tags.
        node_tags = node.tags
        if not (node_tags.get("traffic_sign") or node_tags.get("traffic_sign:forward") or node_tags.get("traffic_sign:backward")):
            return
        if not node.location.valid():
            return
        tags = dict(node_tags)
        for suffix, code, state, direction in _signs(tags):
            self.sign_node_ids.add(node.id)
            self.signs.append({"sign_id": f"n:{node.id}:{suffix}", "osm_type": "node", "osm_id": node.id,
                               "sign_code": code, "state": state, "direction": direction,
                               "lon": node.location.lon, "lat": node.location.lat,
                               "tags": tags})

    def way(self, way):
        # Reuse precisely the set of drivable ways admitted to the legacy bundle.
        if not self.conn.execute("SELECT 1 FROM ways WHERE way_id=?", (way.id,)).fetchone():
            return
        nodes = list(way.nodes)
        if len(nodes) < 2 or any(not n.location.valid() for n in nodes):
            self.incomplete_ways += 1
            return
        coords = [[n.location.lon, n.location.lat] for n in nodes]
        tags = dict(way.tags)
        for suffix, code, state, direction in _signs(tags):
            # Way tags contain no physical crossing position. Preserve them for
            # inspection without inventing a sign coordinate or split location.
            self.signs.append({"sign_id": f"w:{way.id}:{suffix}", "osm_type": "way", "osm_id": way.id,
                               "sign_code": code, "state": state, "direction": direction,
                               "lon": None, "lat": None, "tags": tags})
        for index, node in enumerate(nodes):
            if node.ref in self.sign_node_ids:
                self.sign_ways[node.ref].add(way.id)
                if index == 0:
                    self.sign_way_endpoints[node.ref][way.id] = ("start", coords[0], coords[1])
                elif index == len(nodes) - 1:
                    self.sign_way_endpoints[node.ref][way.id] = ("end", coords[-2], coords[-1])
                else:
                    self.sign_way_endpoints[node.ref][way.id] = ("interior", None, None)
        self.conn.execute("INSERT INTO settlement_source_way VALUES(?,?,?)", (way.id, _json(tags), _json(coords)))
        self.way_count += 1
        if self.way_count % 100000 == 0:
            print(f"  settlement source roads captured: {self.way_count}", file=sys.stderr, flush=True)

    def area(self, area):
        tags = dict(area.tags)
        # Municipality membership never establishes urban traffic rules.
        if tags.get("boundary") == "administrative":
            return
        state = _state(tags.get("zone:traffic"))
        if state is None and tags.get("boundary") == "urban":
            state = "inside"
        if state:
            source, confidence, kind = "urban_polygon", "high", "urban_polygon"
        elif tags.get("landuse") in LANDUSES or tags.get("residential") not in (None, "no"):
            state, source, confidence, kind = "inside", "landuse", "low", "landuse"
        else:
            return
        polygons = []
        for outer in area.outer_rings():
            points = [(float(n.lon), float(n.lat)) for n in outer]
            if len(points) < 4:
                continue
            holes = [[(float(n.lon), float(n.lat)) for n in inner] for inner in area.inner_rings(outer)]
            polygons.append(Polygon(points, [ring for ring in holes if len(ring) >= 4]))
        if not polygons:
            return
        original = MultiPolygon(polygons) if len(polygons) > 1 else polygons[0]
        valid = original.is_valid and not original.is_empty
        geometry = simplify_polygon(original, self.tolerance_m) if valid else original
        osm_type = "way" if area.from_way() else "relation"
        area_id = f"{'w' if area.from_way() else 'r'}:{area.orig_id()}"
        self.conn.execute("INSERT INTO settlement_area VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (area_id, osm_type, area.orig_id(), kind, _inside_city(state), source, confidence,
                           _json(tags), *original.bounds))
        parts = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
        ring_index = 0
        for outer_index, polygon in enumerate(parts):
            for is_hole, ring in [(0, polygon.exterior)] + [(1, ring) for ring in polygon.interiors]:
                self.conn.execute("INSERT INTO settlement_ring VALUES(?,?,?,?,?)",
                                  (area_id, ring_index, outer_index, is_hole, _json(list(ring.coords))))
                ring_index += 1
        if valid:
            # Classification and split positions use unsimplified source geometry.
            self.area_geometries.append(original)
            self.area_evidence.append({"area_id": area_id, "source": source, "state": state, "confidence": confidence})
        else:
            self.invalid_areas += 1


def _intersection_distances(line, geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Point":
        return [line.project(geometry)]
    if hasattr(geometry, "geoms"):
        return [distance for part in geometry.geoms for distance in _intersection_distances(line, part)]
    if geometry.geom_type in ("LineString", "LinearRing"):
        return [line.project(Point(geometry.coords[0])), line.project(Point(geometry.coords[-1]))]
    return []


def _sign_evidence(signs, distance, direction):
    directed = [s for s in signs if s["direction"] == direction]
    if not directed:
        return []
    # Only nearest bracketing observations constrain this interval. A repeated or
    # contradictory entry/exit sequence becomes unknown between those signs.
    before = [s for s in directed if s["position"] < distance]
    after = [s for s in directed if s["position"] > distance]
    anchors = []
    if before:
        nearest = max(s["position"] for s in before)
        anchors.extend(s for s in before if abs(s["position"] - nearest) < 1e-12)
    if after:
        nearest = min(s["position"] for s in after)
        anchors.extend(s for s in after if abs(s["position"] - nearest) < 1e-12)
    result = []
    for sign in anchors:
        passed = (distance > sign["position"]) if direction == 1 else (distance < sign["position"])
        state = sign["state"] if passed else _opposite(sign["state"])
        result.append({"source": "traffic_sign", "state": state, "confidence": "high", "sign_id": sign["sign_id"]})
    return result


def _consistent_split_ways(details):
    """Recognize a straight OSM way split, never a branching intersection.

    Exactly two endpoint memberships with consistent OSM direction and a turn
    below 30 degrees provide an unambiguous shared direction for the sign node.
    """
    if len(details) != 2 or {item[0] for item in details.values()} != {"start", "end"}:
        return False
    vectors = []
    for _, a, b in details.values():
        coslat = math.cos(math.radians((a[1] + b[1]) / 2))
        dx, dy = (b[0] - a[0]) * coslat, b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 1e-12:
            return False
        vectors.append((dx / length, dy / length))
    return sum(a * b for a, b in zip(vectors[0], vectors[1])) >= math.cos(math.radians(30))


def build_settlement_context(conn: sqlite3.Connection, input_pbf, country_code="DE", tolerance_m=2.0):
    if country_code != "DE":
        raise ValueError("settlement context v1 supports the DE pilot only")
    if tolerance_m < 0 or not math.isfinite(tolerance_m):
        raise ValueError("settlement geometry tolerance must be finite and nonnegative")
    conn.executescript(SCHEMA)
    extractor = Extractor(conn, tolerance_m)
    print(f"Extracting settlement evidence from original source: {input_pbf}", file=sys.stderr, flush=True)
    extractor.apply_file(str(input_pbf), locations=True)
    print(f"Settlement source extracted: roads={extractor.way_count} valid_areas={len(extractor.area_geometries)} invalid_areas={extractor.invalid_areas} sign_observations={len(extractor.signs)}", file=sys.stderr, flush=True)
    conn.commit()
    sign_by_way = defaultdict(list)
    association_counts = defaultdict(int)
    for sign in extractor.signs:
        if sign["osm_type"] == "way":
            associations = [(sign["osm_id"], "way_tag_location_unknown")]
        else:
            ways = extractor.sign_ways[sign["osm_id"]]
            if len(ways) == 1:
                associations = [(next(iter(ways)), "node_membership")]
            elif len(ways) == 2 and _consistent_split_ways(extractor.sign_way_endpoints[sign["osm_id"]]):
                associations = [(way_id, "collinear_way_split") for way_id in sorted(ways)]
            else:
                associations = [(None, "ambiguous_ways" if ways else "unassociated")]
        for way_id, association in associations:
            if way_id is not None and sign["direction"] == 0 and sign["osm_type"] == "node":
                association = "direction_unknown"
            observation = dict(sign)
            if len(associations) > 1:
                observation["sign_id"] += f":w:{way_id}"
            conn.execute("INSERT INTO settlement_sign VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (observation["sign_id"], sign["osm_type"], sign["osm_id"], sign["sign_code"], _inside_city(sign["state"]), sign["direction"],
                          way_id, sign["lon"], sign["lat"], association, _json(sign["tags"])))
            association_counts[association] += 1
            if association in ("node_membership", "collinear_way_split"):
                sign_by_way[way_id].append(observation)
    tree = STRtree(extractor.area_geometries)
    counts = defaultdict(int)
    segment_count = 0
    zero_length_way_count = 0
    fallback_way_count = 0
    processed_way_count = 0
    for way_id, tags_json, coords_json in conn.execute("SELECT way_id,tags_json,points_json FROM settlement_source_way ORDER BY way_id"):
        processed_way_count += 1
        if processed_way_count % 100000 == 0:
            print(f"  settlement roads classified: {processed_way_count}/{extractor.way_count}; segments={segment_count}", file=sys.stderr, flush=True)
        tags, coords = json.loads(tags_json), json.loads(coords_json)
        line = LineString(coords)
        if line.length == 0:
            zero_length_way_count += 1
            continue
        candidates = [int(index) for index in tree.query(line)]
        cuts = {0.0, line.length}
        for index in candidates:
            cuts.update(_intersection_distances(line, line.intersection(extractor.area_geometries[index].boundary)))
        signs = sign_by_way[way_id]
        for sign in signs:
            sign["position"] = line.project(Point(sign["lon"], sign["lat"]))
            cuts.add(sign["position"])
        cuts = sorted(cuts)
        segment_index = 0
        for start, end in zip(cuts, cuts[1:]):
            if end - start < 1e-12:
                continue
            midpoint = (start + end) / 2
            point = line.interpolate(midpoint)
            area_evidence = [extractor.area_evidence[index] for index in candidates if extractor.area_geometries[index].contains(point)]
            outcomes = []
            for direction in (1, -1):
                evidence = typed_evidence(tags, direction) + _sign_evidence(signs, midpoint, direction) + area_evidence
                outcomes.append((direction, resolve(evidence), evidence))
            if outcomes[0][1] == outcomes[1][1]:
                # Keep directional evidence in the explanation even when states agree.
                evidence = [{"direction": d, "evidence": e} for d, _, e in outcomes]
                outcomes = [(0, outcomes[0][1], evidence)]
            segment = substring(line, start, end)
            points_json = _json([[lat, lon] for lon, lat in segment.coords])
            for direction, outcome, evidence in outcomes:
                if segment_index >= 262144 or way_id >= 2**43:
                    raise ValueError("settlement segment ID exceeds supported OSM way/index range")
                segment_id = way_id * 1048576 + segment_index * 4 + direction + 1
                segment_count += 1
                state, source, confidence = outcome
                conn.execute("INSERT INTO settlement_segment VALUES(?,?,?,?,?,?,?,?,?)",
                             (segment_id, way_id, segment_index, direction, _inside_city(state), source, confidence, _evidence_json(evidence), points_json))
                counts[f"{state}_{confidence}"] += 1
            segment_index += 1
        if way_id % 10000 == 0:
            conn.commit()
    # Any admitted way with unavailable full source geometry receives explicit
    # unknown context using its existing polyline, never an urban guess.
    for way_id, points_json in conn.execute("SELECT w.way_id,COALESCE(g.points_json,'[]') FROM ways w LEFT JOIN way_geom g USING(way_id) LEFT JOIN settlement_segment s USING(way_id) WHERE s.way_id IS NULL"):
        segment_id = way_id * 1048576 + 1
        segment_count += 1
        fallback_way_count += 1
        conn.execute("INSERT INTO settlement_segment VALUES(?,?,0,0,NULL,'missing','unknown',?,?)",
                     (segment_id, way_id, _json([{"reason": "usable_source_geometry_missing"}]), points_json))
        counts["unknown_unknown"] += 1
    conn.execute("DROP TABLE settlement_source_way")
    metadata = {"settlement_context_version": VERSION, "settlement_country_code": country_code,
                "settlement_geometry_tolerance_m": str(tolerance_m), "settlement_segment_count": str(segment_count),
                "settlement_invalid_area_count": str(extractor.invalid_areas),
                "settlement_source_way_count": str(extractor.way_count),
                "settlement_incomplete_way_count": str(extractor.incomplete_ways),
                "settlement_zero_length_way_count": str(zero_length_way_count),
                "settlement_fallback_way_count": str(fallback_way_count),
                "settlement_sign_association_counts": _json(dict(association_counts)),
                "settlement_state_counts": _json(dict(counts))}
    conn.executemany("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)", metadata.items())
    conn.commit()
    return metadata
