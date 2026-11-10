"""Fit private traffic-sign position and front-face hypotheses from qualified rays."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import re

from fiona.transform import transform
from shapely.geometry import Point, box
from shapely.strtree import STRtree

from scripts.tsr.collection.triangulate_sign_position import MAX_RAYS, triangulate
from scripts.tsr.collection.travelled_way import PhoneMatch


WGS84 = "EPSG:4326"
METRIC = "EPSG:25832"
SOURCE_KINDS = {
    "mobile": "qualified_live_crop",
    "panoramax": "qualified_panoramax_annotation",
}
SIGN_CODE = re.compile(r"DE:[0-9]{3,4}(?:[.-][0-9]{1,4}){0,3}")
MAX_RANGE_M = 100.0
MIN_RANGE_M = 4.0
MIN_BASELINE_M = 3.0
MIN_PARALLAX_DEG = 8.0
MAX_POSITION_RADIUS_M = 20.0
MAX_RAY_POSITION_ERROR_M = 50.0
MAX_MOBILE_SOURCE_POSITION_ERROR_M = 110.0
MIN_VIEWS = 3
MAX_PAIRS_PER_CLASS = 300_000
MAX_HEADING_ERROR_DEG = 45.0
IDENTITY_DISTANCE_M = 20.0
IDENTITY_VIEW_DIFFERENCE_DEG = 30.0


def digest(value):
    raw = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def number(value, minimum, maximum):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not minimum <= value <= maximum
    ):
        raise ValueError("invalid sign ray measurement")
    return float(value)


def identity(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 250
        or not value.isprintable()
    ):
        raise ValueError("invalid sign ray identifier")
    return value


def vector(bearing):
    theta = math.radians(bearing)
    return math.sin(theta), math.cos(theta)


def angle(vector):
    return math.degrees(math.atan2(*vector)) % 360


def delta_angle(a, b):
    return abs((a - b + 180) % 360 - 180)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def subtract(a, b):
    return a[0] - b[0], a[1] - b[1]


def project(lons, lats):
    """Return projected coordinates and rotation from true north to grid north."""
    xs, ys = transform(
        WGS84, METRIC, lons + lons, lats + [lat + 0.0001 for lat in lats]
    )
    size = len(lons)
    return [
        ((x, y), angle((nx - x, ny - y)))
        for x, y, nx, ny in zip(xs[:size], ys[:size], xs[size:], ys[size:])
    ]


@dataclass(frozen=True)
class Ray:
    key: str
    image: str
    sequence: str
    fix: str
    code: str
    position: tuple[float, float]
    direction: tuple[float, float]
    bearing: float
    angular_error: float
    position_error: float
    width: float | None
    width_error: float | None
    source: str
    pose_basis: str
    group: str | None
    captured_at: str
    fix_at: str
    fingerprint: str
    phone_match: PhoneMatch | None = None
    evidence_kind: str | None = None

    @classmethod
    def parse(cls, record, position, rotation):
        source = record["source"]
        pose = record["pose_basis"]
        code = record["sign_code"]
        if (
            source not in SOURCE_KINDS
            or pose not in ("calibrated", "assumed")
            or not SIGN_CODE.fullmatch(code)
        ):
            raise ValueError("invalid source, camera model or German sign code")
        captured = record["captured_at"]
        fix_at = record.get("fix_at") or captured
        for timestamp in (captured, fix_at):
            if not re.fullmatch(
                r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z",
                timestamp,
            ):
                raise ValueError("an exact UTC capture and fix timestamp is required")
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        bearing = (number(record["bearing_degrees"], 0, 360) + rotation) % 360
        group = record.get("group_id")
        if group is not None:
            group = f"{source}:{identity(record['sequence_id'])}:{identity(group)}"
        width = record.get("angular_width_deg")
        evidence_kind = record.get("evidence_kind")
        if evidence_kind is not None and (
            source != "mobile"
            or evidence_kind != "sighting"
            or pose != "assumed"
            or width is not None
            or record.get("phone_road_match") is not None
        ):
            raise ValueError(
                "mobile sighting rays require a bounded assumed camera model"
            )
        return cls(
            key=f"{source}:{identity(record['observation_id'])}",
            image=f"{source}:{identity(record['image_id'])}",
            sequence=f"{source}:{identity(record['sequence_id'])}",
            fix=identity(record.get("fix_id") or digest([fix_at, position])),
            code=code,
            position=position,
            direction=vector(bearing),
            bearing=bearing,
            angular_error=number(record["bearing_error_deg"], 0.01, 45),
            position_error=number(
                record["horizontal_error_m"], 0.01, MAX_RAY_POSITION_ERROR_M
            ),
            width=number(width, 0.01, 45) if width is not None else None,
            width_error=number(record.get("width_relative_error", 0.30), 0.10, 0.90)
            if width is not None
            else None,
            source=source,
            pose_basis=pose,
            group=group,
            captured_at=captured,
            fix_at=fix_at,
            fingerprint=digest(record),
            phone_match=PhoneMatch.from_frame(record.get("phone_road_match"), captured)
            if source == "mobile"
            else None,
            evidence_kind=evidence_kind,
        )

    def envelope(self):
        x, y = self.position
        dx, dy = self.direction
        slack = self.position_error + MAX_RANGE_M * math.sin(
            math.radians(self.angular_error)
        )
        end_x, end_y = x + MAX_RANGE_M * dx, y + MAX_RANGE_M * dy
        return box(
            min(x, end_x) - slack,
            min(y, end_y) - slack,
            max(x, end_x) + slack,
            max(y, end_y) + slack,
        )

    def intersection(self, other):
        determinant = cross(self.direction, other.direction)
        if abs(determinant) < math.sin(math.radians(MIN_PARALLAX_DEG)):
            return None
        if math.dist(self.position, other.position) < MIN_BASELINE_M:
            return None
        displacement = subtract(other.position, self.position)
        distance_a = cross(displacement, other.direction) / determinant
        distance_b = cross(displacement, self.direction) / determinant
        if not (
            MIN_RANGE_M <= distance_a <= MAX_RANGE_M
            and MIN_RANGE_M <= distance_b <= MAX_RANGE_M
        ):
            return None
        return tuple(p + distance_a * d for p, d in zip(self.position, self.direction))

    def association_distance(self, point):
        offset = subtract(point, self.position)
        forward = dot(self.direction, offset)
        if forward < MIN_RANGE_M or math.hypot(*offset) > MAX_RANGE_M:
            return None
        cross_track = abs(cross(self.direction, offset))
        envelope = self.position_error + forward * math.tan(
            math.radians(self.angular_error)
        )
        # A tight nominal gate groups rays. Declared wider envelopes qualify the fit.
        if cross_track > min(3.0, 0.65 * envelope):
            return None
        return cross_track / envelope

    def solver_row(self, anchor):
        provenance = {
            "reference": "qualified private source ray",
            "sha256": self.fingerprint,
        }
        return {
            "sighting_id": self.key,
            "source_frame_id": self.image,
            "position_fix_id": self.fix,
            "source_kind": (
                "qualified_live_sighting"
                if self.evidence_kind == "sighting"
                else SOURCE_KINDS[self.source]
            ),
            "captured_at": self.captured_at,
            "fix_at": self.fix_at,
            "ray_at": self.captured_at,
            "position_en_m": list(subtract(self.position, anchor)),
            "horizontal_error_bound_m": self.position_error,
            "position_error_covers_capture_time": True,
            "optical_ray_bearing_degrees": self.bearing,
            "angular_error_bound_degrees": self.angular_error,
            "bearing_basis": "calibrated_optical_ray"
            if self.pose_basis == "calibrated"
            else "explicit_camera_hypothesis",
            "source_provenance": provenance,
            "position_provenance": provenance,
            "bearing_provenance": provenance,
        }


def independent(rays, *, scores=None):
    if scores is not None:
        image_counts = Counter(ray.image for ray in rays)
        rays = [ray for ray in rays if image_counts[ray.image] == 1]
    retained = []
    images, fixes = set(), set()
    for ray in sorted(
        rays,
        key=lambda r: (
            (scores or {}).get(r.key, 0),
            r.position_error,
            r.angular_error,
            r.key,
        ),
    ):
        if ray.image in images or ray.fix in fixes:
            continue
        if any(math.dist(ray.position, other.position) < 1.0 for other in retained):
            continue
        retained.append(ray)
        images.add(ray.image)
        fixes.add(ray.fix)
    return tuple(sorted(retained, key=lambda ray: ray.key))


def associations(rays):
    """Produce bounded candidate sets of same-class independent observations."""
    groups = defaultdict(list)
    for ray in rays:
        if ray.group is not None:
            groups[ray.group].append(ray)
    sets = {}
    for group in groups.values():
        rows = independent(group)
        if MIN_VIEWS <= len(rows) <= MAX_RAYS:
            sets[tuple(ray.key for ray in rows)] = rows
    all_one_group = len(groups) == 1 and len(next(iter(groups.values()))) == len(rays)
    if len(rays) < MIN_VIEWS or all_one_group:
        return sets

    index = STRtree([ray.envelope() for ray in rays])
    tested_pairs = 0
    for i, ray in enumerate(rays):
        for j in sorted(index.query(ray.envelope())):
            if j <= i:
                continue
            tested_pairs += 1
            if tested_pairs > MAX_PAIRS_PER_CLASS:
                raise ValueError(
                    "too many overlapping same-class rays; use a smaller survey area"
                )
            point = ray.intersection(rays[j])
            if point is None:
                continue
            matched = []
            scores = {}
            for k in index.query(Point(point)):
                other = rays[k]
                score = other.association_distance(point)
                if score is not None:
                    matched.append(other)
                    scores[other.key] = score
            if not MIN_VIEWS <= len(matched) <= MAX_RAYS:
                continue
            rows = independent(matched, scores=scores)
            if MIN_VIEWS <= len(rows) <= MAX_RAYS:
                sets.setdefault(tuple(other.key for other in rows), rows)
    return sets


@dataclass(frozen=True)
class Fit:
    point: tuple[float, float]
    radius: float
    rays: tuple[Ray, ...]
    region: tuple[tuple[float, float], ...]

    @property
    def keys(self):
        return tuple(ray.key for ray in self.rays)


def fit_position(rays, *, max_radius=MAX_POSITION_RADIUS_M):
    anchor = rays[0].position
    frame = {"reference": METRIC, "sha256": digest(anchor)}
    ids = [ray.key for ray in rays]
    association = {
        "reference": "same-class ray association hypothesis",
        "sha256": digest(ids),
    }
    result = triangulate(
        {
            "schema_version": 1,
            "local_frame": {
                "frame_id": METRIC,
                "axes": "east_north",
                "units": "metres",
                "provenance": frame,
            },
            "association": {
                "group_id": digest(ids),
                "basis": "hypothesis",
                "provenance": association,
            },
            "rays": [ray.solver_row(anchor) for ray in rays],
        },
        {
            "max_range_m": MAX_RANGE_M,
            "min_forward_m": MIN_RANGE_M,
            "min_baseline_m": MIN_BASELINE_M,
            "min_parallax_degrees": MIN_PARALLAX_DEG,
        },
    )
    if result["status"] == "invalid_input":
        raise ValueError(f"invalid qualified ray input: {result['reason']}")
    if result["status"] != "estimated":
        return None, result["status"]
    region = result["feasible_region"]
    point = result["estimate_en_m"]
    selected = set(region["conditional_on_inlier_ids"])
    if len(selected) < MIN_VIEWS:
        return None, "insufficient_consensus"
    radius = max(math.dist(point, edge) for edge in region["vertices_en_m"])
    if not region["bounds_known"] or radius > max_radius:
        return None, "position_envelope_too_wide"
    absolute = (point[0] + anchor[0], point[1] + anchor[1])
    vertices = tuple((x + anchor[0], y + anchor[1]) for x, y in region["vertices_en_m"])
    return Fit(
        absolute, radius, tuple(ray for ray in rays if ray.key in selected), vertices
    ), "estimated"


def consolidate(fits):
    """Keep the best supported fit for reused rays and withhold close-ranked conflicts."""
    chosen = {}
    ambiguous = set()
    unique = {fit.keys: fit for fit in sorted(fits, key=lambda f: -f.radius)}
    for fit in sorted(unique.values(), key=lambda f: (-len(f.rays), f.radius, f.keys)):
        if ambiguous.intersection(fit.keys):
            continue
        competing = {chosen[key] for key in fit.keys if key in chosen}
        if not competing:
            chosen.update(dict.fromkeys(fit.keys, fit))
            continue
        for other in competing:
            if (
                len(fit.rays) >= len(other.rays) - 1
                and math.dist(fit.point, other.point) > 6
            ):
                ambiguous.update(other.keys)
                ambiguous.update(fit.keys)
    return sorted(
        {f for f in chosen.values() if not ambiguous.intersection(f.keys)},
        key=lambda f: f.keys,
    )


def angle_envelope(bearings, padding=0.0):
    """Smallest circular arc containing all bearings, with outward padding."""
    headings = sorted(set(bearings))
    if not headings:
        return None
    if len(headings) == 1:
        return headings[0], padding
    gap, _, start = max(
        ((b - a) % 360, a, b) for a, b in zip(headings, headings[1:] + headings[:1])
    )
    half = (360 - gap) / 2
    return ((start + half) % 360, half + padding) if half + padding < 180 else None


def mean_bearing(bearings):
    vectors = [vector(value) for value in bearings]
    east, north = (math.fsum(axis) for axis in zip(*vectors))
    return angle((east, north)) if math.hypot(east, north) >= len(vectors) / 2 else None


@dataclass(frozen=True)
class ImageBearingCandidate:
    heading: float
    spread: float
    bearing_allowance: float
    views: int
    sequences: int


def image_bearing_candidate(rays):
    """Summarize the camera side of a sign. This is a front-normal proxy."""
    rays = independent(rays)
    if len(rays) < 2:
        return None
    sequences = defaultdict(list)
    for ray in rays:
        sequences[ray.sequence].append((ray.bearing + 180) % 360)
    # Repeated frames from one pass do not outvote an independent pass.
    representatives = [mean_bearing(values) for _, values in sorted(sequences.items())]
    if any(value is None for value in representatives):
        return None
    heading = mean_bearing(representatives)
    if heading is None:
        return None
    spread = max(
        delta_angle(heading, value) for values in sequences.values() for value in values
    )
    if spread >= 90:
        return None
    return ImageBearingCandidate(
        heading,
        spread,
        max(ray.angular_error for ray in rays),
        len(rays),
        len(sequences),
    )


def separate_opposite_views(rays):
    """Keep clearly opposing sequence approaches out of the same ray fit."""
    by_sequence = defaultdict(list)
    for ray in rays:
        by_sequence[ray.sequence].append(ray.bearing)
    means = {key: mean_bearing(values) for key, values in by_sequence.items()}
    directions = [value for value in means.values() if value is not None]
    if not any(delta_angle(a, b) >= 120 for a in directions for b in directions):
        return (rays,)
    return tuple(
        tuple(
            ray
            for ray in rays
            if means[ray.sequence] is not None
            and delta_angle(means[ray.sequence], direction) <= 45
        )
        for direction in sorted(set(directions))
    )


def opposing_fits(rays, cached_fit):
    groups = separate_opposite_views(rays)
    if len(groups) < 2:
        return []
    fitted = {}
    for group in groups:
        if len(group) >= MIN_VIEWS:
            fit, _ = cached_fit(group)
            if fit is not None:
                direction = image_bearing_candidate(fit.rays)
                if direction is not None:
                    fitted[fit.keys] = (fit, direction.heading)
    matches = set()
    candidates = list(fitted.values())
    for i, (fit, direction) in enumerate(candidates):
        for other, other_direction in candidates[i + 1 :]:
            if (
                delta_angle(direction, other_direction) >= 120
                and math.dist(fit.point, other.point) < IDENTITY_DISTANCE_M
                and not set(fit.keys).intersection(other.keys)
            ):
                matches.update((fit, other))
    return sorted(matches, key=lambda fit: fit.keys)


def consolidate_sequences(estimates):
    """Merge disjoint cross-sequence fits only if all evidence supports one sign."""
    by_code = defaultdict(list)
    for code, fit, heading in estimates:
        by_code[code].append((fit, heading, image_bearing_candidate(fit.rays)))
    results = []
    for code, candidates in sorted(by_code.items()):
        points = [Point(fit.point) for fit, _, _ in candidates]
        index = STRtree(points)
        neighbors = [{i} for i in range(len(candidates))]
        for i, (fit, _, direction) in enumerate(candidates):
            if direction is None:
                continue
            sequences = {ray.sequence for ray in fit.rays}
            images = {ray.image for ray in fit.rays}
            for j in index.query(
                points[i], predicate="dwithin", distance=IDENTITY_DISTANCE_M
            ):
                other, _, other_direction = candidates[j]
                if (
                    j <= i
                    or other_direction is None
                    or math.dist(fit.point, other.point) >= IDENTITY_DISTANCE_M
                    or delta_angle(direction.heading, other_direction.heading)
                    > IDENTITY_VIEW_DIFFERENCE_DEG
                    or sequences == {ray.sequence for ray in other.rays}
                    or any(ray.image in images for ray in other.rays)
                ):
                    continue
                neighbors[i].add(j)
                neighbors[j].add(i)
        visited = set()
        for i, adjacent in enumerate(neighbors):
            if i in visited:
                continue
            # A chain of nearby detections cannot make one sign.
            if len(adjacent) > 1 and all(neighbors[j] == adjacent for j in adjacent):
                members = [candidates[j][0] for j in sorted(adjacent)]
                rays = independent([ray for member in members for ray in member.rays])
                if len(rays) <= MAX_RAYS:
                    combined, _ = fit_position(rays)
                    if combined and all(
                        len(set(member.keys).intersection(combined.keys)) >= 2
                        for member in members
                    ):
                        results.append((code, combined, heading_interval(combined)))
                        visited.update(adjacent)
                        continue
            fit, heading, _ = candidates[i]
            results.append((code, fit, heading))
    return results


def heading_interval(fit):
    """Bound the face normal from optical rays and optional panel geometry."""
    views = [((ray.bearing + 180) % 360, 90 + ray.angular_error) for ray in fit.rays]
    if len(views) < MIN_VIEWS:
        return None
    headings = [
        h
        for h in range(360)
        if all(delta_angle(h, direction) <= bound for direction, bound in views)
    ]
    if not headings:
        return None
    widths = []
    for ray in fit.rays:
        offset = subtract(ray.position, fit.point)
        distance = math.hypot(*offset)
        error = fit.radius + ray.position_error
        if error >= distance:
            continue
        uncertainty = math.degrees(math.asin(error / distance))
        direction = angle(offset)
        if ray.width is not None and uncertainty < 30:
            apparent_scale = 2 * math.tan(math.radians(ray.width / 2))
            low = (distance - error) * apparent_scale * (1 - ray.width_error)
            high = (distance + error) * apparent_scale * (1 + ray.width_error)
            widths.append((direction, uncertainty, low, high))
    method = "front_visibility"
    if len(widths) >= MIN_VIEWS:
        feasible = []
        for h in headings:
            # A vertical planar sign has apparent width W*cos(obliquity).
            # Bound W across all views, allowing position and box uncertainty.
            lower, upper = 0.05, 8.0
            for direction, uncertainty, low, high in widths:
                distance = delta_angle(h, direction)
                best = math.cos(math.radians(max(0, distance - uncertainty)))
                worst = math.cos(math.radians(min(90, distance + uncertainty)))
                if best <= 1e-12:
                    lower = math.inf
                    break
                lower = max(lower, low / best)
                if worst > 1e-12:
                    upper = min(upper, high / worst)
            if lower <= upper:
                feasible.append(h)
        if feasible:
            headings = feasible
            method = "panel_foreshortening"

    envelope = angle_envelope(headings, padding=1)
    return (*envelope, method) if envelope is not None else None


def estimate(records, *, max_radius=MAX_POSITION_RADIUS_M):
    """Return position/heading hypotheses and aggregate rejection counts."""
    if not records:
        return [], {}
    lons = [number(r["longitude"], 5, 16) for r in records]
    lats = [number(r["latitude"], 47, 56) for r in records]
    classes = defaultdict(list)
    seen = {}
    for record, (point, rotation) in zip(records, project(lons, lats)):
        ray = Ray.parse(record, point, rotation)
        if ray.key in seen:
            if ray != seen[ray.key]:
                raise ValueError("conflicting duplicate source ray")
            continue
        seen[ray.key] = ray
        classes[ray.code].append(ray)
    results = []
    stats = Counter()
    for code in sorted(classes):
        rays = sorted(classes[code], key=lambda r: r.key)
        fitted = []
        cache = {}

        def cached_fit(candidate):
            key = tuple(ray.key for ray in candidate)
            if key not in cache:
                cache[key] = fit_position(candidate, max_radius=max_radius)
            return cache[key]

        for candidate in associations(rays).values():
            split = opposing_fits(candidate, cached_fit)
            if split:
                fitted.extend(split)
                stats["opposing_face_splits"] += 1
                continue
            fit, status = cached_fit(candidate)
            stats[status] += 1
            if fit is not None:
                fitted.append(fit)
        accepted = consolidate(fitted)
        stats["conflicting_or_redundant_fits"] += len(fitted) - len(accepted)
        for fit in accepted:
            results.append((code, fit, heading_interval(fit)))
    return results, dict(stats)
