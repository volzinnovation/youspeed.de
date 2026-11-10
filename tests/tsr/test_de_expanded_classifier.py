import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.tsr.de_expanded_classifier import (
    apply_training_relabels, bind_exposure_ledger, deduplicate_existing, exclude_groups,
    historical_selection_rows, identity_values, normalize_expanded_metrics,
    real_new_class_eligibility, require_eligible_checkpoint, sha, split_new_rows,
    training_image_rgb, validate_classes, verify_new_rows,
)


def base_classes():
    return [f"old:{i}" for i in range(134)] + ["city:start", "city:end"]


def test_prefix_is_immutable_but_total_is_not_hardcoded():
    base=base_classes()
    validate_classes(base,base+["bus:stop","supplementary:plate","new:other"])
    with pytest.raises(ValueError,match="append-only"):
        validate_classes(base,base[::-1]+["new:other"])
    with pytest.raises(ValueError,match="append-only"):
        validate_classes(base,base+["city:end"])


def test_collection_prefix_normalizes_identity():
    assert "abc" in identity_values({"route_tokens":["collection:abc"]})


def test_one_overlap_excludes_the_entire_new_route():
    rows=[{"sample_id":"one","group_id":"route","sha256":"shared"},
          {"sample_id":"two","group_id":"route","sha256":"different"},
          {"sample_id":"three","group_id":"clear","sha256":"clear"}]
    kept,audit=exclude_groups(rows,[{"sha256":"shared"}])
    assert [r["sample_id"] for r in kept]==["three"]
    assert audit[1]["direct_reasons"]==["connected_route_overlap"]


def test_geographic_exclusion_catches_another_collection_of_same_place():
    rows=[{"sample_id":"one","group_id":"other","coordinates":[8.7,48.9]}]
    assert exclude_groups(rows,[{"coordinates":[8.70001,48.90001]}])[0]==[]
    assert len(exclude_groups(rows,[{"coordinates":[9.7,49.9]}])[0])==1


def test_silver_development_uses_whole_real_groups_and_preserves_train_support():
    rows=[{"group_id":f"real:{i}","label":"new","label_origin":"assistant_visual_silver"} for i in range(4)]
    rows += [{"group_id":"art","label":"new","label_origin":"official_pictogram"}]
    train,dev,groups=split_new_rows(rows,["new"])
    assert len(groups)==1 and len(dev)==1
    assert dev[0]["label_origin"]=="assistant_visual_silver"
    assert any(x["group_id"]=="art" for x in train)
    assert {r["group_id"] for r in train}.isdisjoint(r["group_id"] for r in dev)
    assert split_new_rows(rows,["new"])==(train,dev,groups)


def test_singleton_and_artwork_have_no_fabricated_dev_evidence():
    rows=[{"group_id":"one","label":"new","label_origin":"assistant_visual_silver"},
          {"group_id":"art","label":"new","label_origin":"official_pictogram"}]
    assert split_new_rows(rows,["new"])[1]==[]


def test_explicit_training_only_sources_never_enter_development():
    rows=[{"group_id":f"real:{i}","label":"new","label_origin":"assistant_visual_silver","training_only":True,"evaluation_eligible":False} for i in range(4)]
    assert split_new_rows(rows,["new"])[1]==[]


def intake(tmp_path,origin="assistant_visual_silver",reviewed=False):
    image=tmp_path/"one.png";Image.new("RGB",(16,20),"red").save(image)
    record={"sample_id":"one","group_id":"route","label":"new","label_origin":origin,
            "path":"one.png","sha256":sha(image),"human_reviewed":reviewed,"sign_box":[1,2,12,18]}
    path=tmp_path/"intake.json";path.write_text(json.dumps({"samples":[record]}))
    return path,record


def test_verified_silver_keeps_its_provenance_and_explicit_crop(tmp_path):
    path,_=intake(tmp_path)
    row=verify_new_rows(path,["old","new"])[0]
    assert row["class_index"]==1 and row["human_reviewed"] is False
    assert row["training_crop_box"]==[1,2,12,18] and row["sign_rgb_sha256"]


def test_silver_cannot_be_promoted_to_human_truth(tmp_path):
    path,_=intake(tmp_path,reviewed=True)
    with pytest.raises(ValueError,match="human reference"):
        verify_new_rows(path,["new"])


def test_model_pseudolabels_cannot_silently_enter_new_data(tmp_path):
    path,_=intake(tmp_path,origin="model_prediction")
    with pytest.raises(ValueError,match="provenance"):
        verify_new_rows(path,["new"])


