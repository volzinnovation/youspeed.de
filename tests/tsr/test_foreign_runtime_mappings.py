"""Regression coverage for missing Belgian speed-zone meanings in both apps."""
import importlib.util
import json
import re
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    'foreign_runtime_metadata', ROOT / 'scripts/tsr/foreign-export/build_runtime_pack_metadata.py'
)
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


@pytest.mark.parametrize('label', [
    'bicycle:priority:end', 'priority:end', 'no_overtaking:end',
    'zone:no_parking', 'zone:no_parking:end', 'zone:low_emission',
    'zone:other:end', 'maxspeed:unknown', 'maxspeed:0', 'maxspeed:250',
])
def test_non_speed_classes_cannot_clear_or_start_a_speed_limit(label):
    assert BUILDER.semantic(label) == {'kind': 'unknown'}


def test_schematic_speed_mapping_does_not_require_artwork_and_is_idempotent():
    mappings = []
    names = ['zone:30', 'zone:30:end', 'maxspeed:15', 'zone:other', 'bad']
    BUILDER.add_schematic_speed_mappings(mappings, names)
    BUILDER.add_schematic_speed_mappings(mappings, names)
    assert [m['class_id'] for m in mappings] == names[:3]
    assert [m['semantic'] for m in mappings] == [
        {'kind': 'zone_start', 'value': 30, 'unit': 'km/h'},
        {'kind': 'zone_end'},
        {'kind': 'maximum_speed', 'value': 15, 'unit': 'km/h'},
    ]


def test_both_belgium_packs_cover_actual_numeric_outputs_with_matching_meanings():
    paths = [
        ROOT / 'iphone/SpeedConsumerApp/TSRModelPacks/BE.panoramax-bootstrap.tsrmodelpack',
        ROOT / 'android/app/src/main/assets/tsr/BE.panoramax-bootstrap.tsrmodelpack',
    ]
    packs = [json.loads((p / 'manifest.json').read_text()) for p in paths]
    labels = json.loads((paths[0] / 'classify_be_road_signs.mlmodelc/metadata.json').read_text())[0]['classLabels']
    schema = json.loads((ROOT / 'shared/tsr/model-pack.schema.json').read_text())
    assert packs[0]['class_mapping'] == packs[1]['class_mapping']
    for pack in packs:
        jsonschema.Draft202012Validator(schema).validate(pack)
        mappings = {m['class_id']: m for m in pack['class_mapping']}
        assert len(mappings) == len(pack['class_mapping'])
        assert mappings.keys() <= set(labels)
        # Freeze the field failures explicitly, then guard all numeric model outputs.
        for label in ['zone:30', 'zone:50']:
            assert mappings[label]['semantic'] == {
                'kind': 'zone_start', 'value': int(label.split(':')[1]), 'unit': 'km/h',
            }
        for label in labels:
            if re.fullmatch(r'(maxspeed|zone):[0-9]+(:end)?', label):
                assert mappings[label]['semantic'] == BUILDER.semantic(label)
                assert mappings[label]['threshold'] == 0.7
        for label in ['priority:end', 'no_overtaking:end', 'bicycle:priority:end']:
            assert mappings[label]['semantic'] == {'kind': 'unknown'}
