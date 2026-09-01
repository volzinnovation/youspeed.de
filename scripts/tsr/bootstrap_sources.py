#!/usr/bin/env python3
"""Validate and fetch explicitly selected, pinned TSR bootstrap artifacts.

This utility is intentionally a byte-level tool. It validates metadata,
downloads selected artifacts, and verifies hashes; it never imports a model
framework or deserializes a checkpoint. In particular, ``.pt`` and ``.pth``
files are treated as untrusted opaque bytes because they may use pickle-based
serialization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "shared" / "tsr" / "training-sources-v1.json"
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
HASH_PATTERNS = {
    "md5": re.compile(r"^[a-f0-9]{32}$"),
    "sha256": re.compile(r"^[a-f0-9]{64}$"),
}
SERIALIZATION_RISKS = {"data_archive", "data_only", "pickle_capable_untrusted"}


class SourceManifestError(ValueError):
    """Raised when source metadata or a selected artifact is unsafe."""


@dataclass(frozen=True)
class ValidatedSourceManifest:
    path: Path
    payload: dict[str, Any]
    sources_by_id: Mapping[str, dict[str, Any]]
    artifacts_by_id: Mapping[str, dict[str, Any]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceManifestError(message)


def _safe_relative_path(value: Any, field: str) -> Path:
    _require(isinstance(value, str) and value, f"{field} must be a non-empty path")
    relative = Path(value)
    _require(not relative.is_absolute(), f"{field} must be relative")
    _require(".." not in relative.parts, f"{field} cannot contain '..'")
    _require(
        relative.parts and all(part not in {"", "."} for part in relative.parts),
        f"{field} is not normalized",
    )
    return relative


def _https_host(value: Any, field: str) -> str:
    _require(isinstance(value, str) and value, f"{field} must be a non-empty URL")
    parsed = urlparse(value)
    _require(parsed.scheme == "https", f"{field} must use HTTPS")
    _require(parsed.hostname is not None, f"{field} must contain a host")
    _require(
        parsed.username is None and parsed.password is None,
        f"{field} cannot contain credentials",
    )
    return parsed.hostname.lower()


def validate_manifest(path: Path | str = DEFAULT_MANIFEST) -> ValidatedSourceManifest:
    manifest_path = Path(path).expanduser().resolve()
    _require(manifest_path.is_file(), f"missing source manifest: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SourceManifestError(f"cannot read {manifest_path}: {error}") from error

    _require(isinstance(payload, dict), "source manifest must be an object")
    _require(payload.get("schema_version") == 1, "unsupported source manifest schema")
    _require(
        payload.get("manifest_id") == "youspeed-tsr-training-sources-v1",
        "unexpected manifest id",
    )

    release_policy = payload.get("release_policy")
    _require(isinstance(release_policy, dict), "release_policy is required")
    _require(
        release_policy.get("default") == "blocked_until_every_lineage_gate_is_approved",
        "release_policy must default to blocked",
    )
    requirements = release_policy.get("requirements")
    _require(
        isinstance(requirements, list) and requirements,
        "release requirements are required",
    )
    _require(
        all(isinstance(item, str) and item for item in requirements),
        "release requirements must be strings",
    )
    license_gates = release_policy.get("license_gates")
    _require(
        isinstance(license_gates, dict) and license_gates, "license gates are required"
    )
    _require(
        license_gates.get("ultralytics_agpl_or_enterprise", {}).get("default_decision")
        == "blocked",
        "the Ultralytics gate must be blocked by default",
    )

    sources = payload.get("sources")
    _require(isinstance(sources, list) and sources, "sources must be a non-empty array")
    sources_by_id: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(sources):
        field = f"sources[{index}]"
        _require(isinstance(source, dict), f"{field} must be an object")
        source_id = source.get("source_id")
        _require(
            isinstance(source_id, str) and SAFE_ID.fullmatch(source_id) is not None,
            f"{field}.source_id is invalid",
        )
        _require(source_id not in sources_by_id, f"duplicate source_id {source_id}")
        _require(
            source.get("kind") in {"dataset", "model_framework"},
            f"{field}.kind is invalid",
        )
        roles = source.get("roles")
        _require(isinstance(roles, list) and roles, f"{field}.roles must be non-empty")
        _require(
            all(isinstance(role, str) and SAFE_ID.fullmatch(role) for role in roles),
            f"{field}.roles are invalid",
        )
        _https_host(source.get("homepage"), f"{field}.homepage")

        revision = source.get("revision")
        _require(isinstance(revision, dict), f"{field}.revision is required")
        _require(
            isinstance(revision.get("kind"), str) and revision["kind"],
            f"{field}.revision.kind is required",
        )
        _require(
            isinstance(revision.get("value"), str) and revision["value"],
            f"{field}.revision.value is required",
        )

        license_info = source.get("license")
        _require(isinstance(license_info, dict), f"{field}.license is required")
        _require(
            isinstance(license_info.get("expression"), str)
            and license_info["expression"],
            f"{field}.license.expression is required",
        )
        _https_host(license_info.get("url"), f"{field}.license.url")
        release_gate = license_info.get("release_gate")
        _require(
            release_gate in license_gates,
            f"{field} references unknown release gate {release_gate}",
        )
        _require(
            type(license_info.get("notice_required")) is bool,
            f"{field}.license.notice_required must be boolean",
        )
        _require(
            type(license_info.get("share_alike")) is bool,
            f"{field}.license.share_alike must be boolean",
        )

        acquisition = source.get("acquisition")
        _require(isinstance(acquisition, dict), f"{field}.acquisition is required")
        _require(
            isinstance(acquisition.get("mode"), str) and acquisition["mode"],
            f"{field}.acquisition.mode is required",
        )
        _https_host(acquisition.get("locator"), f"{field}.acquisition.locator")

        integrity = source.get("integrity")
        _require(isinstance(integrity, dict), f"{field}.integrity is required")
        _require(
            type(integrity.get("immutable_reference")) is bool,
            f"{field}.integrity.immutable_reference must be boolean",
        )
        _require(
            type(integrity.get("post_acquisition_sha256_inventory_required")) is bool,
            f"{field}.integrity.post_acquisition_sha256_inventory_required must be boolean",
        )
        published_checksum = integrity.get("published_aggregate_checksum")
        if published_checksum is not None:
            _require(
                isinstance(published_checksum, str) and ":" in published_checksum,
                f"{field} has an invalid published checksum",
            )
            algorithm, value = published_checksum.split(":", 1)
            _require(
                algorithm in HASH_PATTERNS
                and HASH_PATTERNS[algorithm].fullmatch(value) is not None,
                f"{field} has an invalid published checksum",
            )
        sources_by_id[source_id] = source

    artifacts = payload.get("artifacts")
    _require(
        isinstance(artifacts, list) and artifacts, "artifacts must be a non-empty array"
    )
    artifacts_by_id: dict[str, dict[str, Any]] = {}
    for index, artifact in enumerate(artifacts):
        field = f"artifacts[{index}]"
        _require(isinstance(artifact, dict), f"{field} must be an object")
        artifact_id = artifact.get("artifact_id")
        _require(
            isinstance(artifact_id, str) and SAFE_ID.fullmatch(artifact_id) is not None,
            f"{field}.artifact_id is invalid",
        )
        _require(
            artifact_id not in artifacts_by_id, f"duplicate artifact_id {artifact_id}"
        )
        source_id = artifact.get("source_id")
        _require(
            source_id in sources_by_id,
            f"{field} references unknown source_id {source_id}",
        )
        _require(
            isinstance(artifact.get("role"), str)
            and SAFE_ID.fullmatch(artifact["role"]),
            f"{field}.role is invalid",
        )
        _require(
            isinstance(artifact.get("revision"), str) and artifact["revision"],
            f"{field}.revision is required",
        )
        _safe_relative_path(artifact.get("relative_path"), f"{field}.relative_path")
        size_bytes = artifact.get("size_bytes")
        _require(
            size_bytes is None or (type(size_bytes) is int and size_bytes > 0),
            f"{field}.size_bytes is invalid",
        )
        _require(
            isinstance(artifact.get("format"), str) and artifact["format"],
            f"{field}.format is required",
        )
        _require(
            artifact.get("serialization_risk") in SERIALIZATION_RISKS,
            f"{field}.serialization_risk is invalid",
        )

        hashes = artifact.get("hashes")
        _require(
            isinstance(hashes, dict) and hashes, f"{field}.hashes must be non-empty"
        )
        for algorithm, value in hashes.items():
            _require(
                algorithm in HASH_PATTERNS, f"{field} uses unsupported hash {algorithm}"
            )
            _require(
                isinstance(value, str)
                and HASH_PATTERNS[algorithm].fullmatch(value) is not None,
                f"{field}.{algorithm} is invalid",
            )

        release_gate = artifact.get("release_gate")
        _require(
            release_gate in license_gates,
            f"{field} references unknown release gate {release_gate}",
        )
        _require(
            release_gate == sources_by_id[source_id]["license"]["release_gate"],
            f"{field} release gate differs from source {source_id}",
        )

        download = artifact.get("download")
        _require(isinstance(download, dict), f"{field}.download is required")
        allowed = download.get("allowed")
        _require(type(allowed) is bool, f"{field}.download.allowed must be boolean")
        allowed_hosts = download.get("allowed_hosts")
        _require(
            isinstance(allowed_hosts, list),
            f"{field}.download.allowed_hosts must be an array",
        )
        _require(
            all(
                isinstance(host, str) and host == host.lower() and host
                for host in allowed_hosts
            ),
            f"{field}.download.allowed_hosts is invalid",
        )
        if allowed:
            initial_host = _https_host(download.get("url"), f"{field}.download.url")
            _require(
                initial_host in allowed_hosts,
                f"{field}.download.allowed_hosts must include the source host",
            )
            _require(
                type(size_bytes) is int and size_bytes > 0,
                f"{field} needs an exact size before download",
            )
            _require("sha256" in hashes, f"{field} needs SHA-256 before download")
        else:
            _require(
                download.get("url") is None,
                f"{field} disabled download must not contain a URL",
            )
            _require(
                not allowed_hosts,
                f"{field} disabled download must not contain allowed hosts",
            )
        artifacts_by_id[artifact_id] = artifact

    return ValidatedSourceManifest(
        path=manifest_path,
        payload=payload,
        sources_by_id=sources_by_id,
        artifacts_by_id=artifacts_by_id,
    )


def select_artifacts(
    manifest: ValidatedSourceManifest,
    artifact_ids: Sequence[str],
) -> list[dict[str, Any]]:
    _require(bool(artifact_ids), "select at least one artifact id")
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for artifact_id in artifact_ids:
        _require(
            artifact_id != "all" and artifact_id != "*",
            "wildcard artifact selection is not allowed",
        )
        _require(
            artifact_id not in seen, f"duplicate selected artifact_id {artifact_id}"
        )
        artifact = manifest.artifacts_by_id.get(artifact_id)
        _require(artifact is not None, f"unknown artifact_id {artifact_id}")
        seen.add(artifact_id)
        selected.append(artifact)
    return selected


def describe_artifacts(
    manifest: ValidatedSourceManifest,
    artifact_ids: Sequence[str],
) -> dict[str, Any]:
    artifacts = select_artifacts(manifest, artifact_ids)
    return {
        "manifest_id": manifest.payload["manifest_id"],
        "artifacts": [
            {
                **artifact,
                "source": {
                    "name": manifest.sources_by_id[artifact["source_id"]]["name"],
                    "revision": manifest.sources_by_id[artifact["source_id"]][
                        "revision"
                    ],
                    "license": manifest.sources_by_id[artifact["source_id"]]["license"],
                },
            }
            for artifact in artifacts
        ],
    }


def _artifact_path(root: Path | str, artifact: Mapping[str, Any]) -> Path:
    root_path = Path(root).expanduser()
    root_path.mkdir(parents=True, exist_ok=True)
    resolved_root = root_path.resolve()
    relative = _safe_relative_path(artifact["relative_path"], "artifact.relative_path")
    current = resolved_root
    for part in relative.parts:
        current = current / part
        _require(
            not current.is_symlink(), f"artifact path cannot traverse symlink {current}"
        )
    resolved = (resolved_root / relative).resolve(strict=False)
    _require(resolved_root in resolved.parents, "artifact path escapes output root")
    return resolved


def _hashes_for_file(path: Path, algorithms: Sequence[str]) -> dict[str, str]:
    digests = {algorithm: hashlib.new(algorithm) for algorithm in algorithms}
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            for digest in digests.values():
                digest.update(chunk)
    return {algorithm: digest.hexdigest() for algorithm, digest in digests.items()}


def verify_artifact(artifact: Mapping[str, Any], root: Path | str) -> dict[str, Any]:
    path = _artifact_path(root, artifact)
    _require(path.is_file(), f"missing artifact {artifact['artifact_id']}: {path}")
    _require(not path.is_symlink(), f"artifact cannot be a symlink: {path}")
    actual_size = path.stat().st_size
    expected_size = artifact["size_bytes"]
    if expected_size is not None:
        _require(
            actual_size == expected_size,
            f"size mismatch for {artifact['artifact_id']}: expected {expected_size}, got {actual_size}",
        )
    actual_hashes = _hashes_for_file(path, list(artifact["hashes"]))
    for algorithm, expected in artifact["hashes"].items():
        _require(
            actual_hashes[algorithm] == expected,
            f"{algorithm} mismatch for {artifact['artifact_id']}",
        )
    return {
        "artifact_id": artifact["artifact_id"],
        "path": str(path),
        "size_bytes": actual_size,
        "hashes": actual_hashes,
        "verified": True,
    }


def download_artifact(
    artifact: Mapping[str, Any],
    root: Path | str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    destination = _artifact_path(root, artifact)
    if destination.exists():
        result = verify_artifact(artifact, root)
        result["downloaded"] = False
        return result

    download = artifact["download"]
    _require(
        download["allowed"] is True,
        f"artifact {artifact['artifact_id']} requires manual acquisition",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        download["url"],
        headers={"User-Agent": "YouSpeed-TSR-bootstrap/1"},
    )
    temporary_path: Path | None = None
    try:
        with opener(request, timeout=60) as response:
            final_url = response.geturl()
            final_host = _https_host(final_url, "download redirect")
            _require(
                final_host in download["allowed_hosts"],
                f"download redirected to unapproved host {final_host}",
            )
            expected_size = artifact["size_bytes"]
            header_value = response.headers.get("Content-Length")
            if header_value is not None:
                _require(header_value.isdigit(), "download Content-Length is invalid")
                _require(
                    int(header_value) == expected_size,
                    f"download Content-Length mismatch for {artifact['artifact_id']}",
                )

            digests = {
                algorithm: hashlib.new(algorithm) for algorithm in artifact["hashes"]
            }
            written = 0
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".part",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    _require(
                        written <= expected_size,
                        f"download exceeds declared size for {artifact['artifact_id']}",
                    )
                    handle.write(chunk)
                    for digest in digests.values():
                        digest.update(chunk)
                handle.flush()
                os.fsync(handle.fileno())

            _require(
                written == expected_size,
                f"download size mismatch for {artifact['artifact_id']}: expected {expected_size}, got {written}",
            )
            for algorithm, expected in artifact["hashes"].items():
                _require(
                    digests[algorithm].hexdigest() == expected,
                    f"{algorithm} mismatch for {artifact['artifact_id']}",
                )
        os.replace(temporary_path, destination)
        temporary_path = None
    except SourceManifestError:
        raise
    except (OSError, ValueError) as error:
        raise SourceManifestError(
            f"cannot download {artifact['artifact_id']}: {error}"
        ) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    result = verify_artifact(artifact, root)
    result["downloaded"] = True
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", default=str(DEFAULT_MANIFEST), help="pinned source manifest"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "validate",
        help="validate source metadata without selecting or downloading artifacts",
    )

    show_parser = subparsers.add_parser(
        "show", help="print only explicitly selected artifact records"
    )
    show_parser.add_argument(
        "artifact_ids", nargs="+", help="exact artifact ids; wildcards are rejected"
    )

    verify_parser = subparsers.add_parser(
        "verify", help="verify explicitly selected predownloaded artifacts"
    )
    verify_parser.add_argument("--root", required=True, help="artifact storage root")
    verify_parser.add_argument(
        "artifact_ids", nargs="+", help="exact artifact ids; wildcards are rejected"
    )

    download_parser = subparsers.add_parser(
        "download", help="download explicitly selected public artifacts"
    )
    download_parser.add_argument("--root", required=True, help="artifact storage root")
    download_parser.add_argument(
        "artifact_ids", nargs="+", help="exact artifact ids; wildcards are rejected"
    )

    args = parser.parse_args(argv)
    try:
        manifest = validate_manifest(args.manifest)
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "valid": True,
                        "manifest_id": manifest.payload["manifest_id"],
                        "source_count": len(manifest.sources_by_id),
                        "artifact_count": len(manifest.artifacts_by_id),
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "show":
            print(
                json.dumps(
                    describe_artifacts(manifest, args.artifact_ids),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        selected = select_artifacts(manifest, args.artifact_ids)
        if args.command == "verify":
            results = [verify_artifact(artifact, args.root) for artifact in selected]
        else:
            results = [download_artifact(artifact, args.root) for artifact in selected]
        print(json.dumps({"artifacts": results}, indent=2, sort_keys=True))
        return 0
    except SourceManifestError as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
