from shapely.geometry import Point, box, mapping
import pytest

from scripts.inspector.survey_scope import make_scope, project_geometry, METRIC, WGS84


def gpx(tmp_path, segments):
    path = tmp_path / "route.gpx"
    path.write_text('<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk>' + ''.join(
        '<trkseg>' + ''.join(f'<trkpt lon="{x}" lat="{y}"/>' for x, y in points) + '</trkseg>'
        for points in segments) + '</trk></gpx>')
    return path


def test_route_corridor_is_metric_and_camera_buffer_is_separate(tmp_path):
    path = gpx(tmp_path, [[(8.44, 48.8), (8.441, 48.8)]])
    scope = make_scope(gpx=path)
    point = project_geometry(Point(8.44, 48.8))
    assert scope.export.covers(Point(point.x, point.y + 29))
    assert not scope.export.covers(Point(point.x, point.y + 31))
    assert scope.source_camera_geometry.covers(Point(point.x, point.y + 129))
    assert not scope.export.covers(Point(point.x, point.y + 129))
    assert scope.as_dict()["camera_buffer_m"] == 100


def test_gpx_parts_and_large_gaps_are_never_connected(tmp_path):
    path = gpx(tmp_path, [[(8.44, 48.8)], [(8.441, 48.8), (8.45, 48.8)]])
    scope = make_scope(gpx=path)
    assert not scope.export.covers(project_geometry(Point(8.4405, 48.8)))
    assert not scope.export.covers(project_geometry(Point(8.445, 48.8)))
    assert len(scope.metadata["gaps"]) == 2
    assert scope.metadata["endpoint_gap_not_closed"]


def test_context_is_preserved_and_must_contain_entire_corridor(tmp_path):
    path = gpx(tmp_path, [[(8.44, 48.8), (8.441, 48.8)]])
    scope = make_scope(gpx=path, context_bbox=(8.43, 48.79, 8.45, 48.81))
    assert scope.canonical.area > 10 * scope.export.area
    with pytest.raises(ValueError, match="entire export scope"):
        make_scope(gpx=path, context_bbox=(8.44, 48.8, 8.442, 48.801))
    center = project_geometry(Point(8.44, 48.8))
    exact = box(center.x - 1000, center.y - 1000, center.x + 1000, center.y + 1000)
    geometry = mapping(project_geometry(exact, METRIC, WGS84))
    custom = make_scope(gpx=path, context_geometry=geometry)
    assert custom.canonical.symmetric_difference(exact).area < .1


@pytest.mark.parametrize("bbox", [(12.1, 48, 12.2, 49), (8, 46, 9, 48), (9, 49, 8, 48), (8, 48, float('nan'), 49)])
def test_unsupported_bounds_fail(bbox):
    with pytest.raises(ValueError):
        make_scope(bbox=bbox)
