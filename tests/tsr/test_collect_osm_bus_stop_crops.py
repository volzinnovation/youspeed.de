"""Protection and panorama handling for the bounded OSM-guided collector."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

SPEC = importlib.util.spec_from_file_location(
    "bus_collector", Path(__file__).parents[2] / "scripts/tsr/collect_osm_bus_stop_crops.py")
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def test_protection_matches_prefixed_sequence_and_geography(tmp_path):
    path = tmp_path / "holdout.json"
    path.write_text(json.dumps({"samples": [{"source_id": "old-picture", "group_id": "collection:held-route",
                                           "coordinates": [8.4, 49.0], "rgb_sha256": "abc"}]}))
    protected = collector.protection([path])
    assert collector.excluded({"route_tokens": ["held-route"]}, protected) == ["protected_picture_or_route"]
    assert collector.excluded({"coordinates": [8.4001, 49.0001]}, protected) == ["protected_250m_geography"]
    assert collector.excluded({"route_tokens": ["new-route"], "coordinates": [8.6, 49.0]}, protected) == []
    assert "abc" in protected["pixels"]


def test_panoramax_projection_uses_real_primary_metadata_keys():
    assert collector.panoramax_is_pano({"exif": {"Xmp.GPano.ProjectionType": "equirectangular"}})
    assert collector.panoramax_is_pano({"pers:interior_orientation": {"field_of_view": 360}})
    assert collector.panoramax_is_pano({"proj:type": "equirectangular"})
    assert not collector.panoramax_is_pano({"pers:interior_orientation": {"field_of_view": 110}})


def test_panorama_behind_camera_survives_but_no_osm_truth_is_assigned(tmp_path):
    anchor = {"osm_type": "node", "osm_id": 1, "coordinates": [8.4, 49.0001]}
    feature = {"id": "photo", "collection": "route", "geometry": {"coordinates": [8.4, 49.0]},
               "properties": {"view:azimuth": 180, "exif": {"Xmp.GPano.ProjectionType": "equirectangular"},
                              "geovisio:visibility": "anyone", "geovisio:status": "ready"},
               "assets": {"sd": {"href": "https://example.org/photo.jpg"}},
               "links": [{"rel": "via", "href": "https://example.org"},
                         {"rel": "self", "href": "https://index.example.org/api/pictures/photo"}]}
    path = tmp_path / "queries/federated-node-1.json"
    collector.write(path, {"features": [feature]})
    args = SimpleNamespace(output=tmp_path, radius=45)
    protected = {"ids": set(), "coordinates": [], "pixels": set()}
    rows, _ = collector.query_provider("federated", anchor, args, protected, None)
    assert len(rows) == 1 and rows[0]["is_pano"]
    assert rows[0]["label"] is None and not rows[0]["human_approved"]
    assert rows[0]["training_only"] and not rows[0]["evaluation_eligible"]
    assert rows[0]["source_url"] == "https://example.org/api/pictures/photo"
    feature["properties"]["exif"] = {}
    collector.write(path, {"features": [feature]})
    assert collector.query_provider("federated", anchor, args, protected, None)[0] == []


def test_http_auth_error_never_contains_secret_or_message():
    import io
    error = collector.HTTPError("https://example.org/?access_token=secret", 500, "secret", {},
                                io.BytesIO(b'{"error":{"code":190,"type":"MLYApiException","message":"secret"}}'))
    safe = collector.safe_error(error)
    assert safe["provider_error"]["code"] == 190
    assert "secret" not in json.dumps(safe)


@pytest.mark.parametrize("change", ["private", "moved", "different_route", "not_ready"])
def test_remote_stage_rejects_changed_source_before_opening_pixels(change, monkeypatch, capsys, tmp_path):
    import ast
    import io
    import urllib.request
    from PIL import Image
    tree = ast.parse((Path(__file__).parents[2] / "scripts/tsr/stage_osm_bus_stop_remote.py").read_text())
    program = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                   and any(getattr(target, "id", "") == "REMOTE" for target in node.targets))
    program = program.replace("/tmp/youspeed-osm-de224-staged", str(tmp_path / "remote"))
    metadata = {"id": "picture", "collection": "route", "geometry": {"coordinates": [8.4, 49.0]},
                "properties": {"geovisio:visibility": "anyone", "geovisio:status": "ready"}}
    if change == "private": metadata["properties"]["geovisio:visibility"] = "private"
    if change == "moved": metadata["geometry"]["coordinates"] = [8.7, 49.1]
    if change == "different_route": metadata["collection"] = "protected-route"
    if change == "not_ready": metadata["properties"]["geovisio:status"] = "processing"
    calls = []
    def network(request, timeout):
        calls.append(request.full_url)
        return io.BytesIO(json.dumps(metadata).encode())
    monkeypatch.setattr(urllib.request, "urlopen", network)
    def no_pixels(*args, **kwargs):
        pytest.fail("Changed source pixels must never be opened")
    monkeypatch.setattr(Image, "open", no_pixels)
    exec(program, {"PLAN": [{"source_id": "picture", "source_url": "https://example.org/api/pictures/picture",
                             "sequence_id": "route", "coordinates": [8.4, 49.0]}]})
    result = json.loads(capsys.readouterr().out)
    assert result == [{"source_id": "picture", "error_type": "AssertionError"}]
    assert len(calls) == 1
