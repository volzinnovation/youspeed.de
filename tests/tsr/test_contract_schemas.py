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
