"""Offline geometry contract tests; synthetic shapes are not field evidence."""
from copy import deepcopy
import hashlib
import json

from PIL import Image
import pytest

from scripts.tsr.applicability.image_geometry_replay import (
    CONFIG, ROOT, SCHEMA_PATH, assign_road, predict, run, score, validate,
)


def corpus(tmp_path, count=1):
    frames = []
    for index in range(count):
        path = tmp_path / f"frame-{index}.png"
        Image.new("RGB", (100, 100), (index * 50, 20, 30)).save(path)
        frames.append({
            "frame_id": f"immutable-{index}", "route_id": "route-a",
            "sequence_id": "sequence-a", "captured_at": f"2026-09-28T12:00:0{index}Z",
            "temporal_tracking_eligible": True,
            "legacy_evaluation_eligible": True,
            "split": "development", "image_path": str(path),
            "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "width": 100, "height": 100,
            "source": {"kind": "synthetic_test_only"},
            "geometry": {"reviewed": True, "current_road_id": "main",
                         "uncertainty_margin": .015,
                         "roads": [
                             {"road_id": "main", "role": "mainline",
                              "polygon": [[.1, .1], [.5, .1], [.5, .9], [.1, .9]]},
                             {"road_id": "ramp", "role": "branch",
                              "polygon": [[.6, .1], [.9, .1], [.9, .9], [.6, .9]]}]},
            "topology": {"motorway": True, "map_limit_kmh": 130,
                         "legacy_branch_available": False,
                         "legacy_road_context_fresh": False,
                         "directed_branch_available": True,
                         "branch_road_ids": ["ramp"]},
            "signs": [{"sign_id": "sign-a", "track_id": "physical-a", "track_verified": True,
                       "box": [.50, .1, .08, .08], "value_kmh": 70,
                       "ground_anchor": {"x": .75, "y": .6, "uncertainty_radius": .005,
                                         "reliable": True, "source": "visible_post_base"},
                       "expected_applicability": "other", "expected_road_id": "ramp"}]})
    return {"schema_version": 1, "corpus_id": "synthetic", "frames": frames}


def test_assignment_uses_support_not_elevated_sign_center_or_expected_label(tmp_path):
    data = corpus(tmp_path)
    row = predict(data)[0]
    assert row["legacy_fixed_x_approximation"] == "ego"
    assert row["reviewed_geometry"] == "other"
    changed = deepcopy(data)
    changed["frames"][0]["signs"][0].update(expected_applicability="ego", expected_road_id="main")
    assert predict(changed) == predict(data)


def test_ego_sign_remains_ego_near_branch_without_behavior(tmp_path):
    data = corpus(tmp_path)
    sign = data["frames"][0]["signs"][0]
    sign["ground_anchor"]["x"] = .3
    sign["box"][0] = .7
    sign["expected_applicability"] = "ego"
    assert predict(data)[0]["reviewed_geometry"] == "ego"
    assert not CONFIG["behavior_enabled"] and not CONFIG["learned_geometry_enabled"]


@pytest.mark.parametrize("anchor,reason", [
    (None, "missing_reliable_ground_anchor"),
    ({"x": .75, "y": .6, "uncertainty_radius": .005, "reliable": False},
     "missing_reliable_ground_anchor"),
    ({"x": .601, "y": .6, "uncertainty_radius": .005, "reliable": True},
     "anchor_overlaps_road_boundary"),
    ({"x": .55, "y": .6, "uncertainty_radius": .005, "reliable": True},
     "anchor_too_far_from_reviewed_roads"),
    ({"x": .75, "y": .6, "uncertainty_radius": .1, "reliable": True},
     "anchor_uncertainty_too_large"),
])
def test_uncertain_support_abstains(tmp_path, anchor, reason):
    frame = corpus(tmp_path)["frames"][0]
    frame["signs"][0]["ground_anchor"] = anchor
    assert assign_road(frame["geometry"], frame["signs"][0]) == (None, reason)


def test_nearest_road_with_margin_handles_visible_post_outside_asphalt(tmp_path):
    frame = corpus(tmp_path)["frames"][0]
    frame["signs"][0]["ground_anchor"]["x"] = .91
    assert assign_road(frame["geometry"], frame["signs"][0]) == (
        "ramp", "anchor_near_unique_road_edge")


