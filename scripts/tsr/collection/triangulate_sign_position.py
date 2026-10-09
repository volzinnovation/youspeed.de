"""Offline, conditional 2-D bearing triangulation; never a sign/road truth label.

Inputs are already projected east/north camera positions and EXPLICIT optical
bearings. This module does not derive bearings from GPS course, choose a camera
FOV, associate physical signs, project GPS coordinates, or establish live-source
eligibility. The caller must supply hash-bound provenance for those operations.
Repeated GPS fixes must be resolved by the caller, not counted as independent
votes. Archive/replay sources are not accepted.

The estimator deterministically enumerates pair intersections, chooses a unique
strict-majority consensus, and refines it with envelope-scaled line least squares.
It is a bounded diagnostic heuristic, not LOST or optimal photogrammetry. Bounds
are declared deterministic assumptions, NOT Gaussian standard deviations. The
feasible polygon is the intersection of outward-offset bearing wedges; it is
conservative conditional on the declared bounds and selected inlier association.
An artificial range box is explicitly reported when it clips this polygon.

Primary background: Henry & Christian (2022), §§2-5,
https://arxiv.org/html/2205.12197v2 ; Chawla et al. (2020), §III,
https://arxiv.org/html/2007.04592 . Both distinguish an optical line of sight
in a known frame from unknown camera orientation/calibration. No accuracy result
from either work is claimed for this planar heuristic.
"""

from __future__ import annotations

from datetime import datetime
from itertools import combinations
import math
import re


ALGORITHM = "conditional-bearing-consensus-2d-v1"
DEFAULT_CONFIG = {
    "max_range_m": 500.0,
    "min_baseline_m": 2.0,
    "min_parallax_degrees": 2.0,
    "min_forward_m": 0.01,
    "max_condition_number": 10000.0,
    "max_refine_iterations": 8,
    "convergence_m": 1e-6,
}
MAX_RAYS = 64
_UTC = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: finite number required")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: outside [{low}, {high}]")
    return float(value)


def _text(value, name):
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        raise ValueError(f"{name}: nonempty bounded text required")
    return value


def _keys(value, required, name):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError(f"{name}: exact keys required: {', '.join(sorted(required))}")


def _provenance(value, name):
    _keys(value, ("reference", "sha256"), name)
    _text(value["reference"], name + ".reference")
    if not isinstance(value["sha256"], str) or not _SHA.fullmatch(value["sha256"]):
        raise ValueError(f"{name}: lowercase SHA-256 required")


def _time(value, name):
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise ValueError(f"{name}: explicit UTC timestamp required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name}: invalid UTC timestamp") from exc
    if not 2000 <= result.year <= 2100:
        raise ValueError(f"{name}: timestamp outside supported interval")
    return result


def _config(config):
    if config is None:
        return dict(DEFAULT_CONFIG)
    if not isinstance(config, dict) or set(config) - set(DEFAULT_CONFIG):
        raise ValueError("config: unknown fields")
    result = DEFAULT_CONFIG | config
    for key, low, high in (
        ("max_range_m", 1, 10000), ("min_baseline_m", 0.001, 10000),
        ("min_parallax_degrees", 0.01, 89), ("min_forward_m", 0.001, 100),
        ("max_condition_number", 1, 1e8), ("convergence_m", 1e-10, 0.1),
    ):
        result[key] = _number(result[key], key, low, high)
    iterations = result["max_refine_iterations"]
    if type(iterations) is not int or not 1 <= iterations <= 32:
        raise ValueError("max_refine_iterations: integer from 1 to 32 required")
    return result


