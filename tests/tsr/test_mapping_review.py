"""Five-country regressions: actual model vocabulary, legal actions and artwork."""
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from scripts.tsr.mapping_review import COUNTRIES, ROOT, run, semantic


@pytest.mark.parametrize('country,count', [('DE',134), ('BE',143), ('FR',256), ('NL',160), ('CH',127)])
def test_every_actual_classifier_output_is_mapped_identically_on_both_platforms(country, count):
    ios = ROOT / f'iphone/SpeedConsumerApp/TSRModelPacks/{country}.panoramax-bootstrap.tsrmodelpack'
    android = ROOT / f'android/app/src/main/assets/tsr/{country}.panoramax-bootstrap.tsrmodelpack'
    labels = json.loads((ios / f'classify_{country.lower()}_road_signs.mlmodelc/metadata.json').read_text())[0]['classLabels']
    catalog = json.loads((ROOT / f'shared/tsr/prolix-{country.lower()}-class-catalog-v1.json').read_text())
    a, b = [json.loads((p / 'manifest.json').read_text()) for p in (ios, android)]
    assert a['class_mapping'] == b['class_mapping']
    assert len(labels) == count
    assert catalog['class_labels'] == labels
    assert [m['class_id'] for m in a['class_mapping']] == labels
    assert set(labels) <= {s['class_id'] for s in catalog['signs']}
    assert len(catalog['signs']) == len({s['class_id'] for s in catalog['signs']})
    schema = json.loads((ROOT / 'shared/tsr/model-pack.schema.json').read_text())
    for pack in (a, b):
        jsonschema.Draft202012Validator(schema).validate(pack)
    for sign in catalog['signs']:
        if sign['display_eligible']:
            path = ROOT / 'shared' / sign['image_path']
            assert path.is_file()
            assert Path(path.with_suffix('.svg').as_posix().replace('/png/', '/originals/')).is_file()
            if 'source_provenance' in sign:
                assert hashlib.sha256(path.read_bytes()).hexdigest() == sign['source_provenance']['png_sha256']
        else:
            assert sign['image_path'] is None


@pytest.mark.parametrize('country,label,expected', [
    ('FR','B31',{'kind':'restriction_end'}),
    ('FR','B33-70',{'kind':'restriction_end','value':70}),
    ('FR','B14-45',{'kind':'maximum_speed','value':45,'unit':'km/h'}),
    ('FR','B30',{'kind':'zone_start','value':30,'unit':'km/h'}),
    ('FR','B51',{'kind':'zone_end','value':30}),
    ('FR','B52',{'kind':'zone_start','value':20,'unit':'km/h'}),
    ('FR','B53',{'kind':'zone_end','value':20}),
    ('FR','B54',{'kind':'pedestrian_zone_start'}),
    ('FR','B55',{'kind':'pedestrian_zone_end'}),
    ('FR','EB10',{'kind':'city_entry'}), ('FR','EB20',{'kind':'city_exit'}),
    ('FR','C207',{'kind':'unknown'}), ('FR','C208',{'kind':'restriction_end'}),
    ('FR','C107',{'kind':'unknown'}), ('FR','C108',{'kind':'restriction_end'}),
    ('FR','B41',{'kind':'unknown'}),
    ('CH','zone:calm',{'kind':'zone_start','value':20,'unit':'km/h'}),
    ('CH','zone:calm:end',{'kind':'zone_end','value':20}),
    ('CH','zone:pedestrian',{'kind':'pedestrian_zone_start'}),
    ('CH','zone:pedestrian:end',{'kind':'pedestrian_zone_end'}),
    ('CH','zone:no_parking:end',{'kind':'unknown'}),
    ('NL','zone:60:end',{'kind':'zone_end','value':60}),
    ('BE','city:start',{'kind':'city_entry'}), ('BE','city:end',{'kind':'city_exit'}),
])
def test_reviewed_legal_distinctions(country, label, expected):
    assert semantic(label, country) == expected
    pack = json.loads((ROOT / f'iphone/SpeedConsumerApp/TSRModelPacks/{country}.panoramax-bootstrap.tsrmodelpack/manifest.json').read_text())
    assert next(m['semantic'] for m in pack['class_mapping'] if m['class_id'] == label) == expected


@pytest.mark.parametrize('country', COUNTRIES)
def test_unrelated_endings_and_footpaths_cannot_reset_speed(country):
    for label in ['pedestrian:start','pedestrian:end','priority:end','chains:end','min_speed:end',
                  'bicycle:end','no_overtaking:end','zone:no_parking:end','zone:other:end',
                  'zone:low_emission:end','bad','maxspeed:0','maxspeed:250']:
        assert semantic(label, country) == {'kind':'unknown'}, (country,label)


def test_no_drift_in_review_ledger_and_generators():
    assert run(write=False) == []


def test_actual_model_gaps_are_not_filled_with_fictional_labels():
    for country in ['DE','NL','CH']:
        catalog = json.loads((ROOT / f'shared/tsr/prolix-{country.lower()}-class-catalog-v1.json').read_text())
        assert not {'city:start','city:end'} & set(catalog['class_labels'])
    catalog = json.loads((ROOT / 'shared/tsr/prolix-ch-class-catalog-v1.json').read_text())
    sign = next(s for s in catalog['signs'] if s['class_id']=='zone:no_parking:end')
    assert not sign['display_eligible']  # The upstream ASTRA example is actually a 30-zone end.


def test_swiss_generic_code_fallbacks_cannot_show_unrelated_artwork():
    catalog = json.loads((ROOT / 'shared/tsr/prolix-ch-class-catalog-v1.json').read_text())
    for label in ('hazard:horse', 'no_exit:car', 'zone:no_parking:end'):
        sign = next(s for s in catalog['signs'] if s['class_id'] == label)
        assert not sign['display_eligible']
        assert sign['image_path'] is None
