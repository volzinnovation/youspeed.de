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
        manifest.artifacts_by_id["gtsign-220-vit-all-classes"]["hashes"]["sha256"]
        == "e84304a7bbb2a1677c9f4ff9e330262969f1d598da456c8dbe290489bb301bad"
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
