import importlib.util
import json
from pathlib import Path

from PIL import Image
import pytest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/android/prepare_classifier_pair_benchmark.py'
spec = importlib.util.spec_from_file_location('prepare_android_pair', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(tmp_path):
    (tmp_path/'models').mkdir()
    previous = tmp_path/'models/primary136.tflite'
    previous.write_bytes(b'previous-test-fixture')
    model = tmp_path/'new.tflite'
    model.write_bytes(b'\x00\x00\x00\x00TFL3test-fixture-not-for-inference')
    image = tmp_path/'image.png'
    Image.new('RGB',(224,224),'white').save(image)
    old = [f'class:{i}' for i in range(134)] + ['city:start','city:end']
    classes = old + [f'new:{i}' for i in range(6)]
    class_path = tmp_path/'classes.json'
    class_path.write_text(json.dumps({'classes':classes}))
    pending = tmp_path/'manifest.pending.json'
    pending.write_text(json.dumps({'schemaVersion':1,'modes':['gpu'],'warmupCount':20,'rounds':3,'repeatsPerImage':1,
        'models':[{'id':'primary136','path':'models/primary136.tflite','sha256':module.sha(previous),'classCount':136,'classLabels':old}],
        'candidatePending':{'id':'primary142','classCount':142,'classLabels':classes},
        'images':[{'id':str(i),'path':'image.png','canonicalPath':'image.png','sha256':module.sha(image),'canonicalSha256':module.sha(image)} for i in range(96)]}))
    export = tmp_path/'export-report.json'
    export.write_text(json.dumps({'format':'tflite','artifact_sha256':module.sha(model),'checkpoint_sha256':'c'*64,
        'class_index_sha256':module.sha(class_path),'classes':classes,
        'configuration':{'imgsz':224,'batch':1,'half':True,'nms':False,'dynamic':False}}))
    return [pending,class_path,module.sha(class_path),model,module.sha(model),export,'c'*64]


def test_finalization_binds_actual_artifact_and_keeps_output_immutable(tmp_path):
    args = fixture(tmp_path)
    receipt = module.prepare(*args)
    manifest = json.loads((tmp_path/'manifest.json').read_text())
    assert manifest['models'][1]['sha256'] == module.sha(tmp_path/'models/primary142.tflite')
    assert manifest['models'][1]['classCount'] == 142 and 'candidatePending' not in manifest
    assert receipt['gpu_execution_performed'] is False and receipt['field_f1_computed'] is False
    with pytest.raises(ValueError,match='immutable'):
        module.prepare(*args)


def test_finalization_rejects_other_checkpoint_receipt(tmp_path):
    args = fixture(tmp_path)
    args[-1] = 'd'*64
    with pytest.raises(ValueError,match='provenance'):
        module.prepare(*args)
    assert not (tmp_path/'manifest.json').exists()


def test_finalization_rejects_changed_frozen_image(tmp_path):
    args = fixture(tmp_path)
    Image.new('RGB',(224,224),'black').save(tmp_path/'image.png')
    with pytest.raises(ValueError,match='image changed'):
        module.prepare(*args)
    assert not (tmp_path/'manifest.json').exists()