def _validate(group):
    _keys(group, ("schema_version", "local_frame", "association", "rays"), "group")
    if type(group["schema_version"]) is not int or group["schema_version"] != 1:
        raise ValueError("schema_version: 1 required")
    frame = group["local_frame"]
    _keys(frame, ("frame_id", "axes", "units", "provenance"), "local_frame")
    _text(frame["frame_id"], "frame_id")
    if frame["axes"] != "east_north" or frame["units"] != "metres":
        raise ValueError("local_frame: east_north axes in metres required")
    _provenance(frame["provenance"], "local_frame.provenance")
    association = group["association"]
    _keys(association, ("group_id", "basis", "provenance"), "association")
    _text(association["group_id"], "group_id")
    if association["basis"] not in ("reviewed_same_physical_sign", "hypothesis"):
        raise ValueError("association: explicit reviewed identity or hypothesis required")
    _provenance(association["provenance"], "association.provenance")
    rows = group["rays"]
    if not isinstance(rows, list) or len(rows) > MAX_RAYS:
        raise ValueError(f"rays: list of at most {MAX_RAYS} required")
    seen = {key: set() for key in ("sighting_id", "source_frame_id", "position_fix_id")}
    result = []
    seen_positions = set()
    for row in rows:
        _keys(row, (
            "sighting_id", "source_frame_id", "position_fix_id", "source_kind",
            "captured_at", "fix_at", "ray_at", "position_en_m",
            "horizontal_error_bound_m", "position_error_covers_capture_time",
            "optical_ray_bearing_degrees", "angular_error_bound_degrees", "bearing_basis",
            "source_provenance", "position_provenance", "bearing_provenance",
        ), "ray")
        for key, values in seen.items():
            identity = _text(row[key], key)
            if identity in values:
                raise ValueError(f"duplicate {key}; repeated evidence is not independent")
            values.add(identity)
        if row["source_kind"] not in ("qualified_live_crop", "synthetic"):
            raise ValueError("source_kind: qualified live crop or synthetic only; replay excluded")
        if row["bearing_basis"] not in ("calibrated_optical_ray", "explicit_camera_hypothesis"):
            raise ValueError("bearing_basis: GPS travel course is not an optical ray")
        captured = _time(row["captured_at"], "captured_at")
        fix = _time(row["fix_at"], "fix_at")
        if _time(row["ray_at"], "ray_at") != captured:
            raise ValueError("ray_at: must describe the capture instant")
        if abs((captured - fix).total_seconds()) > 86400:
            raise ValueError("fix_at: more than one day from capture")
        if row["position_error_covers_capture_time"] is not True:
            raise ValueError("position bound must explicitly cover capture-time motion/error")
        for key in ("source_provenance", "position_provenance", "bearing_provenance"):
            _provenance(row[key], key)
        position = row["position_en_m"]
        if not isinstance(position, list) or len(position) != 2:
            raise ValueError("position_en_m: exactly east/north coordinates required")
        p = tuple(_number(v, "position_en_m", -100000, 100000) for v in position)
        if (p, fix) in seen_positions:
            raise ValueError("duplicate position and fix_at; relabeling a fix does not add evidence")
        seen_positions.add((p, fix))
        bearing = _number(row["optical_ray_bearing_degrees"], "bearing", 0, 360)
        if bearing == 360:
            raise ValueError("bearing: use canonical [0, 360) degrees")
        angle = _number(row["angular_error_bound_degrees"], "angular bound", 0, 45)
        error = _number(row["horizontal_error_bound_m"], "position bound", 0, 1000)
        if error == 0 and angle == 0:
            raise ValueError("at least one positive declared error bound required")
        theta, alpha = math.radians(bearing), math.radians(angle)
        result.append({
            "row": row, "p": p, "d": (math.sin(theta), math.cos(theta)),
            "n": (math.cos(theta), -math.sin(theta)), "theta": theta,
            "alpha": alpha, "error": error,
            "frame_fix_delta_ms": (captured - fix).total_seconds() * 1000,
        })
    if len({r["row"]["source_kind"] for r in result}) > 1:
        raise ValueError("synthetic and live evidence may not be mixed")
    return sorted(result, key=lambda r: r["row"]["sighting_id"])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _difference(a, b):
    return a[0] - b[0], a[1] - b[1]


def _intersection(a, b):
    na, nb = a["n"], b["n"]
    determinant = na[0] * nb[1] - na[1] * nb[0]
    if abs(determinant) < 1e-12:
        return None
    # Translate to the first origin to reduce cancellation at large EN offsets.
    rhs = _dot(nb, _difference(b["p"], a["p"]))
    return (a["p"][0] - na[1] * rhs / determinant,
            a["p"][1] + na[0] * rhs / determinant)


def _geometry(a, b):
    baseline = math.dist(a["p"], b["p"])
    cosine = min(1.0, abs(_dot(a["d"], b["d"])))
    return baseline, math.degrees(math.acos(cosine))


def _residual(ray, point, config):
    delta = _difference(point, ray["p"])
    forward = _dot(ray["d"], delta)
    distance = math.hypot(*delta)
    cross = _dot(ray["n"], delta)
    # Equivalent to both unit-normal wedge halfplanes expanded by position error.
    envelope = (forward * math.sin(ray["alpha"]) + ray["error"]) / math.cos(ray["alpha"])
    normalized = abs(cross) / max(envelope, 1e-12)
    reason = (
        "behind_camera" if forward < config["min_forward_m"] else
        "beyond_max_range" if distance > config["max_range_m"] else
        "outside_declared_bounds" if normalized > 1 + 1e-9 else "inlier"
    )
    return {"sighting_id": ray["row"]["sighting_id"], "reason": reason,
            "forward_m": forward, "range_m": distance,
            "cross_track_m": cross, "envelope_m": envelope,
            "normalized_residual": normalized, "frame_fix_delta_ms": ray["frame_fix_delta_ms"]}