def test_overlapping_polygons_abstain(tmp_path):
    frame = corpus(tmp_path)["frames"][0]
    frame["geometry"]["roads"][0]["polygon"][1][0] = .85
    frame["geometry"]["roads"][0]["polygon"][2][0] = .85
    assert assign_road(frame["geometry"], frame["signs"][0])[0] is None


def test_verified_track_is_causal_and_does_not_create_observations(tmp_path):
    data = corpus(tmp_path, 3)
    data["frames"][0]["signs"][0]["ground_anchor"] = None
    data["frames"][2]["signs"][0]["ground_anchor"] = None
    rows = predict(data)
    assert [r["reviewed_geometry_and_track"] for r in rows] == ["unknown", "other", "other"]
    assert rows[-1]["track_reason"] == "past_verified_track_assignment"
    assert len(rows) == 3


@pytest.mark.parametrize("change", ["unverified", "gap", "scope"])
def test_track_does_not_bridge_unknown_identity_gaps_or_road_entry(tmp_path, change):
    data = corpus(tmp_path, 2)
    later = data["frames"][1]
    later["signs"][0]["ground_anchor"] = None
    if change == "unverified":
        later["signs"][0]["track_verified"] = False
    elif change == "gap":
        later["captured_at"] = "2026-09-28T12:00:04Z"
    else:
        later["geometry"]["current_road_id"] = "ramp"
    assert predict(data)[-1]["reviewed_geometry_and_track"] == "unknown"


def test_contradictory_geometry_clears_past_track(tmp_path):
    data = corpus(tmp_path, 3)
    data["frames"][1]["signs"][0]["ground_anchor"]["x"] = .601
    data["frames"][2]["signs"][0]["ground_anchor"] = None
    assert predict(data)[-1]["reviewed_geometry_and_track"] == "unknown"


@pytest.mark.parametrize("change", ["absent", "direction_incompatible"])
@pytest.mark.parametrize("sign_visible_during_change", [True, False])
def test_track_road_invalidation_cannot_resurrect_after_reappearance(
        tmp_path, change, sign_visible_during_change):
    data = corpus(tmp_path, 3)
    first, changed, reappeared = data["frames"]
    changed["signs"][0]["ground_anchor"] = None
    reappeared["signs"][0]["ground_anchor"] = None
    if change == "absent":
        changed["geometry"]["roads"] = changed["geometry"]["roads"][:1]
    else:
        changed["geometry"]["roads"][1]["direction_compatible"] = False
    if not sign_visible_during_change:
        changed["signs"] = []
    rows = predict(data)
    assert rows[0]["reviewed_geometry_and_track"] == "other"
    assert all(row["reviewed_geometry_and_track"] == "unknown" for row in rows[1:])
    assert rows[-1]["frame_id"] == reappeared["frame_id"]


def test_returning_to_previous_ego_scope_does_not_restore_old_track(tmp_path):
    data = corpus(tmp_path, 3)
    data["frames"][1]["geometry"]["current_road_id"] = "ramp"
    for frame in data["frames"][1:]:
        frame["signs"][0]["ground_anchor"] = None
    rows = predict(data)
    assert [row["reviewed_geometry_and_track"] for row in rows] == ["other", "unknown", "unknown"]


def test_missing_directed_topology_does_not_reject_other_road(tmp_path):
    data = corpus(tmp_path)
    data["frames"][0]["topology"]["directed_branch_available"] = False
    assert predict(data)[0]["reviewed_geometry"] == "unknown"


@pytest.mark.parametrize("key", ["route_id", "sequence_id"])
def test_split_leakage_rejected(tmp_path, key):
    data = corpus(tmp_path, 2)
    later = data["frames"][1]
    later["split"] = "held_out"
    other_key = "sequence_id" if key == "route_id" else "route_id"
    later[other_key] = "different"
    with pytest.raises(ValueError, match="leaks across splits"):
        validate(data)


@pytest.mark.parametrize("change,match", [
    ("hash", "Image hash mismatch"), ("identity", "Duplicate immutable"),
    ("time", "strictly increase"), ("bytes", "Duplicate image bytes"),
    ("anchor", "visible_post_base"),
])
def test_corpus_integrity_and_invalid_support_rejected(tmp_path, change, match):
    data = corpus(tmp_path, 2)
    first, later = data["frames"]
    if change == "hash":
        later["image_sha256"] = "a" * 64
    elif change == "identity":
        later["frame_id"] = first["frame_id"]
    elif change == "time":
        later["captured_at"] = first["captured_at"]
    elif change == "bytes":
        later["image_sha256"] = first["image_sha256"]
    else:
        later["signs"][0]["ground_anchor"]["source"] = "elevated_box_center"
    with pytest.raises(ValueError, match=match):
        validate(data)


