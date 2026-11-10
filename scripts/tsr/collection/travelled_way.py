"""Frame-bound vehicle matches for private sign approach review."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sqlite3

from scripts.map.packed_runtime import HEADER, Reader
from scripts.tsr.collection.sign_road_association import closest_segment, sha256


@dataclass(frozen=True)
class PhoneMatch:
    way_id: str
    bundle_hash: str
    direction: str

    @classmethod
    def from_frame(cls, raw, captured_at):
        if (
            not isinstance(raw, dict)
            or type(raw.get("schema_version")) is not int
            or raw["schema_version"] != 1
            or raw.get("source") != "on_device_bundle_matcher"
            or raw.get("matched_way_stable") is not True
            or raw.get("travel_direction") not in ("forward", "reverse")
        ):
            return None
        way_id, bundle_hash = raw.get("osm_way_id"), raw.get("bundle_db_sha256")
        delta = raw.get("frame_match_delta_ms")
        if (
            not isinstance(way_id, str)
            or not re.fullmatch(r"[1-9][0-9]{0,18}", way_id)
            or int(way_id) > 2**63 - 1
            or not isinstance(bundle_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", bundle_hash)
            or type(delta) not in (int, float)
            or not -1000 <= delta <= 1000
        ):
            return None
        try:
            capture, fix = (
                datetime.fromisoformat(text.replace("Z", "+00:00"))
                for text in (captured_at, raw["matched_fix_at"])
            )
            if capture.utcoffset() is None or fix.utcoffset() is None:
                return None
            elapsed = (capture - fix).total_seconds() * 1000
        except (KeyError, AttributeError, TypeError, ValueError):
            return None
        if not -1000 <= elapsed <= 1000 or abs(elapsed - delta) > 1:
            return None
        return cls(way_id, bundle_hash, raw["travel_direction"])


def file_identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def verified_file(path, expected=None):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("travel bundle artifact must be a regular file")
    identity = file_identity(path)
    digest = sha256(path)
    if file_identity(path) != identity or (expected is not None and digest != expected):
        raise ValueError("travel bundle artifact failed SHA-256 verification")
    return digest, (path, identity)


def packed_geometry(manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "youspeed.v4.bundle.manifest":
        raise ValueError("travel bundle manifest must describe a v4 packed bundle")
    context = manifest["db"]
    roads = manifest["packed_base"]["roads"]
    source = manifest["source"]["packed_storage"]["original_sqlite_sha256"]
    verified = []
    for artifact, sha_field, magic in (
        (context, "sha256", b"YSPCTX1\0"),
        (roads, "uncompressed_sha256", b"YSPGEO1\0"),
    ):
        filename = artifact["file"]
        if Path(filename).name != filename:
            raise ValueError("packed travel artifacts must be beside their manifest")
        _, location = verified_file(
            manifest_path.parent / filename, artifact[sha_field]
        )
        with location[0].open("rb") as stream:
            header = stream.read(HEADER)
        if header[:8] != magic or header[96:HEADER].hex() != source:
            raise ValueError(
                "packed travel artifacts must share the original geometry revision"
            )
        verified.append(location)
    return context["sha256"], tuple(verified)


class TravelBundles:
    """Translate phone-relative directions only against identical ordered geometry."""

    def __init__(self, paths, packed_manifests=()):
        self.bundles = {}
        self.geometries = {}
        for path in paths:
            key, location = verified_file(path)
            path, _ = location
            with closing(
                sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
            ) as db:
                policy = db.execute(
                    "SELECT value FROM metadata WHERE key='road_geometry_policy'"
                ).fetchone()
            if policy != ("source_vertices_v1",):
                raise ValueError("travel bundle must preserve source way vertices")
            self.bundles[key] = location
        self.packed = dict(packed_geometry(Path(path)) for path in packed_manifests)

    def direction(self, match, points):
        packed = self.packed.get(match.bundle_hash)
        locations = packed or (self.bundles.get(match.bundle_hash),)
        if locations[0] is None:
            return None
        for artifact, identity in locations:
            if file_identity(artifact) != identity:
                raise ValueError("travel bundle changed after verification")
        key = (match.bundle_hash, match.way_id)
        if key not in self.geometries:
            path, _ = locations[-1]
            if packed:
                with closing(Reader(path)) as reader:
                    geometry = reader.geometry(match.way_id)
            else:
                with closing(
                    sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
                ) as db:
                    record = db.execute(
                        "SELECT points_json FROM way_geom WHERE way_id=?",
                        (int(match.way_id),),
                    ).fetchone()
                geometry = record[0] if record else None
            self.geometries[key] = json.loads(geometry) if geometry else []
        captured = self.geometries[key]
        if len(captured) != len(points):
            return None
        same = all(math.dist(a, b) <= 1e-7 for a, b in zip(captured, points))
        reverse = all(
            math.dist(a, b) <= 1e-7 for a, b in zip(reversed(captured), points)
        )
        if same == reverse:
            return None
        if same:
            return "forward" if match.direction == "forward" else "backward"
        return "backward" if match.direction == "forward" else "forward"


def recorded_approach(fit, way, sign_projection, bundles):
    """Return corroboration from independent upstream frames on this exact way."""
    matched = [ray for ray in fit.rays if getattr(ray, "phone_match", None) is not None]
    if len({ray.image for ray in matched}) < 2 or len({ray.fix for ray in matched}) < 2:
        return None
    votes = set()
    upstream = False
    for ray in matched:
        match = ray.phone_match
        if match.way_id != way.key:
            return None
        direction = bundles.direction(match, way.source_points)
        if direction is None:
            return None
        votes.add(direction)
        camera = closest_segment(ray.position, way.points)
        tangent = sign_projection["tangent_degrees"]
        bend = abs((camera["tangent_degrees"] - tangent + 180) % 360 - 180)
        if camera["tangent_ambiguous"] or bend > 20 or camera["distance_m"] > 12:
            return None
        heading = math.radians(tangent if direction == "forward" else tangent + 180)
        if (
            ray.direction[0] * math.sin(heading) + ray.direction[1] * math.cos(heading)
            <= 0
        ):
            return None
        progress = sign_projection["along_way_m"] - camera["along_way_m"]
        if direction == "backward":
            progress = -progress
        uncertainty = fit.radius + ray.position_error + 2
        if progress < -uncertainty:
            return None
        upstream |= progress > uncertainty
    return next(iter(votes)) if len(votes) == 1 and upstream else None
