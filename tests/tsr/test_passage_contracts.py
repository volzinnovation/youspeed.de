import copy
import json
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[2]
TSR_ROOT = ROOT / "shared" / "tsr"
FIXTURE_ROOT = TSR_ROOT / "fixtures"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def passage_events():
    return load_json(FIXTURE_ROOT / "traffic-sign-passage-events-v1.json")


def passage_events_by_id():
    return {event["finalized_event_id"]: event for event in passage_events()}


def passage_scenarios():
    return load_json(FIXTURE_ROOT / "passage-reducer-scenarios-v1.json")[
        "scenarios"
    ]


def passage_scenario_document():
    return load_json(FIXTURE_ROOT / "passage-reducer-scenarios-v1.json")


def test_structural_action_taxonomy_is_additive_and_complete():
    frozen_frame_taxonomy = load_json(TSR_ROOT / "taxonomy-v2.json")
    action_taxonomy = load_json(TSR_ROOT / "structural-action-taxonomy-v1.json")

    assert frozen_frame_taxonomy["taxonomy_id"] == "youspeed-tsr-semantic-v2"
    assert frozen_frame_taxonomy["status"] == "frozen"
    assert action_taxonomy["taxonomy_id"] == "youspeed-tsr-structural-action-v1"
    assert action_taxonomy["taxonomy_version"] == "tsr-structural-action-v1"
    assert action_taxonomy["status"] == "frozen"

    actions = {action["action_id"]: action for action in action_taxonomy["actions"]}
    assert set(actions) == {
        "posted_maximum",
        "zone_start",
        "zone_end",
        "maximum_speed_end",
        "all_restrictions_end",
        "pedestrian_zone_start",
        "pedestrian_zone_end",
        "city_entry",
        "city_exit",
        "motorway_exit",
        "motorroad_exit",
        "temporary_maximum",
        "non_speed_restriction_end",
    }

    assert actions["city_entry"]["country_defaults"]["DE"] == {
        "presentation_kind": "numeric",
        "value_kmh": 50,
    }
    assert "DE:278" in actions["maximum_speed_end"]["classifier_labels"]
    assert "DE:282" in actions["all_restrictions_end"]["classifier_labels"]
    assert actions["temporary_maximum"]["export_policy"] == "never_auto_export"

    hard_negative = actions["non_speed_restriction_end"]
    assert hard_negative["speed_relevant"] is False
    assert hard_negative["passage_event_eligible"] is False
    assert hard_negative["runtime_effect"] == "no_speed_effect"
    assert hard_negative["export_policy"] == "not_applicable"


