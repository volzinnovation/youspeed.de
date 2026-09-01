import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.tsr.diagnostic_dataset import (
    DiagnosticBundleError,
    materialize_dataset,
    split_for_group,
    validate_bundle,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPOSITORY_ROOT / "shared" / "tsr" / "fixtures" / "diagnostic-bundle-v1"


def test_fixture_round_trips_to_detector_dataset(tmp_path: Path) -> None:
    bundle = validate_bundle(FIXTURE, require_export_approval=True)

    index = materialize_dataset([bundle], tmp_path / "dataset", seed="fixture-split-v1")

    assert index["sample_count"] == 1
    sample = index["samples"][0]
    image_path = tmp_path / "dataset" / sample["detector_image"]
    label_path = tmp_path / "dataset" / sample["detector_label"]
    assert image_path.read_bytes() == (FIXTURE / "frames" / "frame-0001.ppm").read_bytes()
    assert label_path.read_text(encoding="utf-8").splitlines() == [
        "0 0.73500000 0.20500000 0.09000000 0.13000000",
        "1 0.74500000 0.31500000 0.11000000 0.07000000",
    ]
    assert sample["road_context"]["way_id"] == "123456"
    assert sample["road_context"]["heading_degrees"] == 82.0


def test_capture_group_split_is_stable_and_keeps_a_group_together() -> None:
    first = split_for_group("drive-a", seed="split-v1")
    assert split_for_group("drive-a", seed="split-v1") == first
    assert split_for_group("drive-a", seed="split-v1") in {"train", "validation", "test"}


def test_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "bundle"
    copied.mkdir()
    payload = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    payload["samples"][0]["assets"][0]["sha256"] = "0" * 64
    (copied / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    (copied / "frames").mkdir()
    (copied / "frames" / "frame-0001.ppm").write_bytes((FIXTURE / "frames" / "frame-0001.ppm").read_bytes())
    (copied / "crops").mkdir()
    (copied / "crops" / "assembly-0001.ppm").write_bytes((FIXTURE / "crops" / "assembly-0001.ppm").read_bytes())

    with pytest.raises(DiagnosticBundleError, match="hash mismatch"):
        validate_bundle(copied)


def test_plate_must_reference_primary_in_same_assembly(tmp_path: Path) -> None:
    payload = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    payload["samples"][0]["annotation"]["objects"][1]["parent_object_id"] = "missing"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DiagnosticBundleError, match="must reference a primary sign"):
        validate_bundle(manifest, verify_assets=False)


def test_plate_assembly_cannot_claim_no_condition(tmp_path: Path) -> None:
    payload = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    payload["samples"][0]["annotation"]["assemblies"][0]["condition_state"] = "none"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DiagnosticBundleError, match="does not match its plates"):
        validate_bundle(manifest, verify_assets=False)


def test_unknown_restriction_kind_must_be_explicitly_normalized(tmp_path: Path) -> None:
    payload = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    payload["samples"][0]["annotation"]["objects"][1]["restriction"]["kind"] = "wet"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DiagnosticBundleError, match="restriction.kind is invalid"):
        validate_bundle(manifest, verify_assets=False)


def test_live_candidate_requires_way_coordinate_heading_and_source_revision(tmp_path: Path) -> None:
    payload = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    payload["samples"][0]["capture_context"]["way_id"] = None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DiagnosticBundleError, match="way_id is required"):
        validate_bundle(manifest, verify_assets=False)


def test_unapproved_or_unredacted_full_frames_cannot_be_materialized(tmp_path: Path) -> None:
    payload = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    payload["consent"]["export_approved"] = False
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DiagnosticBundleError, match="export is not approved"):
        validate_bundle(manifest, verify_assets=False, require_export_approval=True)

    payload = copy.deepcopy(payload)
    payload["consent"]["export_approved"] = True
    payload["privacy"]["redaction_state"] = "pending"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DiagnosticBundleError, match="verified redaction"):
        validate_bundle(manifest, verify_assets=False, require_export_approval=True)


def test_expired_diagnostic_retention_is_rejected_deterministically(
    tmp_path: Path,
) -> None:
    payload = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    payload["consent"]["retention_expires_at"] = "2026-01-02T00:00:00Z"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DiagnosticBundleError, match="retention has expired"):
        validate_bundle(
            manifest,
            verify_assets=False,
            now=datetime(2026, 1, 3, tzinfo=timezone.utc),
        )


def test_diagnostic_timestamps_require_timezones(tmp_path: Path) -> None:
    payload = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    payload["consent"]["granted_at"] = "2026-01-01T11:59:00"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DiagnosticBundleError, match="must include a timezone"):
        validate_bundle(manifest, verify_assets=False)