def _support(rays, point, config):
    return tuple(i for i, ray in enumerate(rays) if _residual(ray, point, config)["reason"] == "inlier")


def _refine(rays, indices, start, config):
    point = start
    anchor = rays[indices[0]]["p"]
    condition = None
    for iteration in range(config["max_refine_iterations"]):
        aa = ab = bb = ae = be = 0.0
        for i in indices:
            ray = rays[i]
            envelope = _residual(ray, point, config)["envelope_m"]
            weight = 1 / max(envelope, 1e-6) ** 2
            nx, ny = ray["n"]
            rhs = _dot(ray["n"], _difference(ray["p"], anchor))
            aa += weight * nx * nx
            ab += weight * nx * ny
            bb += weight * ny * ny
            ae += weight * nx * rhs
            be += weight * ny * rhs
        determinant = aa * bb - ab * ab
        largest = (aa + bb + math.hypot(aa - bb, 2 * ab)) / 2
        smallest = determinant / largest if largest > 0 else 0
        if smallest <= 0:
            return None
        condition = largest / smallest
        if condition > config["max_condition_number"]:
            return None
        updated = (anchor[0] + (bb * ae - ab * be) / determinant,
                   anchor[1] + (aa * be - ab * ae) / determinant)
        if math.dist(updated, point) <= config["convergence_m"]:
            return updated, condition, iteration + 1
        point = updated
    # A fixed iteration cap is a computational limit, not evidence of convergence.
    return None


def _clip(polygon, normal, offset):
    """Sutherland-Hodgman clipping by normal·point <= offset."""
    clipped = []
    if not polygon:
        return clipped
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        da, db = _dot(normal, a) - offset, _dot(normal, b) - offset
        inside_a, inside_b = da <= 1e-9, db <= 1e-9
        if inside_a:
            clipped.append(a)
        if inside_a != inside_b:
            fraction = da / (da - db)
            clipped.append((a[0] + fraction * (b[0] - a[0]), a[1] + fraction * (b[1] - a[1])))
    return clipped


def _region(rays, indices, config):
    selected = [rays[i] for i in indices]
    radius = config["max_range_m"]
    xmin = min(r["p"][0] for r in selected) - radius
    xmax = max(r["p"][0] for r in selected) + radius
    ymin = min(r["p"][1] for r in selected) - radius
    ymax = max(r["p"][1] for r in selected) + radius
    polygon = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]
    for ray in selected:
        minus, plus = ray["theta"] - ray["alpha"], ray["theta"] + ray["alpha"]
        # Outward shift by e is the support function of an e-radius origin disk.
        normals = [(-math.cos(minus), math.sin(minus)),
                   (math.cos(plus), -math.sin(plus)),
                   (-ray["d"][0], -ray["d"][1])]
        for normal in normals:
            polygon = _clip(polygon, normal, _dot(normal, ray["p"]) + ray["error"])
    touched = any(min(abs(x - xmin), abs(x - xmax), abs(y - ymin), abs(y - ymax)) <= 1e-6
                  for x, y in polygon)
    area = abs(sum(a[0] * b[1] - b[0] * a[1]
                   for a, b in zip(polygon, polygon[1:] + polygon[:1]))) / 2 if polygon else 0
    return {"vertices_en_m": [list(p) for p in polygon], "bounds_known": bool(polygon) and not touched,
            "range_clipped": touched, "clipping_box_en_m": [xmin, ymin, xmax, ymax],
            "area_m2": area, "method": "intersection_of_position_expanded_bearing_wedges",
            "statistical_confidence": None, "conservative_given_declared_bounds": True,
            "conditional_on_inlier_ids": [r["row"]["sighting_id"] for r in selected]}