def test_modified_image_is_rejected(tmp_path):
    path,_=intake(tmp_path)
    Image.new("RGB",(16,20),"green").save(tmp_path/"one.png")
    with pytest.raises(ValueError,match="hash mismatch"):
        verify_new_rows(path,["new"])


def test_contradictory_identical_new_pixels_are_rejected(tmp_path):
    path,row=intake(tmp_path)
    path.write_text(json.dumps({"samples":[row,{**row,"sample_id":"two","label":"other"}]}))
    with pytest.raises(ValueError,match="conflicting labels"):
        verify_new_rows(path,["new","other"])


def test_historical_pixel_relabel_requires_explicit_resolution():
    old=[{"sample_id":"old","label":"lanes","sha256":"same"}]
    with pytest.raises(ValueError,match="historical training pixels"):
        deduplicate_existing([{"sample_id":"new","label":"DE:223.1-50","sha256":"same"}],old)
    kept,duplicates=deduplicate_existing([{"sample_id":"duplicate","label":"lanes","sha256":"same"}],old)
    assert kept==[] and duplicates==["duplicate"]


def test_derived_plate_is_distinct_from_its_training_assembly():
    old=[{"sample_id":"assembly","label":"other:multi","sha256":"parent","rgb_sha256":"assembly-pixels"}]
    child={"sample_id":"plate","label":"supplementary:plate","sha256":"parent","training_crop_box":[0,10,10,20],"sign_rgb_sha256":"plate-pixels"}
    assert deduplicate_existing([child],old)[0]==[child]


def test_training_only_relabel_and_immutable_eval_conflict():
    base=base_classes();classes=base+["DE:325.1"]
    train=[{"sample_id":"one","label":"other","sha256":"hash","class_index":0}]
    evaluation=[{"sample_id":"eval","label":"other","sha256":"eval-hash","class_index":0}]
    proposal={"sample_id":"one","old_label":"other","proposed_label":"DE:325.1","sha256":"hash","label_origin":"assistant_visual_silver","human_reviewed":False}
    review={"training_relabels":[proposal],"evaluation_conflicts":[{**proposal,"sample_id":"eval","sha256":"eval-hash"}]}
    updated,conflicts=apply_training_relabels(train,evaluation,review,classes)
    assert updated[0]["label"]=="DE:325.1" and train[0]["label"]=="other"
    assert evaluation[0]["label"]=="other" and conflicts==["eval"]
    with pytest.raises(ValueError,match="TRAIN"):
        apply_training_relabels(train,evaluation,{"training_relabels":[{**proposal,"sample_id":"eval"}]},classes)


def test_new_old_class_silver_cannot_select_checkpoint_from_a_mixed_group():
    rows = []
    for i in range(3):
        for label, index in [('new', 136), ('old', 0)]:
            rows.append({'sample_id': f'{label}-{i}', 'group_id': f'route-{i}',
                         'label': label, 'class_index': index, 'label_origin': 'assistant_visual_silver',
                         'is_new_intake': True})
    _, new_dev, _ = split_new_rows(rows, ['new'])
    assert any(r['class_index'] == 0 for r in new_dev)
    historical = {'sample_id': 'historical', 'class_index': 0}
    conflict = {'sample_id': 'conflict', 'class_index': 0}
    assert historical_selection_rows(new_dev + [historical, conflict], {'conflict'}) == [historical]


def test_unsupported_false_positive_remains_unmeasured_and_city_absence_is_null():
    # Same structure as the pinned helper: absent classes can receive F1 zero
    # from false positives, but this is not evidence of measured class recall.
    rows = [{'support': 0, 'recall': None, 'f1': 0, 'precision': 0} for _ in range(138)]
    rows[0].update(support=2, recall=.5, f1=.5, precision=.5)
    result = normalize_expanded_metrics({'macro_f1_supported': .5, 'per_class': rows})
    assert result['macro_f1_supported'] == .5
    assert result['per_class'][136]['f1'] is None
    assert result['per_class'][136]['precision'] == 0
    assert result['city_macro_f1_supported'] is None
    assert result['new_class_macro_f1_supported'] is None


def eligibility_rows():
    return [{'sample_id': 'real-a', 'label': 'new:a', 'class_index': 136, 'split': 'train',
             'label_origin': 'assistant_visual_silver'},
            {'sample_id': 'real-b', 'label': 'new:b', 'class_index': 137, 'split': 'train',
             'label_origin': 'assistant_visual_silver'},
            {'sample_id': 'art-b', 'label': 'new:b', 'class_index': 137, 'split': 'train',
             'label_origin': 'official_pictogram'}]