def test_all_golden_passage_events_match_the_v1_schema():
    schema = load_json(TSR_ROOT / "traffic-sign-passage-event-v1.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)

    events = passage_events()
    assert len(events) == 4
    assert len({event["finalized_event_id"] for event in events}) == len(events)
    for event in events:
        validator.validate(event)


def test_passage_schema_rejects_shadow_uncalibrated_and_non_speed_events():
    schema = load_json(TSR_ROOT / "traffic-sign-passage-event-v1.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    event = passage_events()[0]

    shadow = copy.deepcopy(event)
    shadow["pack"]["execution_mode"] = "shadow"
    shadow["pack"]["override_eligible"] = False
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(shadow)

    uncalibrated = copy.deepcopy(event)
    uncalibrated["pack"]["calibration_status"] = "uncalibrated"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(uncalibrated)

    hard_negative = copy.deepcopy(event)
    hard_negative["action"]["kind"] = "non_speed_restriction_end"
    hard_negative["action"].pop("value_kmh")
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(hard_negative)


def test_passage_schema_rejects_raw_semantics_as_an_osc_value():
    schema = load_json(TSR_ROOT / "traffic-sign-passage-event-v1.schema.json")
    event = copy.deepcopy(passage_events()[0])
    event["resolution"]["normalized_operation"]["tag_value"] = "maximum_speed_end"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(event)


def test_passage_schema_binds_osm_key_to_direction_scope():
    schema = load_json(TSR_ROOT / "traffic-sign-passage-event-v1.schema.json")
    event = copy.deepcopy(passage_events()[0])
    event["resolution"]["normalized_operation"]["tag_key"] = "maxspeed:forward"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(event)


def test_passage_schema_keeps_runtime_and_export_eligibility_fail_closed():
    schema = load_json(TSR_ROOT / "traffic-sign-passage-event-v1.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    events = passage_events_by_id()

    unresolved_runtime_row = copy.deepcopy(
        events["passage-maximum-speed-end-unresolved"]
    )
    unresolved_runtime_row["persistence"]["runtime_applicable"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(unresolved_runtime_row)

    resolved_but_inert_row = copy.deepcopy(events["passage-city-entry-de-50"])
    resolved_but_inert_row["persistence"]["runtime_applicable"] = False
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(resolved_but_inert_row)

    preapproved_export = copy.deepcopy(events["passage-city-entry-de-50"])
    preapproved_export["persistence"]["export_eligible_at_commit"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(preapproved_export)


def test_resolved_passage_is_review_only_when_direction_or_continuity_is_unsafe():
    schema = load_json(TSR_ROOT / "traffic-sign-passage-event-v1.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    safe = passage_events_by_id()["passage-city-entry-de-50"]

    for mutate in (
        lambda event: (
            event["activation"].__setitem__("travel_direction", "unknown"),
            event["applicability_scope"].__setitem__(
                "original_travel_direction", "unknown"
            ),
        ),
        lambda event: event["applicability_scope"].__setitem__(
            "continuity_capable_bundle", False
        ),
    ):
        review_only = copy.deepcopy(safe)
        mutate(review_only)
        review_only["persistence"]["review_state"] = "needs_review"
        review_only["persistence"]["runtime_applicable"] = False
        validator.validate(review_only)

        incorrectly_live = copy.deepcopy(review_only)
        incorrectly_live["persistence"]["review_state"] = "local_only"
        incorrectly_live["persistence"]["runtime_applicable"] = True
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(incorrectly_live)


def test_passage_schema_rejects_non_analyzed_loss_as_negative_evidence():
    schema = load_json(TSR_ROOT / "traffic-sign-passage-event-v1.schema.json")
    event = copy.deepcopy(passage_events()[0])
    event["track"]["loss_evidence"][0]["analysis_eligible"] = False

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(event)


def test_tracks_preserve_raw_calibrated_and_monotonic_fused_evidence():
    required_scores = {
        "proposal_raw_score",
        "proposal_calibrated_confidence",
        "classifier_raw_score",
        "classifier_calibrated_confidence",
        "assembly_confidence",
        "accumulated_support",
    }

    for event in passage_events():
        track = event["track"]
        frames = track["frame_evidence"]
        assert track["frames_seen"] == len(frames)
        assert track["peak_consecutive_frames_seen"] <= track["frames_seen"]
        assert track["single_sighting_exception"] == (track["frames_seen"] == 1)
        assert all(frame["outcome"] == "seen" for frame in frames)
        assert all(frame["analysis_eligible"] is True for frame in frames)
        assert all(required_scores <= frame.keys() for frame in frames)

        support = [frame["accumulated_support"] for frame in frames]
        assert support == sorted(support)
        assert support[-1] == pytest.approx(track["final_accumulated_support"])
        assert support[-1] <= track["accumulated_support_cap"]
        assert "final_calibrated_confidence" in track
        assert track["final_calibrated_confidence"] != pytest.approx(
            track["final_accumulated_support"]
        )

        timestamps = [parse_timestamp(frame["timestamp_utc"]) for frame in frames]
        assert timestamps == sorted(timestamps)
        assert parse_timestamp(track["first_seen_timestamp_utc"]) == timestamps[0]
        assert parse_timestamp(track["last_seen_timestamp_utc"]) == timestamps[-1]


def test_only_eligible_analyzed_missing_frames_qualify_loss():
    for event in passage_events():
        track = event["track"]
        losses = track["loss_evidence"]
        assert len(losses) >= track["negative_frames_required"]
        assert all(loss["outcome"] == "analyzed_missing" for loss in losses)
        assert all(loss["analysis_eligible"] is True for loss in losses)

        if track["loss_reason"] == "strong_pass_geometry":
            assert track["negative_frames_required"] == 1
            assert losses[0]["pass_geometry"] == "strong"
        else:
            assert track["loss_reason"] == "negative_debounce"
            assert all(loss["pass_geometry"] == "not_established" for loss in losses)


def test_first_qualified_missing_frame_is_an_immutable_boundary():
    for event in passage_events():
        first_loss = event["track"]["loss_evidence"][0]
        boundary = event["boundary"]
        activation = event["activation"]

        assert boundary["frame_id"] == first_loss["frame_id"]
        assert boundary["timestamp_utc"] == first_loss["timestamp_utc"]
        assert parse_timestamp(activation["timestamp_utc"]) >= parse_timestamp(
            boundary["timestamp_utc"]
        )
        assert parse_timestamp(event["committed_at_utc"]) >= parse_timestamp(
            activation["timestamp_utc"]
        )

        if activation["reason"] == "first_stabilized_same_scope_rematch":
            assert boundary["way_id"] is None
            assert boundary["map_match_state"] == "no_match"
            assert activation["pending_rematch_elapsed_ms"] > 0
            assert activation["pending_rematch_distance_m"] > 0


def test_activation_scope_carries_bounded_relation_provenance():
    for event in passage_events():
        activation = event["activation"]
        scope = event["applicability_scope"]
        initial_groups = set(scope["initial_route_relation_group_ids"])
        eligible_groups = set(scope["eligible_route_relation_group_ids"])

        assert event["tsr_generation"] >= 0
        assert scope["original_way_id"] == activation["way_id"]
        assert eligible_groups <= initial_groups
        assert eligible_groups <= set(activation["route_relation_group_ids"])
        assert all(relation_id > 0 for relation_id in scope["source_relation_ids"])
        assert len(scope["bundle_sha256"]) == 64


def test_runtime_and_export_predicates_are_separate_and_fail_closed():
    for event in passage_events():
        persistence = event["persistence"]
        resolution = event["resolution"]

        assert persistence["export_eligible_at_commit"] is False
        assert persistence["finalized_event_id_is_idempotency_key"] is True

        if resolution["runtime_status"] == "resolved":
            assert resolution["normalized_operation"] is not None
            assert persistence["runtime_applicable"] is True
            assert persistence["review_state"] == "local_only"
            operation = resolution["normalized_operation"]
            if resolution["presentation"]["kind"] == "numeric":
                assert operation["tag_value"] == str(
                    resolution["presentation"]["value_kmh"]
                )
        else:
            assert resolution["runtime_status"] == "unresolved_end"
            assert resolution["presentation"] == {"kind": "unknown"}
            assert resolution["normalized_operation"] is None
            assert resolution["masks_stale_camera_assertion"] is True
            assert persistence["runtime_applicable"] is False
            assert persistence["review_state"] == "needs_review"
            assert persistence["observation_intent"] == "map_inconsistency"


def test_golden_scenarios_reference_events_and_preserve_generation():
    events = passage_events_by_id()
    scenarios = passage_scenarios()
    assert len({scenario["scenario_id"] for scenario in scenarios}) == len(scenarios)

    for scenario in scenarios:
        frames = scenario["input_frames"]
        emissions = scenario["expected_emitted_event_ids_by_step"]
        sources = scenario["expected_effective_source_by_step"]
        assert len(frames) == len(emissions) == len(sources)
        assert {frame["tsr_generation"] for frame in frames} == {7}

        flattened_emissions = [event_id for step in emissions for event_id in step]
        assert len(flattened_emissions) <= 1
        if scenario["expected_finalized_event_id"] is None:
            assert flattened_emissions == []
        else:
            event_id = scenario["expected_finalized_event_id"]
            assert flattened_emissions == [event_id]
            assert event_id in events
            assert events[event_id]["tsr_generation"] == 7
            assert scenario["expected_boundary_frame_id"] == events[event_id][
                "boundary"
            ]["frame_id"]
            assert scenario["expected_activation_reason"] == events[event_id][
                "activation"
            ]["reason"]

        for frame in frames:
            if frame["outcome"] in {"seen", "analyzed_missing"}:
                assert frame["analysis_eligible"] is True
            else:
                assert frame["analysis_eligible"] is False


def test_supplied_panoramax_examples_are_pinned_as_regressions():
    document = passage_scenario_document()
    regressions = {
        regression["regression_id"]: regression
        for regression in document["source_regressions"]
    }
    expected_picture_ids = {
        "panoramax-repeated-speed-limit-passage": [
            "722e390c-7ac8-4d1f-89d9-3f19d33c3c7e",
            "501e2fec-d5e1-400b-8701-52f26bbad0b1",
            "c8c29b58-9b45-42b2-a166-f9a2b6e4057e",
            "3340eefd-70df-403c-90b8-45729184fd3a",
        ],
        "panoramax-german-city-entry": [
            "e88450f8-b625-4b91-bc3c-2ab09e37cff0"
        ],
        "panoramax-maximum-speed-end": [
            "9a5962cd-518c-4ae3-a027-4a53fbd72acd"
        ],
    }
    expected_annotation_ids = {
        "722e390c-7ac8-4d1f-89d9-3f19d33c3c7e": "08d9286f-71d0-4e0a-a0fe-fc9cac5acf0a",
        "501e2fec-d5e1-400b-8701-52f26bbad0b1": "cddc33b2-a933-4c2d-b75e-98bd6ef60d67",
        "c8c29b58-9b45-42b2-a166-f9a2b6e4057e": None,
        "3340eefd-70df-403c-90b8-45729184fd3a": None,
        "e88450f8-b625-4b91-bc3c-2ab09e37cff0": "d8dbe74f-315b-419b-81b9-a736ce373d27",
        "9a5962cd-518c-4ae3-a027-4a53fbd72acd": "71bf3a65-23df-4847-acff-5032009a42af",
    }

    assert set(regressions) == set(expected_picture_ids)
    for regression_id, picture_ids in expected_picture_ids.items():
        pictures = regressions[regression_id]["pictures"]
        assert [picture["picture_id"] for picture in pictures] == picture_ids
        assert all(
            picture["annotation_id"] == expected_annotation_ids[picture["picture_id"]]
            for picture in pictures
        )
        assert all(picture["picture_id"] in picture["url"] for picture in pictures)
        assert all(
            regressions[regression_id]["sequence_id"] in picture["url"]
            for picture in pictures
        )

    repeated = regressions["panoramax-repeated-speed-limit-passage"]
    assert repeated["expected_visibility"] == [
        "seen",
        "seen",
        "seen",
        "analyzed_missing",
    ]
    repeated_scenario = next(
        scenario
        for scenario in document["scenarios"]
        if scenario["scenario_id"] == "seen-seen-first-qualified-missing-commits"
    )
    assert [
        frame["source_picture_id"] for frame in repeated_scenario["input_frames"]
    ] == expected_picture_ids["panoramax-repeated-speed-limit-passage"]

    referenced_regressions = {
        regression_id
        for scenario in document["scenarios"]
        for regression_id in scenario["source_regression_ids"]
    }
    assert referenced_regressions == set(regressions)


def test_repeated_seen_then_missing_changes_source_only_on_the_falling_edge():
    scenarios = {scenario["scenario_id"]: scenario for scenario in passage_scenarios()}
    scenario = scenarios["seen-seen-first-qualified-missing-commits"]

    assert [frame["outcome"] for frame in scenario["input_frames"]] == [
        "seen",
        "seen",
        "seen",
        "analyzed_missing",
    ]
    assert scenario["expected_emitted_event_ids_by_step"][:-1] == [[], [], []]
    assert scenario["expected_effective_source_by_step"] == [
        "bundle",
        "bundle",
        "bundle",
        "camera",
    ]


def test_dropout_reappearance_is_not_a_passage_edge():
    scenarios = {scenario["scenario_id"]: scenario for scenario in passage_scenarios()}
    scenario = scenarios["dropout-and-reappearance-does-not-commit"]

    assert [frame["outcome"] for frame in scenario["input_frames"]] == [
        "seen",
        "analyzed_missing",
        "throttled_not_analyzed",
        "seen",
    ]
    assert scenario["expected_emitted_event_ids_by_step"] == [[], [], [], []]
    assert scenario["expected_finalizer_state"] == "armed"
    assert scenario["expected_finalized_event_id"] is None


def test_pending_passage_commits_only_on_same_scope_rematch():
    scenarios = {scenario["scenario_id"]: scenario for scenario in passage_scenarios()}
    scenario = scenarios["maximum-speed-end-resolves-captured-prior"]

    assert [frame["outcome"] for frame in scenario["input_frames"]][-3:] == [
        "analyzed_missing",
        "analyzed_missing",
        "stabilized_same_scope_rematch",
    ]
    assert all(
        emitted == []
        for emitted in scenario["expected_emitted_event_ids_by_step"][:-1]
    )
    assert scenario["expected_emitted_event_ids_by_step"][-1] == [
        "passage-maximum-speed-end-resolved"
    ]
    assert scenario["expected_boundary_frame_id"] == "frame-max-end-003"
    assert scenario["expected_activation_reason"] == (
        "first_stabilized_same_scope_rematch"
    )


def test_german_city_entry_and_end_resolution_golden_semantics():
    events = passage_events_by_id()

    city = events["passage-city-entry-de-50"]
    assert city["action"]["kind"] == "city_entry"
    assert city["action"]["country"] == "DE"
    assert city["resolution"]["presentation"] == {
        "kind": "numeric",
        "value_kmh": 50,
    }

    resolved_end = events["passage-maximum-speed-end-resolved"]
    assert resolved_end["action"] == {
        "kind": "maximum_speed_end",
        "ended_value_kmh": 70,
        "permanence": "permanent",
        "condition_state": "none",
        "restrictions": [],
    }
    assert resolved_end["resolution"]["presentation"]["value_kmh"] == 50
    assert resolved_end["resolution"]["normalized_operation"]["tag_value"] == "50"

    unresolved_end = events["passage-maximum-speed-end-unresolved"]
    assert unresolved_end["action"]["kind"] == "maximum_speed_end"
    assert unresolved_end["resolution"]["runtime_status"] == "unresolved_end"
    assert unresolved_end["resolution"]["presentation"]["kind"] == "unknown"
    assert unresolved_end["resolution"]["normalized_operation"] is None
    assert unresolved_end["persistence"]["runtime_applicable"] is False
