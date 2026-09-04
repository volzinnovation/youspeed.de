import copy
import json
from pathlib import Path

import jsonschema
import pytest

from scripts.tsr.group_splits_v2 import (
    GroupSplitError,
    SplitSample,
    build_group_split,
    samples_from_full_scene_manifest,
    validate_group_split,
)


ROOT = Path(__file__).resolve().parents[2]


def _sample(
    sample_id: str,
    drive_id: str,
    *physical_sign_ids: str,
    near_duplicate_cluster_ids: tuple[str, ...] = (),
    source_split_id: str | None = None,
    source_artifact_ids: tuple[str, ...] = (),
) -> SplitSample:
    return SplitSample(
        sample_id=sample_id,
        drive_id=drive_id,
        physical_sign_ids=tuple(physical_sign_ids),
        near_duplicate_cluster_ids=near_duplicate_cluster_ids,
        source_split_id=source_split_id,
        source_artifact_ids=source_artifact_ids,
    )


def test_same_drive_and_cross_drive_physical_sign_form_one_component() -> None:
    manifest = build_group_split(
        [
            _sample("frame-a", "drive-a", "sign-70"),
            _sample("frame-b", "drive-a", "sign-80"),
            _sample("frame-c", "drive-b", "sign-70"),
            _sample("frame-d", "drive-c", "sign-100"),
        ],
        seed="m0-split-v2",
    )

    first = next(
        group
        for group in manifest["components"]
        if "frame-a" in group["sample_ids"]
    )
    assert first["sample_ids"] == ["frame-a", "frame-b", "frame-c"]
    assert first["drive_ids"] == ["drive-a", "drive-b"]
    assert first["physical_sign_ids"] == ["sign-70", "sign-80"]
    assert len(manifest["components"]) == 2


def test_split_is_stable_independent_of_input_order() -> None:
    records = [
        _sample("frame-a", "drive-a", "sign-a"),
        _sample("frame-b", "drive-b", "sign-b"),
        _sample("frame-c", "drive-c", "sign-c"),
    ]
    assert build_group_split(records, seed="stable") == build_group_split(
        reversed(records), seed="stable"
    )


@pytest.mark.parametrize(
    "record",
    [
        _sample(
            "frame-a",
            "drive-a",
            "sign-a",
            source_split_id="panoramax-classified-de-road-signs-b485694-validation",
        ),
        _sample(
            "frame-a",
            "drive-a",
            "sign-a",
            source_artifact_ids=("panoramax-de-validation-b485694",),
        ),
    ],
)
def test_published_panoramax_validation_is_rejected(record: SplitSample) -> None:
    with pytest.raises(GroupSplitError, match="published Panoramax validation"):
        build_group_split([record], seed="m0")


def test_relational_validator_rejects_cross_split_sign_leakage() -> None:
    manifest = build_group_split(
        [
            _sample("frame-a", "drive-a", "sign-a"),
            _sample("frame-b", "drive-b", "sign-b"),
        ],
        seed="m0",
    )
    leaked = copy.deepcopy(manifest)
    if len(leaked["components"]) < 2:
        pytest.skip("fixture unexpectedly formed one component")
    leaked["components"][1]["physical_sign_ids"].append(
        leaked["components"][0]["physical_sign_ids"][0]
    )
    leaked["components"][1]["partition"] = next(
        value for value in ("train", "calibration", "holdout")
        if value != leaked["components"][0]["partition"]
    )

    with pytest.raises(GroupSplitError, match="leaks across"):
        validate_group_split(leaked)


def test_empty_dataset_or_invalid_fractions_fail_closed() -> None:
    with pytest.raises(GroupSplitError, match="at least one sample"):
        build_group_split([], seed="m0")
    with pytest.raises(GroupSplitError, match="holdout fraction"):
        build_group_split([_sample("a", "d", "s")], seed="m0", train_fraction=0.9, calibration_fraction=0.1)


def test_near_duplicate_cluster_is_a_transitive_group_key() -> None:
    manifest = build_group_split(
        [
            _sample(
                "frame-a",
                "drive-a",
                "sign-a",
                near_duplicate_cluster_ids=("visual-cluster-1",),
            ),
            _sample(
                "frame-b",
                "drive-b",
                "sign-b",
                near_duplicate_cluster_ids=("visual-cluster-1",),
            ),
        ],
        seed="m0",
        near_duplicate_analysis_status="passed",
    )

    assert len(manifest["components"]) == 1
    assert manifest["leakage_audit"] == {
        "drive_overlap_count": 0,
        "physical_sign_overlap_count": 0,
        "near_duplicate_analysis_status": "passed",
        "near_duplicate_overlap_count": 0,
        "prohibited_source_split_count": 0,
        "passed": True,
    }


def test_near_duplicate_audit_is_pending_by_default() -> None:
    manifest = build_group_split([_sample("a", "d", "s")], seed="m0")
    assert manifest["leakage_audit"]["near_duplicate_analysis_status"] == "pending"
    assert manifest["leakage_audit"]["near_duplicate_overlap_count"] is None
    assert manifest["leakage_audit"]["passed"] is False


def test_generated_manifest_matches_the_v2_schema() -> None:
    manifest = build_group_split(
        [
            _sample(
                "frame-a",
                "drive-a",
                "sign-a",
                near_duplicate_cluster_ids=("visual-a",),
            )
        ],
        seed="m0",
        near_duplicate_analysis_status="passed",
    )
    schema = json.loads(
        (ROOT / "shared" / "tsr" / "group-split-v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator(schema).validate(manifest)


def test_passed_near_duplicate_audit_requires_cluster_coverage() -> None:
    with pytest.raises(GroupSplitError, match="cluster ID for every sample"):
        build_group_split(
            [_sample("frame-a", "drive-a", "sign-a")],
            seed="m0",
            near_duplicate_analysis_status="passed",
        )


def test_frozen_full_scene_manifest_projects_drive_and_physical_sign_groups() -> None:
    fixture_path = (
        ROOT
        / "shared"
        / "tsr"
        / "fixtures"
        / "panoramax-m0-full-scene-annotations-v2.json"
    )
    if not fixture_path.is_file():
        pytest.skip("contract fixture is being generated by the v2 contract task")
    records = samples_from_full_scene_manifest(
        json.loads(fixture_path.read_text(encoding="utf-8"))
    )

    assert len(records) == 2
    assert records[0].drive_id == records[1].drive_id
    assert records[0].physical_sign_ids == records[1].physical_sign_ids
    assert records[0].near_duplicate_cluster_ids == ()
    manifest = build_group_split(records, seed="m0-panoramax")
    assert len(manifest["components"]) == 1
    assert manifest["leakage_audit"]["passed"] is False


def test_full_scene_projection_rejects_published_panoramax_validation() -> None:
    manifest = {
        "schema_version": 2,
        "taxonomy_version": "tsr-semantic-v2",
        "frozen": True,
        "frames": [
            {
                "frame_id": "frame-a",
                "drive_id": "drive-a",
                "source": {
                    "source_id": "source-a",
                    "source_asset_id": "asset-a",
                    "source_split_id": "panoramax-de-validation-b485694",
                },
                "objects": [{"physical_sign_id": "sign-a"}],
            }
        ],
    }
    records = samples_from_full_scene_manifest(manifest)
    with pytest.raises(GroupSplitError, match="published Panoramax validation"):
        build_group_split(records, seed="m0")
