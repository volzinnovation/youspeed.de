import importlib.util
import json
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('field_intake',ROOT/'scripts/tsr/prepare_de_field_evaluation.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def mobile(identifier,route,longitude=10,latitude=51,size=32,sighting=None,label='no_stop',date='2026-11-01T12:00:00+00:00'):
    return {'crop_id':identifier,'digest':module.stable(identifier),'installation':'device','epoch':1,
        'sighting_id':sighting or identifier,'captured_at':date,
        'manifest':{'original_box':[0,0,size,size],'actual_box':[0,0,size,2*size],
                    'decoded_width':size,'decoded_height':2*size,'crop_version':'downward-1'},
        'event':{'app':{'platform':'android'},'collection_session_id':route,
                 'vehicle_position':{'longitude':longitude,'latitude':latitude},
                 'classification':{'model_label':label}}}


def run_selection(tmp_path,monkeypatch,rows,pano=None):
    monkeypatch.setattr(module,'load_catalogs',lambda: ({},{}))
    monkeypatch.setattr(module,'resolve_crop_labels',lambda *a,**k: {'status':'unique','country':'DE','class_id':'no_stop'})
    historical=tmp_path/'old.json';supplement=tmp_path/'extra.json'
    module.dump(historical,{'classes':['no_stop','city:start','city:end'],'samples':[{'source_id':'prior-picture','sha256':'a'*64}]})
    module.dump(supplement,{'samples':[]})
    module.dump(tmp_path/'snapshot.json',{'mobile':rows,'panoramax':pano or [],'review_counts':[],
        'historical_manifest_sha256':module.sha(historical),'source_supplement_sha256':module.sha(supplement),
        'exposed_picture_metadata':[{'picture_id':'prior-picture','gps':{'type':'Point','coordinates':[8,49]},'collections':[{'id':'prior-route'}]}]})
    module.select(tmp_path,historical,supplement)
    return json.loads((tmp_path/'selection-frozen.json').read_text())


def test_one_exposed_member_excludes_entire_route(tmp_path,monkeypatch):
    result=run_selection(tmp_path,monkeypatch,[mobile('near','mixed',8.0001,49),mobile('far','mixed'),mobile('new','new')])
    assert [r['crop_id'] for r in result['samples']]==['new']
    rejected=json.loads((tmp_path/'excluded-candidates.json').read_text())
    assert all('within_200m_known_exposure' in r['exclusion_reasons'] for r in rejected)


def test_date_or_missing_route_cannot_escape_via_other_crop(tmp_path,monkeypatch):
    result=run_selection(tmp_path,monkeypatch,[mobile('old','repeat',date='2026-10-20T12:00:00+00:00'),
        mobile('later','repeat'),mobile('missing',None),mobile('new','new')])
    assert [r['crop_id'] for r in result['samples']]==['new']


def test_representative_is_one_per_sighting_and_ignores_predicted_class(tmp_path,monkeypatch):
    result=run_selection(tmp_path,monkeypatch,[mobile('small','r',size=16,sighting='encounter',label='city:start'),
        mobile('large','r',size=32,sighting='encounter',label='no_stop')])
    assert [r['crop_id'] for r in result['samples']]==['large']
    assert result['samples'][0]['truth_label'] is None
    assert not result['selection_uses_predictions']


def test_shared_cross_source_collection_is_excluded(tmp_path,monkeypatch):
    pano=[{'crop_id':'prior-crop','picture_id':'prior-picture','annotation_id':'a','fingerprint':'f','item_fingerprint':'i',
        'digest':'b'*64,'captured_at':'2026-11-01T12:00:00+00:00','gps':{'type':'Point','coordinates':[10,51]},
        'collections':[{'id':'cross-source'}],'geometry':{'sign_in_crop':[0,0,32,32]},'width':32,'height':64,
        'labels':[],'semantics':[]}]
    result=run_selection(tmp_path,monkeypatch,[mobile('phone','cross-source'),mobile('new','new')],pano)
    assert [r['crop_id'] for r in result['samples']]==['new']


def test_coordinates_reject_nonfinite_and_preserve_metric_distance():
    assert module.coord({'longitude':8,'latitude':49})==[8.,49.]
    assert module.coord({'longitude':8,'latitude':float('nan')}) is None
    assert module.coord({'type':'Point','coordinates':[181,49]}) is None
    assert 110<module.distance([8,49],[8,49.001])<112


def test_naive_capture_timestamp_is_not_silently_assigned_a_zone(tmp_path,monkeypatch):
    with pytest.raises(ValueError,match='timezone'):
        run_selection(tmp_path,monkeypatch,[mobile('naive','new',date='2026-11-01T12:00:00')])