def test_scoring_reports_unresolved_truth_and_errors_separately(tmp_path):
    data = corpus(tmp_path, 3)
    data["frames"][1]["signs"][0]["expected_applicability"] = "ego"
    data["frames"][2]["signs"][0]["expected_applicability"] = "unknown"
    result = score(data, predict(data))["reviewed_geometry"]["all"]
    assert result["legitimate_sign_rejections"] == 1
    assert result["truth_unknown"] == 1
    assert result["truth_other__output_other"] == 1


def test_report_binds_input_and_images(tmp_path):
    data = corpus(tmp_path)
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(data))
    report = run([path])
    assert report["corpora"][0]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert report["validation"]["image_hashes_verified"] is True
    assert report["frame_provenance"][0]["image_sha256"] == data["frames"][0]["image_sha256"]
    assert len(report["runner_sha256"]) == 64


def test_panorama_does_not_claim_comparable_fixed_x_baseline(tmp_path):
    data = corpus(tmp_path)
    data["frames"][0]["projection"] = "equirectangular"
    rows = predict(data)
    assert rows[0]["legacy_fixed_x_approximation"] == "not_evaluated"
    assert score(data, rows)["legacy_fixed_x_approximation"]["all"]["wrong_road_admissions"] == 0
    assert "projection:equirectangular" in score(data, rows)["reviewed_geometry"]


def test_microsecond_metadata_preserved_but_unknown_cadence_forbids_track_carry(tmp_path):
    data = corpus(tmp_path, 2)
    first, later = data["frames"]
    first["captured_at"] = "2024-08-21T22:00:00.395740Z"
    later["captured_at"] = "2024-08-21T22:00:00.395750Z"
    first["temporal_tracking_eligible"] = False
    later["signs"][0]["ground_anchor"] = None
    assert validate(data)["frames"] == 2
    rows = predict(data)
    assert rows[-1]["captured_at"] == later["captured_at"]
    assert rows[-1]["reviewed_geometry_and_track"] == "unknown"
    assert rows[-1]["track_reason"] == "temporal_cadence_not_verified"


def test_timing_eligibility_is_opt_in(tmp_path):
    data = corpus(tmp_path, 2)
    for frame in data["frames"]:
        del frame["temporal_tracking_eligible"]
    data["frames"][1]["signs"][0]["ground_anchor"] = None
    assert predict(data)[-1]["reviewed_geometry_and_track"] == "unknown"


def test_public_still_without_historical_guard_context_has_no_invented_baseline(tmp_path):
    data = corpus(tmp_path)
    del data["frames"][0]["legacy_evaluation_eligible"]
    row = predict(data)[0]
    assert row["legacy_fixed_x_approximation"] == "not_evaluated"
    assert row["legacy_reason"] == "historical_guard_context_unavailable"


def test_manual_arrow_road_relation_does_not_smuggle_answer_into_geometry(tmp_path):
    data = corpus(tmp_path)
    sign = data["frames"][0]["signs"][0]
    sign["ground_anchor"] = None
    sign["supplementary_arrow"] = {"road_id": "ramp", "verified": True,
                                   "source": "visible_arrow_to_road_relation"}
    assert predict(data)[0]["reviewed_geometry"] == "unknown"
    assert CONFIG["manual_arrow_road_relations_enabled"] is False


def test_frozen_real_image_report_matches_prediction_and_input_provenance():
    # Metadata-only CI check: private image bytes are intentionally not in Git.
    path = ROOT / "shared/tsr/applicability/fixtures/image-road-geometry-ablation-20260928-v1.report.json"
    frozen = json.loads(path.read_text())
    fresh = run([ROOT / source["path"] for source in frozen["corpora"]], verify_images=False)
    assert fresh["predictions"] == frozen["predictions"]
    assert fresh["stages"] == frozen["stages"]
    assert fresh["coverage"] == frozen["coverage"]
    assert fresh["runner_sha256"] == frozen["runner_sha256"]
    assert hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest() == frozen["corpus_schema_sha256"]
    assert [c["sha256"] for c in fresh["corpora"]] == [c["sha256"] for c in frozen["corpora"]]