def triangulate(group: dict, config: dict | None = None) -> dict:
    """Return a serializable conditional estimate or an explicit failure status.

    Provenance hashes identify caller-supplied evidence; this pure function cannot
    independently read/verify those referenced objects or authenticate eligibility.
    ``qualified_live_crop`` must therefore come from the live-only lifecycle-aware
    adapter. ``synthetic`` is reserved for explicit fixtures and cannot mix with it.
    """
    result = {"schema_version": 1, "algorithm": ALGORITHM, "status": "invalid_input",
              "estimate_en_m": None, "feasible_region": None, "diagnostics": {},
              "statistical_confidence": None, "proves_physical_sign_identity": False,
              "proves_sign_to_road_applicability": False}
    try:
        policy = _config(config)
        rays = _validate(group)
    except (ValueError, TypeError, OverflowError) as exc:
        return result | {"reason": str(exc)}
    result.update({"config": policy, "local_frame": group["local_frame"],
                   "association": group["association"], "bearing_bases": sorted({r["row"]["bearing_basis"] for r in rays}),
                   "conditional_on_camera_hypothesis": any(r["row"]["bearing_basis"] == "explicit_camera_hypothesis" for r in rays),
                   "conditional_on_association_hypothesis": group["association"]["basis"] == "hypothesis"})
    if len(rays) < 2:
        return result | {"status": "underconstrained", "reason": "fewer_than_two_unique_rays"}
    minimum_support = max(2, len(rays) // 2 + 1)
    stats = {"input_rays": len(rays), "minimum_strict_majority": minimum_support,
             "pair_count": 0, "adequate_geometry_pairs": 0, "behind_camera_pairs": 0,
             "range_rejected_pairs": 0, "refinement_rejected": 0}
    candidates = {}
    for i, j in combinations(range(len(rays)), 2):
        stats["pair_count"] += 1
        baseline, parallax = _geometry(rays[i], rays[j])
        if baseline < policy["min_baseline_m"] or parallax < policy["min_parallax_degrees"]:
            continue
        stats["adequate_geometry_pairs"] += 1
        point = _intersection(rays[i], rays[j])
        if point is None:
            continue
        pair_residuals = [_residual(rays[k], point, policy) for k in (i, j)]
        if any(r["reason"] == "behind_camera" for r in pair_residuals):
            stats["behind_camera_pairs"] += 1
            continue
        if any(r["reason"] == "beyond_max_range" for r in pair_residuals):
            stats["range_rejected_pairs"] += 1
            continue
        indices = _support(rays, point, policy)
        if len(indices) < minimum_support:
            continue
        refined = _refine(rays, indices, point, policy)
        if refined is None:
            stats["refinement_rejected"] += 1
            continue
        fitted, condition, iterations = refined
        final_indices = _support(rays, fitted, policy)
        # Do not silently switch the fitted population after scoring it.
        if final_indices != indices:
            stats["refinement_rejected"] += 1
            continue
        residuals = [_residual(rays[k], fitted, policy) for k in indices]
        objective = sum(r["normalized_residual"] ** 2 for r in residuals)
        candidate = (objective, fitted, condition, iterations)
        if indices not in candidates or candidate < candidates[indices]:
            candidates[indices] = candidate
    result["diagnostics"] = stats
    if not candidates:
        status, reason = "inconsistent", "no_stable_strict_majority_consensus"
        if stats["adequate_geometry_pairs"] == 0:
            status, reason = "degenerate", "insufficient_baseline_or_parallax"
        elif stats["behind_camera_pairs"] == stats["adequate_geometry_pairs"]:
            status, reason = "behind_camera", "all_adequate_pair_intersections_behind_camera"
        elif stats["range_rejected_pairs"] + stats["behind_camera_pairs"] == stats["adequate_geometry_pairs"]:
            status, reason = "underconstrained", "no_forward_intersection_within_max_range"
        return result | {"status": status, "reason": reason}
    largest = max(map(len, candidates))
    winners = [indices for indices in candidates if len(indices) == largest]
    if len(winners) != 1:
        stats["competing_consensus_sets"] = [[rays[i]["row"]["sighting_id"] for i in indices]
                                             for indices in sorted(winners)]
        return result | {"status": "ambiguous", "reason": "equal_size_distinct_consensus_sets"}
    indices = winners[0]
    objective, point, condition, iterations = candidates[indices]
    polygon = _region(rays, indices, policy)
    if not polygon["vertices_en_m"]:
        return result | {"status": "inconsistent", "reason": "empty_declared_feasible_region"}
    pair_geometry = [_geometry(rays[i], rays[j]) for i, j in combinations(indices, 2)]
    stats.update({"inlier_count": len(indices), "outlier_count": len(rays) - len(indices),
                  "max_baseline_m": max(b for b, _ in pair_geometry),
                  "max_parallax_degrees": max(p for _, p in pair_geometry),
                  "normal_matrix_condition": condition, "refinement_iterations": iterations,
                  "scaled_line_objective": objective,
                  "two_ray_outlier_check_unavailable": len(rays) == 2,
                  "residuals": [_residual(ray, point, policy) for ray in rays]})
    return result | {"status": "estimated", "reason": "conditional_planar_estimate",
                     "estimate_en_m": list(point), "feasible_region": polygon}
