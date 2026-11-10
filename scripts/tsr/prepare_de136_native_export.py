#!/usr/bin/env python3
"""Prepare pinned DE136 checkpoints for isolated native qualification.

No training, model-pack replacement, deployment, or test-set selection occurs.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

BASELINE = 'f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7'
HELPER = '50e2c478161e13c8b1b67c0dcd8cfbbc7db9d1ce90398c9c5f9f915280b787f7'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_record(record, expected_classes):
    if len(expected_classes) != 136 or expected_classes[-2:] != ['city:start', 'city:end']:
        raise ValueError('Expected the original 134 classes followed by city:start and city:end')
    if record.get('classes') != expected_classes or record.get('family') != 'yolo':
        raise ValueError('Checkpoint class order or architecture differs')
    if record.get('normalization') != 'RGB/255' or record.get('initialization_sha256') != BASELINE:
        raise ValueError('Checkpoint initialization or normalization differs')
    if not isinstance(record.get('state_dict'), dict) or not record['state_dict']:
        raise ValueError('Missing checkpoint state')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course-root', required=True, type=Path)
    parser.add_argument('--checkpoint', required=True, type=Path)
    parser.add_argument('--checkpoint-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--candidate-id', required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a new output directory')
    if sha(args.checkpoint) != args.checkpoint_sha256:
        raise ValueError('Checkpoint digest mismatch')
    helper_path = args.course_root / 'code/model_utils.py'
    if sha(helper_path) != HELPER or sha(args.course_root / 'models/baseline.pt') != BASELINE:
        raise ValueError('Pinned architecture loader or baseline differs')
    sys.path.insert(0, str(helper_path.parent))
    import model_utils as mu
    torch, ultralytics, np, _image, _image_ops = mu.dependencies()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    classes = mu.load_classes(args.course_root / 'data/dataset-v1/class-index.json')
    record = torch.load(args.checkpoint, map_location='cpu', weights_only=True)
    validate_record(record, classes)
    model = mu.extend_classifier(torch, mu.load_baseline(torch, ultralytics, args.course_root / 'models/baseline.pt', classes), classes)
    model.load_state_dict(record['state_dict'], strict=True)
    model.float().eval()
    model.names = dict(enumerate(classes))
    model.yaml = {**model.yaml, 'nc': len(classes)}
    if hasattr(model, 'nc'):
        model.nc = len(classes)
    args.output.mkdir(parents=True)
    output = args.output / (args.candidate_id + '.pt')
    provenance = {'created_at': datetime.now(timezone.utc).isoformat(),
                  'candidate_id': args.candidate_id, 'source_checkpoint_sha256': sha(args.checkpoint),
                  'baseline_sha256': BASELINE, 'helper_sha256': HELPER, 'script_sha256': sha(__file__),
                  'class_index_sha256': sha(args.course_root / 'data/dataset-v1/class-index.json'),
                  'classes': classes, 'source_epoch': record['epoch'],
                  'source_variant': record['variant'], 'source_manifest_sha256': record['manifest_sha256'],
                  'source_partition_sha256': record['partition_sha256'], 'normalization': 'RGB/255',
                  'shape': [1, 3, 224, 224], 'torch': str(torch.__version__),
                  'ultralytics': ultralytics.__version__, 'parameters': sum(p.numel() for p in model.parameters()),
                  'prior_adjustment': False, 'deployed': False}
    torch.save({'model': deepcopy(model), 'ema': None, 'optimizer': None, 'updates': 0,
                'epoch': record['epoch'], 'date': provenance['created_at'], 'version': ultralytics.__version__,
                'train_args': {'task': 'classify', 'imgsz': 224}, 'youspeed_provenance': provenance}, output)
    restored = ultralytics.YOLO(str(output), task='classify').model.float().eval()
    if [restored.names[i] for i in range(136)] != classes:
        raise ValueError('Serialized class order changed')
    torch.manual_seed(20261109)
    probes = [torch.zeros(1, 3, 224, 224), torch.ones(1, 3, 224, 224), torch.rand(1, 3, 224, 224),
              torch.linspace(0, 1, 3 * 224 * 224).reshape(1, 3, 224, 224)]
    errors = []
    with torch.inference_mode():
        for probe in probes:
            expected = mu.logits_from_output(model(probe)).softmax(1)
            actual = mu.logits_from_output(restored(probe)).softmax(1)
            errors.append(float((actual - expected).abs().max()))
            if not torch.equal(actual, expected):
                raise ValueError('Checkpoint packaging changed output values')
    provenance.update(artifact_sha256=sha(output), artifact_bytes=output.stat().st_size,
                      synthetic_packaging_probes=4, packaging_probability_max_errors=errors,
                      packaging_parity_is_not_field_accuracy=True)
    (args.output / 'class-index.json').write_text(json.dumps({'classes': classes}, indent=2) + '\n')
    (args.output / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    (args.output / 'executed-prepare.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'candidate': args.candidate_id, 'artifact': str(output), 'sha256': provenance['artifact_sha256'], 'parity': errors}))


if __name__ == '__main__':
    main()
