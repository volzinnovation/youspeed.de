"""Geometry helpers: preserve topology with a metric error budget, never a vertex cap."""

import math


def simplify_polygon(polygon, tolerance_m=2.0):
    """Simplify in a local metre projection; preserve invalid/source geometry unchanged.

    Local equirectangular coordinates avoid the latitude-dependent metre scale of
    Web Mercator. This is for individual settlement polygons, not continent shapes.
    """
    if tolerance_m <= 0 or polygon.is_empty or not polygon.is_valid:
        return polygon
    from shapely.affinity import affine_transform

    lon0, lat0 = polygon.centroid.coords[0]
    sy = math.pi * 6378137.0 / 180.0
    sx = sy * max(0.01, math.cos(math.radians(lat0)))
    local = affine_transform(polygon, [sx, 0, 0, sy, -lon0 * sx, -lat0 * sy])
    simplified = local.simplify(tolerance_m, preserve_topology=True)
    if simplified.is_empty or not simplified.is_valid:
        return polygon
    return affine_transform(simplified, [1 / sx, 0, 0, 1 / sy, lon0, lat0])


def simplify_ring(points, tolerance_m=2.0):
    """Older packer environments without Shapely retain exact source vertices."""
    if len(points) < 4:
        return points
    try:
        from shapely.geometry import Polygon
    except ImportError:
        return points
    polygon = Polygon(points)
    if not polygon.is_valid:
        return points
    return list(simplify_polygon(polygon, tolerance_m).exterior.coords)
