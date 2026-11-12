"""Metric survey scopes; export points and source camera coverage are separate."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from xml.etree import ElementTree

from fiona.transform import transform_geom
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import unary_union

from scripts.research.profile_bw_sign_route import route_segments, timestamp

WGS84 = "EPSG:4326"
METRIC = "EPSG:25832"
CORRIDOR_M = 30
CAMERA_BUFFER_M = 100


def project_geometry(geometry, source=WGS84, target=METRIC):
    return shape(transform_geom(source, target, mapping(geometry)))


def validate_bbox(values):
    if len(values) != 4 or not all(math.isfinite(v) for v in values):
        raise ValueError("bbox needs four finite WGS84 coordinates")
    west, south, east, north = values
    # Supported longitude range is Germany's EPSG:25832 area, not UTM zone 33.
    if not (6 <= west < east <= 12 and 47 <= south < north <= 56):
        raise ValueError("scope must lie in Germany's supported UTM32 range (6–12 E, 47–56 N)")
    return tuple(values)


def bbox_polygon(values):
    west, south, east, north = validate_bbox(values)
    corners = [(west, south), (east, south), (east, north), (west, north), (west, south)]
    # Densify geographic edges before projection; a projected four-corner box
    # would silently use straight metric edges in place of latitude parallels.
    return Polygon([(a[0] + (b[0] - a[0]) * i / 32,
                     a[1] + (b[1] - a[1]) * i / 32)
                    for a, b in zip(corners, corners[1:]) for i in range(32)])


def gpx_geometry(path):
    root = ElementTree.parse(path).getroot()
    fixes = []
    local = lambda element: element.tag.rsplit("}", 1)[-1]
    parts = [element for element in root.iter() if local(element) in {"trkseg", "rte"}]
    for part, segment in enumerate(parts):
        for point in segment:
            if local(point) not in {"trkpt", "rtept"}:
                continue
            lon, lat = float(point.attrib["lon"]), float(point.attrib["lat"])
            if not (math.isfinite(lon) and math.isfinite(lat) and 6 <= lon <= 12 and 47 <= lat <= 56):
                raise ValueError("GPX fix outside Germany's supported UTM32 range")
            at = next((child.text for child in point if local(child) == "time"), None)
            fixes.append(dict(index=len(fixes), lon=lon, lat=lat, part=part, timestamp=timestamp(at)))
    if not fixes:
        raise ValueError("GPX contains no track or route fixes")
    segments, gaps = route_segments(fixes)
    lines = []
    for a, b in segments:
        first, second = (a["lon"], a["lat"]), (b["lon"], b["lat"])
        lines.append(project_geometry(Point(first) if first == second else LineString([first, second])))
    return unary_union(lines), {"valid_fixes": len(fixes), "track_parts": len(parts), "gaps": gaps,
                                "endpoint_gap_not_closed": True,
                                "gpx_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}


@dataclass(frozen=True)
class SurveyScope:
    canonical: object
    export: object
    route: object | None
    metadata: dict

    @property
    def source_camera_geometry(self):
        return self.canonical.buffer(CAMERA_BUFFER_M)

    @property
    def query_bbox(self):
        return project_geometry(self.source_camera_geometry, METRIC, WGS84).bounds

    @property
    def canonical_wgs84(self):
        return mapping(project_geometry(self.canonical, METRIC, WGS84))

    def as_dict(self):
        return {"schema_version": 1, "crs": METRIC, "area_geometry": mapping(self.canonical),
                "export_geometry": mapping(self.export), "route_geometry": mapping(self.route) if self.route else None,
                "source_camera_geometry": mapping(self.source_camera_geometry),
                "source_query_bbox_wgs84": self.query_bbox, "camera_buffer_m": CAMERA_BUFFER_M,
                "export_point_rule": "Canonical sign point intersects export geometry; camera coverage is not a point filter.",
                **self.metadata}


def make_scope(*, gpx=None, bbox=None, context_bbox=None, context_geometry=None):
    if (gpx is None) == (bbox is None):
        raise ValueError("supply exactly one of GPX or bbox")
    route, metadata = None, {"kind": "bbox"}
    if gpx is not None:
        route, metadata = gpx_geometry(gpx)
        metadata.update(kind="gpx", corridor_radius_m=CORRIDOR_M)
        export = route.buffer(CORRIDOR_M)
    else:
        export = project_geometry(bbox_polygon(bbox))
    if context_bbox is not None and context_geometry is not None:
        raise ValueError("supply one canonical context geometry or bbox")
    canonical = project_geometry(bbox_polygon(context_bbox)) if context_bbox else export
    if context_geometry is not None:
        value = json.loads(Path(context_geometry).read_text()) if isinstance(context_geometry, (str, Path)) else context_geometry
        geometry = shape(value.get("geometry", value))
        validate_bbox(geometry.bounds)
        if geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty or not geometry.is_valid:
            raise ValueError("canonical context must be a valid WGS84 Polygon or MultiPolygon")
        canonical = project_geometry(geometry)
    if not canonical.buffer(0.001).covers(export):
        raise ValueError("canonical context must cover the entire export scope, including the GPX corridor")
    return SurveyScope(canonical, export, route, metadata)