def test_correct_artwork_cannot_replace_failed_real_training_examples():
    classes = base_classes() + ['new:a', 'new:b']
    result = real_new_class_eligibility(eligibility_rows(), [136, 0, 137], classes)
    assert result['eligible'] is False
    assert result['classes_without_correct_real_prediction'] == ['new:b']
    assert result['per_class'][1]['real_training_support'] == 1
    assert result['per_class'][1]['correct_real_training_predictions'] == 0
    assert result['human_field_f1'] is False


def test_one_correct_real_training_example_per_class_is_minimum_eligibility():
    classes = base_classes() + ['new:a', 'new:b']
    result = real_new_class_eligibility(eligibility_rows(), [136, 137, 0], classes)
    assert result['eligible'] is True
    assert all(r['correct_real_training_predictions'] == 1 for r in result['per_class'])
    assert result['human_field_f1'] is False


def test_artwork_only_class_is_ineligible_even_if_predicted_correctly():
    rows = eligibility_rows()
    result = real_new_class_eligibility([rows[0], rows[2]], [136, 137], base_classes() + ['new:a', 'new:b'])
    assert result['eligible'] is False
    assert result['classes_without_real_support'] == ['new:b']


def test_eligibility_never_uses_dev_or_report_truth():
    rows = eligibility_rows(); rows[1]['split'] = 'report'
    with pytest.raises(ValueError, match='only matching TRAIN'):
        real_new_class_eligibility(rows, [136, 137, 137], base_classes() + ['new:a', 'new:b'])


def test_all_ineligible_epochs_fail_before_native_export_even_if_checkpoint_exists(tmp_path):
    (tmp_path / 'best.pt').write_bytes(b'Not a selected eligible checkpoint')
    with pytest.raises(RuntimeError, match='native checkpoint export is forbidden'):
        require_eligible_checkpoint(tmp_path, [])
    receipt = json.loads((tmp_path / 'complete.json').read_text())
    assert receipt['status'] == 'failed_no_eligible_epoch'
    assert receipt['native_export_created'] is False
    assert not (tmp_path / 'expanded-native.pt').exists()


def test_exposure_ledger_binds_prior_test_inspection_without_opening_pixels(tmp_path):
    manifest = {'samples': [{'sample_id': 'one', 'sha256': 'a' * 64, 'split': 'test'}]}
    ledger = {'schema': 'youspeed-taxonomy-exposure-ledger-v1',
              'records': [{'historical_sample_id': 'one', 'sha256': 'a' * 64, 'historical_split': 'test'}],
              'counts_by_historical_split': {'test': 1}}
    path = tmp_path / 'ledger.json'; path.write_text(json.dumps(ledger))
    bound = bind_exposure_ledger(path, manifest)
    assert bound['sha256'] == sha(path) and bound['earlier_test_pixels_exposed'] is True
    ledger['records'][0]['historical_split'] = 'train'
    path.write_text(json.dumps(ledger))
    with pytest.raises(ValueError, match='identity or split mismatch'):
        bind_exposure_ledger(path, manifest)


def test_palette_transparency_matches_rgba_artwork_and_preserves_opaque_ink(tmp_path):
    indexed = Image.new('P', (2, 1))
    indexed.putpalette([0, 0, 0, 255, 0, 0] + [0] * (768 - 6))
    indexed.putdata([0, 1]); indexed.info['transparency'] = 0
    path = tmp_path / 'palette.png'; indexed.save(path)
    with Image.open(path) as image:
        assert image.mode == 'P' and 'A' not in image.getbands()
        rendered = training_image_rgb(image, official_artwork=True)
    rgba = Image.new('RGBA', (2, 1)); rgba.putdata([(0, 0, 0, 0), (255, 0, 0, 255)])
    assert [rendered.getpixel((x, 0)) for x in range(2)] == [(238, 238, 238), (255, 0, 0)]
    assert rendered.tobytes() == training_image_rgb(rgba, official_artwork=True).tobytes()
    intake_path = tmp_path / 'intake.json'
    intake_path.write_text(json.dumps({'samples': [{'sample_id': 'art', 'group_id': 'art',
        'label': 'new', 'label_origin': 'official_pictogram', 'human_reviewed': False,
        'path': path.name, 'sha256': sha(path)}]}))
    import hashlib
    verified = verify_new_rows(intake_path, ['new'])[0]
    assert verified['sign_rgb_sha256'] == hashlib.sha256(
        str(rendered.size).encode() + b'\0' + rendered.tobytes()).hexdigest()
