import copy
import json
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[2]
TSR_ROOT = ROOT / "shared" / "tsr"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_shared_model_pack_fixture_matches_schema():
    schema = load_json(TSR_ROOT / "model-pack.schema.json")
    fixture = load_json(TSR_ROOT / "fixtures" / "de-direct-pack-v1.json")

    jsonschema.Draft202012Validator(schema).validate(fixture)


def test_shared_recognition_events_match_atomic_context_schema():
    schema = load_json(TSR_ROOT / "recognition-event.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    events = load_json(TSR_ROOT / "fixtures" / "recognition-events-v1.json")

    for event in events:
        validator.validate(event)


def test_live_confirmation_without_frame_time_road_context_is_rejected():
    schema = load_json(TSR_ROOT / "recognition-event.schema.json")
    event = copy.deepcopy(load_json(TSR_ROOT / "fixtures" / "recognition-events-v1.json")[-1])
    event["road_context"] = None

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(event)


def test_zero_area_detection_box_is_rejected():
    schema = load_json(TSR_ROOT / "recognition-event.schema.json")
    event = copy.deepcopy(load_json(TSR_ROOT / "fixtures" / "recognition-events-v1.json")[0])
    event["candidate"]["bounding_box"]["width"] = 0

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(event)


def test_confirmed_event_without_candidate_is_rejected():
    schema = load_json(TSR_ROOT / "recognition-event.schema.json")
    event = copy.deepcopy(
        load_json(TSR_ROOT / "fixtures" / "recognition-events-v1.json")[-1]
    )
    event["candidate"] = None

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(event)


def test_diagnostic_and_recognition_restriction_taxonomies_match():
    recognition_schema = load_json(TSR_ROOT / "recognition-event.schema.json")
    diagnostic_schema = load_json(TSR_ROOT / "diagnostic-bundle.schema.json")

    recognition_kinds = recognition_schema["$defs"]["restriction"]["properties"][
        "kind"
    ]["enum"]
    diagnostic_kinds = diagnostic_schema["$defs"]["restriction"]["properties"][
        "kind"
    ]["enum"]

    assert diagnostic_kinds == recognition_kinds


def test_wet_plate_fixture_uses_current_german_sign_code():
    events = load_json(TSR_ROOT / "fixtures" / "recognition-events-v1.json")
    bundle = load_json(
        TSR_ROOT / "fixtures" / "diagnostic-bundle-v1" / "manifest.json"
    )

    assert (
        events[-1]["candidate"]["restrictions"][0]["country_sign_code"]
        == "DE:1053-35"
    )
    assert (
        bundle["samples"][0]["annotation"]["objects"][1]["restriction"][
            "country_sign_code"
        ]
        == "DE:1053-35"
    )
