import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
import jsonschema

ROOT=Path(__file__).resolve().parents[2]
CONTRACT=ROOT/'shared/tsr/applicability'

def load(name):return json.loads((CONTRACT/name).read_text())
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/f'scripts/tsr/applicability/{name}.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_versioned_batches_and_strict_schema():
    schema=load('evidence-v1.schema.json');jsonschema.Draft202012Validator.check_schema(schema)
    validator=jsonschema.Draft202012Validator(schema)
    vectors=load('golden-vectors-v1.json')
    for scenario in vectors['scenarios']:
        assert scenario['origin']=='synthetic'
        for batch in scenario['batches']:validator.validate(batch)
    bad=copy.deepcopy(vectors['scenarios'][0]['batches'][0]);bad['prediction_is_truth']=True
    with pytest.raises(jsonschema.ValidationError):validator.validate(bad)
    bad.pop('prediction_is_truth');bad['candidates'][0]['box']['width']=0
    with pytest.raises(jsonschema.ValidationError):validator.validate(bad)

def test_configuration_identity_and_frozen_contracts():
    expected=hashlib.sha256((CONTRACT/'policy-v1.json').read_bytes()).hexdigest()
    for source in [ROOT/'iphone/SpeedConsumerApp/TrafficSignApplicability.swift',ROOT/'android/app/src/main/java/de/youspeed/android/alpha/TrafficSignApplicability.kt']:
        assert expected in source.read_text()
        assert '"shadow"' in source.read_text()
    assert load('policy-v1.json')['mode']=='shadow'
    assert load('qualification-gates-v1.json')['approvedHoldoutHash'] is None

def encounter(name='encounter-1',**kwargs):
    return dict(encounterId=name,driveId='drive-1',physicalSignId='sign-1',routeGroup='route-1',duplicateGroups=['dup-1'],split='holdout',origin='reviewed_real',reviewer='test-reviewer',provenance='test fixture only',scenario='ego_yield',roadClass='primary',signClassCorrect=True,applicability='ego',distanceKm=0,durationHours=0,**kwargs)

def prediction(name='encounter-1',**kwargs):
    return dict(encounterId=name,immediateEvents=[],passageEvents=[],unknown=True,incrementalProcessingMs=[],**kwargs)

def test_zero_exposure_and_blanket_suppression_cannot_pass():
    sc=module('scorecard');e=encounter();m=sc.summarize([e],{e['encounterId']:prediction()})
    assert m['falseImmediatePerKm'] is None and m['falseImmediatePerHour'] is None
    assert m['precision'] is None and m['recall']==0 and m['missedValidSigns']==1
    assert m['recallWilson95'][0]==0

def test_split_leakage_includes_route_and_transitive_signs():
    sc=module('scorecard');a=encounter();b=copy.deepcopy(a);b.update(encounterId='encounter-2',driveId='drive-2',physicalSignId='sign-2',duplicateGroups=['dup-2'],split='calibration')
    with pytest.raises(ValueError,match='leakage'):sc.validate_corpus(dict(schemaVersion=1,encounters=[a,b]))

def test_unknown_truth_never_becomes_negative_and_zero_distance_numerator_excluded():
    sc=module('scorecard');a=encounter();a['applicability']='unknown'
    p=prediction();p['immediateEvents']=[dict(eventId='e1',classCorrect=False,wrongDirection=False,dangerousSubstitution=False)]
    m=sc.summarize([a],{a['encounterId']:p})
    assert m['falseImmediate']==0 and m['precision'] is None and m['knownTruthEncounters']==0

def test_golden_generator_is_reproducible():
    assert module('generate_fixtures').build()==load('golden-vectors-v1.json')


def test_generated_native_configuration_does_not_drift():
    import subprocess
    subprocess.run(["python3", str(ROOT / "scripts/tsr/applicability/sync_configuration.py"), "--check"], check=True)


def test_metadata_import_preserves_immutable_links_and_source_truth_separation():
    importer=module('import_diagnostics')
    batch=load('golden-vectors-v1.json')['scenarios'][0]['batches'][0]
    envelope=dict(schemaVersion=1,batch=batch,tracks=[],decisions=[])
    text='timestamp=now tsr_applicability_v1='+json.dumps(envelope)
    assert importer.extract(text)==[envelope]
    assert importer.extract(json.dumps(dict(event='tsr_applicability_v1',evidence=json.dumps(envelope))))==[envelope]
    changed=copy.deepcopy(envelope);changed['batch']['candidates'][0]['rawScore']=0.2
    with pytest.raises(ValueError,match='Conflicting'):
        importer.extract(text+'\n'+'tsr_applicability_v1='+json.dumps(changed))


def test_original_class_id_is_optional_presentation_evidence():
    validator = jsonschema.Draft202012Validator(load('evidence-v1.schema.json'))
    batch = copy.deepcopy(load('golden-vectors-v1.json')['scenarios'][0]['batches'][0])
    validator.validate(batch)  # Old captures have no class ID.
    candidate = batch['candidates'][0]
    candidate['semanticKey'] = 'unknown::'
    candidate['rawClassId'] = 'AB3a'
    validator.validate(batch)
    candidate['rawClassId'] = None
    validator.validate(batch)
    for invalid in ['', 42, {'label': 'AB3a'}]:
        candidate['rawClassId'] = invalid
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(batch)


def test_frame_country_is_optional_and_requires_iso2_when_present():
    validator = jsonschema.Draft202012Validator(load('evidence-v1.schema.json'))
    batch = copy.deepcopy(load('golden-vectors-v1.json')['scenarios'][0]['batches'][0])
    validator.validate(batch)
    for country in ['DE', 'FR', 'BE', 'NL', 'CH', None]:
        batch['country'] = country
        validator.validate(batch)
    for invalid in ['', 'France', 42]:
        batch['country'] = invalid
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(batch)
