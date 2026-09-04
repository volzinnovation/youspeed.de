import ast
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.tsr.bootstrap_sources import (
    DEFAULT_MANIFEST,
    SourceManifestError,
    describe_artifacts,
    download_artifact,
    select_artifacts,
    validate_manifest,
    verify_artifact,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "tsr" / "bootstrap_sources.py"


def test_repository_manifest_pins_sources_hashes_and_release_gates() -> None:
    manifest = validate_manifest(DEFAULT_MANIFEST)

    assert manifest.sources_by_id["zod-frames-2.0.0"]["revision"]["value"] == "2.0.0"
    assert (
        manifest.sources_by_id["zod-frames-2.0.0"]["revision"]["verification_status"]
        == "pending_provider_access"
    )
    assert (
        manifest.sources_by_id["zod-frames-2.0.0"]["integrity"][
            "post_acquisition_sha256_inventory_required"
        ]
        is True
    )
    assert (
        manifest.sources_by_id["gtsign-220-e235536"]["revision"]["value"]
        == "e235536c26486a42858602b146df40520a75be59"
    )
    assert (
        manifest.artifacts_by_id["synset-signset-germany-archive"]["hashes"]["md5"]
        == "373656812a1d57a899f8289c340544b8"
    )
    assert (
        manifest.artifacts_by_id["synset-signset-germany-archive"]["relative_path"]
        == "datasets/synset-signset-germany/synset-signset-germany.tar"
    )
    assert (
        manifest.artifacts_by_id["synset-signset-germany-archive"]["size_bytes"]
        == 17149598208
    )
    assert (
        manifest.artifacts_by_id["gtsign-220-vit-all-classes"]["hashes"]["sha256"]
        == "e84304a7bbb2a1677c9f4ff9e330262969f1d598da456c8dbe290489bb301bad"
    )
    panoramax_dataset = manifest.sources_by_id["panoramax-de-crops-b485694"]
    assert (
        panoramax_dataset["revision"]["value"]
        == "b4856947ed7cb6312587258acc90e8cf88a4aa13"
    )
    assert panoramax_dataset["license"]["expression"] == "CC-BY-SA-4.0"
    assert panoramax_dataset["license"]["share_alike"] is True
    panoramax_train = manifest.artifacts_by_id["panoramax-de-train-b485694"]
    assert panoramax_train["size_bytes"] == 59887779
    assert (
        panoramax_train["hashes"]["sha256"]
        == "0a7cc5895afd76a4dc98e70efc9421ae82a6f580e6d60da3904911155e424853"
    )
    assert panoramax_train["download"]["url"] == (
        "https://huggingface.co/datasets/Panoramax/classified_de_road_signs/resolve/"
        "b4856947ed7cb6312587258acc90e8cf88a4aa13/train.zip"
    )
    panoramax_validation = manifest.artifacts_by_id["panoramax-de-validation-b485694"]
    assert panoramax_validation["size_bytes"] == 29740678
    assert (
        panoramax_validation["hashes"]["sha256"]
        == "13ca882129a4e024fc865fc4a3187514a4554f8e323f612e338144fd1ff189ea"
    )
    assert panoramax_validation["download"]["url"] == (
        "https://huggingface.co/datasets/Panoramax/classified_de_road_signs/resolve/"
        "b4856947ed7cb6312587258acc90e8cf88a4aa13/val.zip"
    )
    panoramax_classifier_source = manifest.sources_by_id[
        "panoramax-de-classifier-5360aa6"
    ]
    assert (
        panoramax_classifier_source["revision"]["value"]
        == "5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790"
    )
    assert panoramax_classifier_source["license"]["expression"] == "Etalab-2.0"
    assert (
        panoramax_classifier_source["license"]["release_gate"]
        == "panoramax_cc_by_sa_and_ultralytics_review"
    )
    assert "verified=false" in panoramax_classifier_source["integrity"]["note"]
    assert "unsuitable as an acceptance set" in panoramax_dataset["integrity"]["note"]
    panoramax_classifier = manifest.artifacts_by_id[
        "panoramax-de-yolo26-classifier-5360aa6"
    ]
    assert panoramax_classifier["size_bytes"] == 26282865
    assert panoramax_classifier["serialization_risk"] == "pickle_capable_untrusted"
    assert (
        panoramax_classifier["hashes"]["sha256"]
        == "f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7"
    )
    assert panoramax_classifier["download"]["url"] == (
        "https://huggingface.co/Panoramax/classify_de_road_signs/resolve/"
        "5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790/classify_de_road_signs.pt"
    )
    assert (
        panoramax_classifier["release_gate"]
        == "panoramax_cc_by_sa_and_ultralytics_review"
    )
    mobilenet_large = manifest.artifacts_by_id["mobilenetv3-large-ra-in1k-96f46a1"]
    assert mobilenet_large["size_bytes"] == 22058321
    assert mobilenet_large["format"] == "safetensors"
    assert mobilenet_large["serialization_risk"] == "data_only"
    assert (
        mobilenet_large["hashes"]["sha256"]
        == "f425af34cc1cead2b5d6211f789a1f30b94835dc32f9c0fcc5a916e4fd2dde85"
    )
    assert mobilenet_large["release_gate"] == "apache_notice_review"
    assert (
        manifest.sources_by_id["timm-mobilenetv3-large-ra-in1k-96f46a1"]["revision"][
            "value"
        ]
        == "96f46a1c52932f27492dff66c72378eb99b443a7"
    )
    assert (
        manifest.sources_by_id["timm-mobilenetv3-large-ra-in1k-96f46a1"]["license"][
            "expression"
        ]
        == "Apache-2.0"
    )
    assert mobilenet_large["download"]["url"] == (
        "https://huggingface.co/timm/mobilenetv3_large_100.ra_in1k/resolve/"
        "96f46a1c52932f27492dff66c72378eb99b443a7/model.safetensors"
    )
    mobilenet_small = manifest.artifacts_by_id["mobilenetv3-small-lamb-in1k-1824797"]
    assert mobilenet_small["size_bytes"] == 10241912
    assert mobilenet_small["format"] == "safetensors"
    assert mobilenet_small["serialization_risk"] == "data_only"
    assert (
        mobilenet_small["hashes"]["sha256"]
        == "46d2c063b18125884c48937afa4c49e18128869e52e8db96df48bf0a4d7ff697"
    )
    assert mobilenet_small["release_gate"] == "apache_notice_review"
    assert (
        manifest.sources_by_id["timm-mobilenetv3-small-lamb-in1k-1824797"]["revision"][
            "value"
        ]
        == "1824797e7887cbec1990e4adbd6675960a36c589"
    )
    assert (
        manifest.sources_by_id["timm-mobilenetv3-small-lamb-in1k-1824797"]["license"][
            "expression"
        ]
        == "Apache-2.0"
    )
    assert mobilenet_small["download"]["url"] == (
        "https://huggingface.co/timm/mobilenetv3_small_100.lamb_in1k/resolve/"
        "1824797e7887cbec1990e4adbd6675960a36c589/model.safetensors"
    )
    assert (
        manifest.artifacts_by_id["yolox-nano-coco-0.1.1rc0"]["hashes"]["sha256"]
        == "cd28f55fbbc1829f99d9ac9b38a16d259a22889739c8728ea877610201feff7b"
    )
    assert (
        manifest.artifacts_by_id["yolo26n-coco-v8.4.0"]["hashes"]["sha256"]
        == "9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef"
    )
    assert (
        manifest.artifacts_by_id["yolo26n-cls-imagenet-v8.4.0"]["hashes"]["sha256"]
        == "0dd6f8dbc448870ac98a3cbb7156f923f7ce21fed3755d4019169ffffd279e81"
    )
    assert (
        manifest.artifacts_by_id["yolo26n-coco-v8.4.0"]["release_gate"]
        == "ultralytics_agpl_or_enterprise"
    )
    assert (
        manifest.artifacts_by_id["yolo26n-cls-imagenet-v8.4.0"]["release_gate"]
        == "ultralytics_agpl_or_enterprise"
    )
    assert (
        manifest.payload["release_policy"]["license_gates"][
            "ultralytics_agpl_or_enterprise"
        ]["default_decision"]
        == "blocked"
    )
    combined_panoramax_gate = manifest.payload["release_policy"]["license_gates"][
        "panoramax_cc_by_sa_and_ultralytics_review"
    ]
    assert combined_panoramax_gate["default_decision"] == "blocked"
    assert combined_panoramax_gate["requires"] == [
        "attribution_share_alike_review",
        "ultralytics_agpl_or_enterprise",
    ]
    assert "CC-BY-SA-4.0" in combined_panoramax_gate["reason"]
    assert "AGPL-3.0" in combined_panoramax_gate["reason"]
    assert "Enterprise" in combined_panoramax_gate["reason"]
    assert (
        manifest.payload["release_policy"]["license_gates"]["apache_notice_review"][
            "default_decision"
        ]
        == "blocked_pending_weight_and_lineage_review"
    )
    assert manifest.sources_by_id["yolox-0.1.1rc0"]["roles"] == [
        "license_gated_detector_control"
    ]
    assert (
        manifest.artifacts_by_id["yolox-nano-coco-0.1.1rc0"]["role"]
        == "license_gated_detector_control"
    )


def test_artifact_output_requires_exact_explicit_selection() -> None:
    manifest = validate_manifest(DEFAULT_MANIFEST)

    shown = describe_artifacts(manifest, ["yolox-nano-coco-0.1.1rc0"])
    assert [item["artifact_id"] for item in shown["artifacts"]] == [
        "yolox-nano-coco-0.1.1rc0"
    ]
    with pytest.raises(SourceManifestError, match="select at least one"):
        select_artifacts(manifest, [])
    with pytest.raises(SourceManifestError, match="wildcard"):
        select_artifacts(manifest, ["all"])
    with pytest.raises(SourceManifestError, match="unknown artifact_id"):
        select_artifacts(manifest, ["not-in-the-manifest"])


def test_manifest_rejects_unsafe_artifact_path(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    payload["artifacts"][0]["relative_path"] = "../escape.zip"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SourceManifestError, match="cannot contain"):
        validate_manifest(path)


def test_manifest_rejects_download_without_sha256(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    payload["artifacts"][1]["hashes"] = {"md5": "0" * 32}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SourceManifestError, match="needs SHA-256"):
        validate_manifest(path)


def test_manifest_rejects_unblocked_or_incomplete_panoramax_lineage_gate(
    tmp_path: Path,
) -> None:
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    gate = payload["release_policy"]["license_gates"][
        "panoramax_cc_by_sa_and_ultralytics_review"
    ]
    gate["default_decision"] = "allow"
    path = tmp_path / "manifest-unblocked.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SourceManifestError, match="unrecognized default decision"):
        validate_manifest(path)

    gate["default_decision"] = "blocked"
    gate["requires"] = ["attribution_share_alike_review"]
    path = tmp_path / "manifest-incomplete-requires.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SourceManifestError, match="must require"):
        validate_manifest(path)

    gate["requires"] = [
        "attribution_share_alike_review",
        "ultralytics_agpl_or_enterprise",
    ]
    gate["reason"] = "CC-BY-SA-4.0 review only"
    path = tmp_path / "manifest-incomplete.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SourceManifestError, match="dataset share-alike"):
        validate_manifest(path)


def test_manifest_rejects_unblocked_ultralytics_gate(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    payload["release_policy"]["license_gates"]["ultralytics_agpl_or_enterprise"][
        "default_decision"
    ] = "allow"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SourceManifestError, match="unrecognized default decision"):
        validate_manifest(path)


@pytest.mark.parametrize(
    "gate_id",
    [
        "apache_notice_review",
        "attribution_review",
        "attribution_share_alike_review",
    ],
)
def test_manifest_rejects_fail_open_license_gate_decisions(
    tmp_path: Path, gate_id: str
) -> None:
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    payload["release_policy"]["license_gates"][gate_id]["default_decision"] = "allow"
    path = tmp_path / f"manifest-{gate_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SourceManifestError, match="unrecognized default decision"):
        validate_manifest(path)


def test_manifest_binds_huggingface_source_artifact_and_download_revisions(
    tmp_path: Path,
) -> None:
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    source = next(
        item
        for item in payload["sources"]
        if item["source_id"] == "panoramax-de-crops-b485694"
    )
    artifact = next(
        item
        for item in payload["artifacts"]
        if item["artifact_id"] == "panoramax-de-train-b485694"
    )

    source["acquisition"]["locator"] = source["acquisition"]["locator"].replace(
        source["revision"]["value"], "0" * 40
    )
    path = tmp_path / "manifest-source-locator.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SourceManifestError, match="locator must contain"):
        validate_manifest(path)

    source["acquisition"]["locator"] = source["acquisition"]["locator"].replace(
        "0" * 40, source["revision"]["value"]
    )
    artifact["revision"] = "0" * 40
    path = tmp_path / "manifest-artifact-revision.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SourceManifestError, match="revision must match"):
        validate_manifest(path)

    artifact["revision"] = source["revision"]["value"]
    artifact["download"]["url"] = artifact["download"]["url"].replace(
        source["revision"]["value"], "0" * 40
    )
    path = tmp_path / "manifest-download-revision.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SourceManifestError, match="must resolve its pinned"):
        validate_manifest(path)


@pytest.mark.parametrize(
    ("artifact_format", "serialization_risk", "expected_error"),
    [
        (
            "pytorch_checkpoint",
            "data_only",
            "pytorch_checkpoint must use serialization risk",
        ),
        ("safetensors", "data_only", "pickle-capable checkpoint must remain"),
    ],
)
def test_manifest_keeps_pt_checkpoints_opaque_and_untrusted(
    tmp_path: Path,
    artifact_format: str,
    serialization_risk: str,
    expected_error: str,
) -> None:
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    artifact = next(
        item
        for item in payload["artifacts"]
        if item["artifact_id"] == "panoramax-de-yolo26-classifier-5360aa6"
    )
    artifact["format"] = artifact_format
    artifact["serialization_risk"] = serialization_risk
    path = tmp_path / f"manifest-{artifact_format}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SourceManifestError, match=expected_error):
        validate_manifest(path)


def _artifact_for(data: bytes, **overrides: Any) -> dict[str, Any]:
    artifact: dict[str, Any] = {
        "artifact_id": "fixture-model",
        "relative_path": "models/fixture/model.safetensors",
        "size_bytes": len(data),
        "hashes": {"sha256": hashlib.sha256(data).hexdigest()},
        "download": {
            "allowed": True,
            "url": "https://models.example.test/model.safetensors",
            "allowed_hosts": ["models.example.test"],
        },
    }
    artifact.update(overrides)
    return artifact


def test_verify_predownloaded_artifact_checks_size_and_hash(tmp_path: Path) -> None:
    data = b"safe opaque checkpoint bytes"
    artifact = _artifact_for(data)
    path = tmp_path / artifact["relative_path"]
    path.parent.mkdir(parents=True)
    path.write_bytes(data)

    result = verify_artifact(artifact, tmp_path)
    assert result["verified"] is True
    assert result["hashes"]["sha256"] == hashlib.sha256(data).hexdigest()

    path.write_bytes(data + b"tampered")
    with pytest.raises(SourceManifestError, match="size mismatch"):
        verify_artifact(artifact, tmp_path)


class _FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, url: str) -> None:
        super().__init__(data)
        self._url = url
        self.headers = {"Content-Length": str(len(data))}

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_download_streams_and_hashes_selected_bytes_without_loading_model(
    tmp_path: Path,
) -> None:
    data = b"opaque model bytes only"
    artifact = _artifact_for(data)
    calls: list[str] = []

    def opener(request: Any, *, timeout: int) -> _FakeResponse:
        assert timeout == 60
        calls.append(request.full_url)
        return _FakeResponse(data, "https://models.example.test/model.safetensors")

    result = download_artifact(artifact, tmp_path, opener=opener)

    assert calls == [artifact["download"]["url"]]
    assert result["downloaded"] is True
    assert (tmp_path / artifact["relative_path"]).read_bytes() == data


def test_download_rejects_manual_artifact_and_unapproved_redirect(
    tmp_path: Path,
) -> None:
    data = b"content"
    manual = _artifact_for(data)
    manual["download"] = {"allowed": False, "url": None, "allowed_hosts": []}
    with pytest.raises(SourceManifestError, match="manual acquisition"):
        download_artifact(manual, tmp_path)

    artifact = _artifact_for(data)

    def redirecting_opener(_request: Any, *, timeout: int) -> _FakeResponse:
        assert timeout == 60
        return _FakeResponse(data, "https://attacker.example.test/model.safetensors")

    with pytest.raises(SourceManifestError, match="unapproved host"):
        download_artifact(artifact, tmp_path, opener=redirecting_opener)
    assert not (tmp_path / artifact["relative_path"]).exists()


def test_bootstrap_tool_never_imports_pickle_or_model_frameworks() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert "pickle" not in imported_roots
    assert "torch" not in imported_roots
    assert "ultralytics" not in imported_roots
