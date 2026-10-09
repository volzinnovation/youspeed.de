"""Offline geometric road hypotheses; never sign applicability or routing truth.

Coordinates are east/north metres in the solver's explicitly shared local frame.
Distances refer to mapped centre lines, not lane boundaries or sign ownership.
Unknown position/geometry bounds keep candidates ambiguous. No intake, catalog,
runtime matcher, or speed-reference policy is modified by this module.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sqlite3

EARTH_M = 6371008.8
VERSION = "offline-sign-road-association-v1"
DIRECTIONS = {"forward", "reverse", "both", "unknown"}


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2 or not all(map(finite, value)):
        raise ValueError("invalid_coordinate")
    return tuple(map(float, value))


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_bounds(bounds):
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4 or not all(map(finite, bounds)):
        raise ValueError("invalid_wgs84_bounds")
    west, south, east, north = bounds
    if not (-180 <= west < east <= 180 and -70 <= south < north <= 70):
        raise ValueError("invalid_wgs84_bounds")
    return tuple(map(float, bounds))


def local_en(position_lat_lon, origin_lat_lon):
    """Declared local spherical equirectangular transform, not optical heading.

    Inputs are [latitude, longitude]; no dateline/polar or >50 km frame. Both
    crop and road inputs must use this same frame/transform. This function does
    not invent a positional or cartographic accuracy guarantee.
    """
    lat, lon = point(position_lat_lon)
    lat0, lon0 = point(origin_lat_lon)
    if not (-70 <= lat <= 70 and -70 <= lat0 <= 70 and -180 <= lon <= 180 and -180 <= lon0 <= 180):
        raise ValueError("outside_local_projection_domain")
    result = (EARTH_M * math.radians(lon - lon0) * math.cos(math.radians(lat0)),
              EARTH_M * math.radians(lat - lat0))
    if math.hypot(*result) > 50000:
        raise ValueError("local_frame_exceeds_50km")
    return list(result)


def direction_from_tags(tags):
    """Explicit directions only; class defaults/conditional rules stay unknown."""
    if any(k.startswith("oneway:") for k in tags):
        return "unknown"
    value = str(tags.get("oneway", "")).lower()
    return {"yes": "forward", "true": "forward", "1": "forward", "-1": "reverse",
            "no": "both", "false": "both", "0": "both"}.get(value, "unknown")


def segment_projection(location, start, end):
    """Closest point on one consecutive-node segment, with signed left offset."""
    x, y = point(location)
    ax, ay = point(start)
    bx, by = point(end)
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length <= 1e-12:
        return None
    raw = ((x - ax) * dx + (y - ay) * dy) / (length * length)
    fraction = min(1.0, max(0.0, raw))
    projection = [ax + fraction * dx, ay + fraction * dy]
    return {"projection_en_m": projection, "fraction": fraction,
            "unclamped_fraction": raw, "distance_m": math.hypot(x - projection[0], y - projection[1]),
            "signed_left_offset_m": (dx * (y - ay) - dy * (x - ax)) / length,
            "offset_reference": "source_node_order_not_travel_direction",
            "tangent_degrees": math.degrees(math.atan2(dx, dy)) % 360,
            "segment_length_m": length}


def closest_segment(location, vertices):
    if not isinstance(vertices, list) or len(vertices) < 2:
        raise ValueError("road_has_no_segments")
    rows = []
    along = 0.0
    for i, (left, right) in enumerate(zip(vertices, vertices[1:])):
        row = segment_projection(location, left, right)
        if row is None:
            continue
        rows.append({**row, "segment_index": i,
                     "along_way_m": along + row["fraction"] * row["segment_length_m"]})
        along += row["segment_length_m"]
    if not rows:
        raise ValueError("road_has_no_nonzero_segments")
    rows.sort(key=lambda row: (row["distance_m"], row["segment_index"]))
    best = rows[0]
    # At a junction/bend a single arbitrary tangent must not imply direction.
    best["equally_close_segment_indices"] = [r["segment_index"] for r in rows
                                             if abs(r["distance_m"] - best["distance_m"]) <= 1e-7]
    best["tangent_ambiguous"] = any(
        abs((r["tangent_degrees"] - best["tangent_degrees"] + 180) % 360 - 180) > 1e-5
        for r in rows if r["segment_index"] in best["equally_close_segment_indices"])
    return best


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(p, a, b):
    return abs(_cross(a, b, p)) <= 1e-8 and all(min(a[i], b[i]) - 1e-8 <= p[i] <= max(a[i], b[i]) + 1e-8 for i in (0, 1))


def _intersects(a, b, c, d):
    if any((_on_segment(p, x, y)) for p, x, y in ((a, c, d), (b, c, d), (c, a, b), (d, a, b))):
        return True
    return _cross(a, b, c) * _cross(a, b, d) < 0 and _cross(c, d, a) * _cross(c, d, b) < 0


def _inside(p, polygon):
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if _on_segment(p, a, b):
            return True
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return inside


def _point_segment_distance(p, a, b):
    row = segment_projection(p, a, b)
    return row["distance_m"] if row else math.dist(p, a)


def region_road_distance(polygon, vertices):
    """Minimum region-to-polyline distance, including crossing with no vertex inside."""
    if len(polygon) < 3:
        raise ValueError("feasible_region_requires_polygon")
    best = math.inf
    for a, b in zip(vertices, vertices[1:]):
        if _inside(a, polygon) or _inside(b, polygon):
            return 0.0
        for c, d in zip(polygon, polygon[1:] + polygon[:1]):
            if _intersects(a, b, c, d):
                return 0.0
            best = min(best, _point_segment_distance(a, c, d), _point_segment_distance(b, c, d),
                       _point_segment_distance(c, a, b), _point_segment_distance(d, a, b))
    return best


def _directed_nodes(road, traversal=None):
    nodes = road.get("node_ids")
    if not nodes or len(nodes) != len(road["points_en_m"]):
        return None
    direction = traversal or road.get("direction", "unknown")
    if direction not in DIRECTIONS:
        raise ValueError("invalid_path_direction")
    if direction == "unknown":
        return None
    forward = list(zip(nodes, nodes[1:]))
    return forward if direction == "forward" else [(b, a) for a, b in forward] if direction == "reverse" else forward + [(b, a) for a, b in forward]


def _path_relation(road, graph, travelled_path):
    unknown = {"relation": "unknown", "direction_compatibility": "unknown", "shared_node_ids": []}
    if not travelled_path or travelled_path.get("source_sha256") != graph["source"]["sha256"]:
        return {**unknown, "reason": "travelled_path_missing_or_map_mismatch"}
    ids = travelled_path.get("way_ids", [])
    directions = travelled_path.get("direction_by_way", {})
    if road["way_id"] in ids:
        travel = directions.get(road["way_id"], "unknown")
        legal = road.get("direction", "unknown")
        compatible = "unknown" if travel not in {"forward", "reverse"} or legal == "unknown" else "compatible" if legal in {travel, "both"} else "opposite_explicit_direction"
        return {**unknown, "relation": "same_mapped_way", "direction_compatibility": compatible,
                "reason": "way_identity_is_not_sign_applicability"}
    if graph["source"].get("topology") != "original_osm_node_ids":
        return {**unknown, "reason": "original_node_topology_unavailable"}
    roads_by_id = {r["way_id"]: r for r in graph["roads"]}
    shared, reachable, unresolved = set(), set(), False
    candidate_edges = _directed_nodes(road)
    for identity in ids:
        path_road = roads_by_id.get(identity)
        if path_road is None:
            unresolved = True
            continue
        common = set(road.get("node_ids", [])) & set(path_road.get("node_ids", []))
        shared.update(common)
        traversal = directions.get(identity, "unknown")
        legal = path_road.get("direction", "unknown")
        path_edges = _directed_nodes(path_road, traversal)
        if traversal not in {"forward", "reverse"} or legal == "unknown" or legal not in {traversal, "both"}:
            path_edges = None
        if common and (path_edges is None or candidate_edges is None):
            unresolved = True
        if path_edges is not None and candidate_edges is not None:
            reachable.update({b for a, b in path_edges} & {a for a, b in candidate_edges} & common)
    if reachable:
        return {"relation": "directed_adjacent_candidate", "direction_compatibility": "compatible",
                "shared_node_ids": sorted(reachable), "reason": "adjacency_only_restrictions_and_path_timing_unverified"}
    if shared:
        return {"relation": "node_adjacent_direction_unknown" if unresolved else "node_adjacent_not_forward_reachable",
                "direction_compatibility": "unknown" if unresolved else "incompatible_at_shared_node",
                "shared_node_ids": sorted(shared), "reason": "no_sign_governing_road_proof"}
    return {**unknown, "relation": "no_direct_shared_node" if not unresolved else "unknown",
            "reason": "not_a_multihop_reachability_or_disconnection_proof"}


def associate_roads(solver_result, graph, travelled_path=None, search_radius_m=50.0):
    if not finite(search_radius_m) or not 0 <= search_radius_m <= 2000:
        raise ValueError("invalid_search_radius")
    frame = solver_result.get("local_frame")
    if not frame or frame != graph.get("local_frame") or frame.get("axes") != "east_north" or frame.get("units") != "metres":
        raise ValueError("local_frame_mismatch")
    region = solver_result.get("feasible_region") or {}
    polygon = [point(p) for p in region.get("vertices_en_m", [])]
    if len(polygon) >= 3:
        turns = [_cross(a, b, c) for a, b, c in zip(polygon, polygon[1:] + polygon[:1], polygon[2:] + polygon[:2])]
        if any(t > 1e-8 for t in turns) and any(t < -1e-8 for t in turns):
            raise ValueError("feasible_region_must_be_convex")
    nonzero_area = len(polygon) >= 3 and abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(polygon, polygon[1:] + polygon[:1]))) > 1e-8
    estimate = solver_result.get("estimate_en_m")
    if estimate is not None:
        estimate = point(estimate)
    bounded = region.get("bounds_known") is True and region.get("range_clipped") is False and nonzero_area
    if estimate is None and polygon:
        estimate = (sum(p[0] for p in polygon) / len(polygon), sum(p[1] for p in polygon) / len(polygon))
    ids, rows = set(), []
    for road in graph["roads"]:
        identity = road.get("way_id")
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("invalid_or_duplicate_way_identity")
        ids.add(identity)
        if road.get("direction", "unknown") not in DIRECTIONS:
            raise ValueError("invalid_direction")
        vertices = [point(p) for p in road["points_en_m"]]
        if len(vertices) < 2 or not any(a != b for a, b in zip(vertices, vertices[1:])):
            raise ValueError("road_has_no_nonzero_segments")
        error = road.get("geometry_error_bound_m")
        valid_error = finite(error) and error >= 0
        geometry_bounded = graph["source"].get("geometry_bounds_known") is True and valid_error
        if error is not None and not valid_error:
            raise ValueError("invalid_geometry_error_bound")
        separation = region_road_distance(polygon, vertices) if len(polygon) >= 3 else None
        # Unknown bounds never silently filter a supplied candidate road.
        excluded = bounded and geometry_bounded and separation > search_radius_m + error
        nominal = closest_segment(estimate, vertices) if estimate is not None else None
        direction = road.get("direction", "unknown")
        headings = [] if nominal is None or nominal["tangent_ambiguous"] or direction == "unknown" else (
            [nominal["tangent_degrees"]] if direction == "forward" else
            [(nominal["tangent_degrees"] + 180) % 360] if direction == "reverse" else
            [nominal["tangent_degrees"], (nominal["tangent_degrees"] + 180) % 360])
        rows.append({"way_id": identity, "nominal_projection": nominal,
                     "region_distance_m": separation, "geometry_error_bound_m": error,
                     "direction": direction, "permitted_local_headings_degrees": headings,
                     "candidate": not excluded,
                     "candidate_reason": "outside_bounded_search_buffer" if excluded else "uncertainty_bounds_unknown" if not (bounded and geometry_bounded) else "intersects_bounded_search_buffer",
                     "travelled_path": _path_relation(road, graph, travelled_path),
                     "highway": road.get("tags", {}).get("highway")})
    rows.sort(key=lambda r: (r["nominal_projection"]["distance_m"] if r["nominal_projection"] else math.inf, r["way_id"]))
    candidates = [r["way_id"] for r in rows if r["candidate"]]
    return {"schema_version": 1, "algorithm_version": VERSION, "local_frame": frame,
            "map_source": graph["source"], "search_radius_m": search_radius_m,
            "extraction_scope": graph.get("extraction"),
            # Enumeration rectangles are preserved, but this function has not
            # proved they cover the entire feasible region plus search buffer.
            "candidate_population_complete_for_region": False,
            "candidate_population_scope": "supplied_roads_only_query_footprint_containment_not_proved",
            "candidate_way_ids": candidates, "roads": rows,
            "status": "uncertainty_unbounded" if not bounded or graph["source"].get("geometry_bounds_known") is not True or any(r["geometry_error_bound_m"] is None for r in rows) else "multiple_enumerated_candidates" if len(candidates) > 1 else "one_enumerated_candidate" if candidates else "no_enumerated_candidate_in_buffer",
            "proves_applicability": False, "acceptance_eligible": False,
            "limitations": ["Mapped road proximity and directed adjacency do not establish sign ownership or legal applicability.",
                            "Candidate completeness is limited to the declared graph extraction bounds/classes.",
                            "Position and road-source bounds are assumptions, not measured accuracy or statistical confidence."]}


def load_candidate_roads_sqlite(database, bounds_wgs84, expected_sha256, max_ways=10000):
    """Read-only legacy bundle adapter; preserves explicitly degraded capability."""
    west, south, east, north = validate_bounds(bounds_wgs84)
    path = Path(database).resolve()
    if sha256(path) != expected_sha256:
        raise ValueError("bundle_hash_mismatch")
    if type(max_ways) is not int or not 1 <= max_ways <= 100000:
        raise ValueError("invalid_way_cap")
    with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as conn:
        rows = conn.execute("""SELECT w.way_id,w.highway,g.points_json,w.ref,w.street_name
            FROM ways_rtree r JOIN ways w USING(way_id) JOIN way_geom g USING(way_id)
            WHERE r.min_lon<=? AND r.max_lon>=? AND r.min_lat<=? AND r.max_lat>=?
            ORDER BY w.way_id LIMIT ?""", (east, west, north, south, max_ways + 1)).fetchall()
    if len(rows) > max_ways:
        raise ValueError("candidate_way_cap_exceeded")
    roads = []
    for identity, highway, geometry, ref, name in rows:
        points = json.loads(geometry)
        for value in points:
            lat, lon = point(value)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("invalid_bundle_coordinate")
        roads.append({"way_id": str(identity), "points_lat_lon": points,
                      "node_ids": None, "direction": "unknown", "geometry_error_bound_m": None,
                      "tags": {"highway": highway, "ref": ref, "name": name}})
    return {"schema_version": 1,
            "source": {"kind": "legacy_bundle_sqlite", "sha256": expected_sha256,
                       "topology": "coordinate_endpoints_only", "geometry_bounds_known": False,
                       "is_as_driven": False, "geometry_policy": "unattested_legacy_geometry"},
            "extraction": {"bounds_wgs84": list(bounds_wgs84), "candidate_complete_within_source_bbox": True,
                           "node_geometry_complete": False, "legal_routing_complete": False},
            "roads": roads}


def project_graph(graph_wgs84, origin_lat_lon, local_frame):
    """Project map and crop fixes with the exact same declared transform."""
    roads = []
    for road in graph_wgs84["roads"]:
        roads.append({**road, "points_en_m": [local_en(p, origin_lat_lon) for p in road["points_lat_lon"]]})
    return {**graph_wgs84, "local_frame": local_frame,
            "projection": {"method": "spherical_local_en_v1", "earth_radius_m": EARTH_M,
                           "origin_lat_lon": list(origin_lat_lon), "accuracy_truth": False}, "roads": roads}
