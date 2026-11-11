from datetime import date
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from xml.etree import ElementTree

import pytest
from shapely.geometry import box, mapping

from inspector.sign_wfs import SignWFSError, query_snapshot
from scripts.inspector.build_city_sign_wfs import build, features, previous_dates


def group(identifier, longitude):
    return {
        "id": identifier, "sign_code": "DE:205",
        "proposal": {
            "longitude": longitude, "latitude": 48.8, "azimut_deg": 270,
            "position_status": "adjacent_track_review",
        },
        "observations": [{"image_id": "source", "captured_at": "2026-11-02T01:00:00+02:00"}],
        "follow_on_observations": [{"image_id": "source", "captured_at": "2026-11-03T00:00:00Z"}],
    }


def test_features_preserve_discovery_and_use_resolved_municipal_pose():
    candidate = group("a" * 32, 8.4)
    candidate["mobile_refinement"] = {
        "status": "refined",
        "mobile_evidence_ids": ["used"],
        "proposal": {**candidate["proposal"], "longitude": 8.41, "azimut_deg": 180,
                     "position_status": "mobile_refinement"},
    }
    candidate["mobile_observations"] = [
        {"evidence_id": "used", "captured_at": "2026-11-04T00:00:00Z"},
        {"evidence_id": "unused", "captured_at": "2026-09-01T00:00:00Z"},
    ]
    missing = {**group("c" * 32, 8.4), "proposal": None}
    document = {"groups": [candidate, group("b" * 32, 8.5), missing]}
    boundary = box(8.3, 48.7, 8.45, 48.9)
    rows, counts = features(document, "08235033", boundary, {})
    assert counts == {"features": 1, "missing_azimuth": 0, "mobile_refined": 1,
                      "outside_municipality": 1, "unresolved": 1}
    fields = rows[0]["properties"]
    assert fields["first_discovered_on"] == "2026-11-01"
    assert fields["datum"] == "2026-11-04"
    assert fields["azimut"] == 0
    assert fields["sighting_count"] == 2
    assert fields["source_types"] == "panoramax,mobile"
    assert fields["img"] is None
    assert rows[0]["geometry"]["coordinates"] == (fields["ost"], fields["nord"])
    rows, _ = features(document, "08235033", boundary, {"a" * 32: "2026-10-01"})
    assert rows[0]["properties"]["first_discovered_on"] == "2026-10-01"


@pytest.fixture
def snapshot_inputs(tmp_path):
    directory = tmp_path / "wfs"
    boundaries = tmp_path / "boundaries.json"
    reviews = {}
    polygons = []
    for index, (ags, city, lon) in enumerate(
        (("08235033", "Bad Herrenalb", 8.4), ("08231000", "Pforzheim", 8.7)), 1
    ):
        boundary = mapping(box(lon - .04, 48.75, lon + .04, 48.85))
        path = tmp_path / f"{ags}.json"
        path.write_text(json.dumps({"place": {"name": city, "boundary_wgs84": boundary},
                                    "groups": [group(str(index) * 32, lon)]}))
        path.chmod(0o600)
        reviews[ags] = path
        polygons.append({"type": "Feature", "geometry": boundary,
                         "properties": {"kind": "gemeinde_ags", "id": ags}})
    boundaries.write_text(json.dumps({"type": "FeatureCollection", "features": polygons}))
    return directory, boundaries, reviews


def test_failed_update_keeps_previous_snapshot(snapshot_inputs):
    directory, boundaries, reviews = snapshot_inputs
    build(*snapshot_inputs)
    data = directory / "verkehrszeichen.gpkg"
    original = data.read_bytes()
    path = reviews["08231000"]
    review = json.loads(path.read_text())
    review["groups"].clear()
    path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="empty snapshot"):
        build(directory, boundaries, reviews)
    assert data.read_bytes() == original
    assert previous_dates(data) == {"1" * 32: "2026-11-01", "2" * 32: "2026-11-01"}


def test_cgi_rejects_file_overrides_and_non_wfs_requests(tmp_path):
    for query in (
        "SERVICE=WFS&REQUEST=GetFeature&map=other",
        "SERVICE=WFS&REQUEST=GetFeature&request=GetCapabilities",
        "SERVICE=WMS&REQUEST=GetCapabilities",
        "SERVICE=WFS&REQUEST=Transaction",
    ):
        with pytest.raises(SignWFSError) as error:
            query_snapshot(tmp_path / "mapserv", tmp_path / "mapserver.conf", "localhost:8769", query)
        assert error.value.status == 400


def test_native_wfs_filters_city_and_exposes_schema(snapshot_inputs):
    executable = os.environ.get("YOUSPEED_WFS_MAPSERV")
    if not executable:
        pytest.skip("set YOUSPEED_WFS_MAPSERV to a MapServer 8 CGI executable")
    directory, _, reviews = snapshot_inputs
    build(*snapshot_inputs)

    def get(request, **fields):
        query = urlencode({"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": request, **fields})
        body, content_type, status = query_snapshot(
            Path(executable), directory / "mapserver.conf", "localhost:8769", query,
        )
        assert status == 200
        return body, content_type

    layer = "youspeed:verkehrszeichen"
    capabilities, _ = get("GetCapabilities")
    assert ElementTree.fromstring(capabilities).tag.endswith("WFS_Capabilities")
    schema, _ = get("DescribeFeatureType", TYPENAMES=layer)
    assert b'first_discovered_on' in schema
    for ags in reviews:
        filter_xml = (
            '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0">'
            '<fes:PropertyIsEqualTo><fes:ValueReference>gemeinde_ags</fes:ValueReference>'
            f'<fes:Literal>{ags}</fes:Literal></fes:PropertyIsEqualTo></fes:Filter>'
        )
        body, content_type = get("GetFeature", TYPENAMES=layer, OUTPUTFORMAT="geojson", FILTER=filter_xml)
        assert content_type == "application/geo+json"
        [feature] = json.loads(body)["features"]
        assert feature["properties"]["gemeinde_ags"] == ags
        assert date.fromisoformat(feature["properties"]["first_discovered_on"]) == date(2026, 11, 1)
        assert feature["geometry"]["coordinates"][1] == pytest.approx(48.8)
        gml, _ = get("GetFeature", TYPENAMES=layer, FILTER=filter_xml)
        root = ElementTree.fromstring(gml)
        assert root.attrib["numberReturned"] == "1"
        assert root.find(".//{https://youspeed.de/ns/verkehrszeichen/1}gemeinde_ags").text == ags
