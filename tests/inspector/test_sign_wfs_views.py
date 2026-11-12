import json
import os
from pathlib import Path
from urllib.parse import urlencode

import fiona
import pytest
from shapely.geometry import box, shape

from inspector.sign_wfs import query_snapshot
from scripts.inspector.build_city_sign_wfs import FIELDS, features, write_snapshot
from scripts.inspector.sign_wfs_views import create_view, digest


@pytest.fixture
def canonical(tmp_path):
    rows = []
    for index, (lon, ags) in enumerate(((8.40, "08235033"), (8.41, "08231000"), (8.42, "08231000")), 1):
        group = {"id": str(index) * 32, "sign_code": "DE:205", "proposal": {
            "longitude": lon, "latitude": 48.8, "azimut_deg": 270, "position_status": "nominal_review"},
            "observations": [{"image_id": str(index), "captured_at": "2026-11-02T00:00:00Z"}]}
        exported, _ = features({"groups": [group]}, ags, box(8.3, 48.7, 8.5, 48.9), {})
        rows.extend(exported)
    directory = tmp_path / "canonical"
    write_snapshot(directory, rows)
    return directory, rows


def test_view_references_one_immutable_canonical_file(canonical, tmp_path):
    directory, rows = canonical
    package = directory / "verkehrszeichen.gpkg"
    before = digest(package)
    create_view(directory, tmp_path / "area")
    create_view(directory, tmp_path / "loop", ["1" * 32, "3" * 32])
    text = (tmp_path / "loop/verkehrszeichen.map").read_text()
    assert 'FILTER (("[id]" = "' in text
    assert str(package) in text
    assert not list((tmp_path / "loop").glob("*.gpkg"))
    assert digest(package) == before
    create_view(directory, tmp_path / "loop", ["3" * 32, "1" * 32])
    with pytest.raises(ValueError, match="immutable"):
        create_view(directory, tmp_path / "loop", ["1" * 32])
    for path in (tmp_path / "loop").iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
    with fiona.open(package) as source:
        assert dict(source.schema["properties"]) == FIELDS


@pytest.mark.parametrize("ids", [["unknown"], ["f" * 32], ["1" * 32, "1" * 32]])
def test_invalid_view_membership_is_rejected(canonical, tmp_path, ids):
    with pytest.raises(ValueError):
        create_view(canonical[0], tmp_path / "invalid", ids)
    assert not (tmp_path / "invalid").exists()


def test_native_subset_and_fes_bbox_queries_preserve_all_properties(canonical, tmp_path):
    executable = os.environ.get("YOUSPEED_WFS_MAPSERV")
    if not executable:
        pytest.skip("set YOUSPEED_WFS_MAPSERV to a native MapServer 8 CGI executable")
    directory, rows = canonical
    for name, ids in (("area", None), ("loop", ["1" * 32, "3" * 32]), ("empty", [])):
        create_view(directory, tmp_path / name, ids)

    def get(name, **extra):
        query = urlencode({"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
                           "TYPENAMES": "youspeed:verkehrszeichen", "OUTPUTFORMAT": "geojson", **extra})
        body, content_type, status = query_snapshot(Path(executable), tmp_path / name / "mapserver.conf", "localhost:8769", query)
        assert status == 200
        assert content_type == "application/geo+json"
        return {row["properties"]["id"]: row for row in json.loads(body)["features"]}

    area, loop = get("area"), get("loop")
    assert set(loop) == {"1" * 32, "3" * 32}
    assert loop == {key: area[key] for key in loop}
    assert get("empty") == {}
    for ags, expected in (("08235033", {"1" * 32}), ("08231000", {"3" * 32})):
        fes = ('<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0"><fes:PropertyIsEqualTo>'
               '<fes:ValueReference>gemeinde_ags</fes:ValueReference>'
               f'<fes:Literal>{ags}</fes:Literal></fes:PropertyIsEqualTo></fes:Filter>')
        filtered = get("loop", FILTER=fes)
        assert set(filtered) == expected
        assert filtered == {key: area[key] for key in expected}
    # Both endpoints must apply an incoming spatial filter after the permanent
    # ID membership filter, including exclusion of its first OR branch.
    east, north = rows[2]["geometry"]["coordinates"]
    bbox = f"{east-10},{north-10},{east+10},{north+10},urn:ogc:def:crs:EPSG::25832"
    assert get("loop", BBOX=bbox) == get("area", BBOX=bbox) == {"3" * 32: area["3" * 32]}
