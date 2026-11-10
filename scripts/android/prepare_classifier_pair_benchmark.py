#!/usr/bin/env python3
"""Finalize a GPU benchmark only from an actual hash-bound native export.

No inference is performed here. The device harness verifies native tensor shape
and dtype when loading the GPU interpreter; this script binds images, class order,
checkpoint provenance and the actual TensorFlow Lite artifact before staging.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil

from PIL import Image


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def contained(root, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Artifact path escapes fixture')
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError('Artifact path escapes fixture')
    return resolved


def prepare(pending, classes_path, classes_sha256, model_path, model_sha256,
            export_path, checkpoint_sha256):
    root = pending.parent
    target = root / 'manifest.json'
    if target.exists():
        raise ValueError('Keep finalized benchmark manifests immutable')
    if sha(classes_path) != classes_sha256 or sha(model_path) != model_sha256:
        raise ValueError('Class index or model digest differs')
    config = json.loads(pending.read_text())
    classes = json.loads(classes_path.read_text())['classes']
    report = json.loads(export_path.read_text())
    if (report['format'] != 'tflite' or report['artifact_sha256'] != model_sha256
            or report['checkpoint_sha256'] != checkpoint_sha256
            or report['class_index_sha256'] != classes_sha256 or report['classes'] != classes):
        raise ValueError('Export provenance differs from frozen candidate')
    if report['configuration'] != {'imgsz':224, 'batch':1, 'half':True, 'nms':False, 'dynamic':False}:
        raise ValueError('Unexpected native export configuration')
    with model_path.open('rb') as stream:
        if stream.read(8)[4:8] != b'TFL3':
            raise ValueError('Not a TensorFlow Lite FlatBuffer')
    if (config['schemaVersion'] != 1 or config['modes'] != ['gpu']
            or config['warmupCount'] != 20 or config['rounds'] != 3
            or config['repeatsPerImage'] != 1 or len(config['models']) != 1):
        raise ValueError('Expected the frozen paired GPU-only protocol')
    predecessor = config['models'][0]
    if (len(classes) <= predecessor['classCount']
            or classes[:predecessor['classCount']] != predecessor['classLabels']
            or len(set(classes)) != len(classes)):
        raise ValueError('Expanded class order changes predecessor indices')
    candidate = config['candidatePending']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', candidate['id']):
        raise ValueError('Unsafe candidate identifier')
    if candidate['classLabels'] != classes or candidate['classCount'] != len(classes):
        raise ValueError('Pending candidate order differs')
    if sha(contained(root, predecessor['path'])) != predecessor['sha256']:
        raise ValueError('Frozen predecessor artifact changed')
    ids = [row['id'] for row in config['images']]
    if len(ids) != 96 or len(set(ids)) != 96:
        raise ValueError('Expected 96 unique frozen images')
    for row in config['images']:
        for field, digest in [('path', 'sha256'), ('canonicalPath', 'canonicalSha256')]:
            path = contained(root, row[field])
            if sha(path) != row[digest]:
                raise ValueError('Frozen image changed')
        with Image.open(contained(root, row['canonicalPath'])) as im:
            if im.format != 'PNG' or im.size != (224,224):
                raise ValueError('Canonical image is not224RGB PNG')
    destination = root / 'models' / (candidate['id'] + '.tflite')
    if destination.exists() and sha(destination) != model_sha256:
        raise ValueError('Refusing to replace another staged model')
    if not destination.exists():
        shutil.copyfile(model_path, destination)
    if sha(destination) != model_sha256:
        raise ValueError('Staged model bytes differ')
    output = copy.deepcopy(config)
    output.pop('candidatePending')
    output['models'].append({'id':candidate['id'], 'path':destination.relative_to(root).as_posix(),
                             'sha256':model_sha256, 'classCount':len(classes), 'classLabels':classes})
    target.write_text(json.dumps(output, indent=2) + '\n')
    receipt = {'status':'staged_awaiting_device', 'pending_manifest_sha256':sha(pending),
               'manifest_sha256':sha(target), 'export_report_sha256':sha(export_path),
               'checkpoint_sha256':checkpoint_sha256, 'candidate_sha256':model_sha256,
               'class_index_sha256':classes_sha256, 'class_count':len(classes),
               'image_count':96, 'all_image_hashes_verified':True,
               'predecessor_sha256':predecessor['sha256'], 'script_sha256':sha(__file__),
               'native_tensor_contract':'Device load must verify Float32 NHWC[1,224,224,3] and Float32[1,classCount]',
               'gpu_execution_performed':False, 'cpu_inference_performed':False,
               'human_labels_read':False, 'field_f1_computed':False, 'production_deployed':False}
    (root / 'finalization-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['pending','classes','model','export-report']:
        p.add_argument('--'+name, type=Path, required=True)
    for name in ['classes-sha256','model-sha256','checkpoint-sha256']:
        p.add_argument('--'+name, required=True)
    a = p.parse_args()
    print(json.dumps(prepare(a.pending, a.classes, a.classes_sha256, a.model,
                             a.model_sha256, a.export_report, a.checkpoint_sha256), indent=2))


if __name__ == '__main__':
    main()
