#!/usr/bin/env python3
"""One sealed, phone-input geographic evaluation; no audit threshold search."""
import argparse
import hashlib
import json
from pathlib import Path
import random

import train_evaluate as base
import mobile_replay as phone


def paired_intervals(left, right, iterations=2000, seed=14):
    """Resample identical geographic groups for the candidate-minus-baseline delta."""
    a = {r['group_id']: r for r in left['frames']}
    b = {r['group_id']: r for r in right['frames']}
    assert len(a) == len(left['frames']) and set(a) == set(b)
    keys = sorted(a)
    rng = random.Random(seed)
    samples = {k: [] for k in ('precision', 'recall', 'f2')}
    for _ in range(iterations):
        picked = rng.choices(keys, k=len(keys))
        totals = [base.metrics({k: sum(rows[g][k] for g in picked)
                               for k in ('tp', 'fp', 'fn')}) for rows in (a, b)]
        for k in samples:
            samples[k].append(totals[1][k] - totals[0][k])
    return {'method': 'paired geographic-group percentile bootstrap, d8 minus d4',
            'iterations': iterations, 'seed': seed, 'groups': len(keys),
            'intervals': {k: [sorted(v)[int(.025*(iterations-1))],
                              sorted(v)[int(.975*(iterations-1))]] for k, v in samples.items()},
            'limitation': 'Small assistant-reviewed audit; not human-certified population accuracy.'}


def main(args):
    import torch
    import ultralytics
    from ultralytics import YOLO
    from PIL import Image
    assert ultralytics.__version__ == '8.4.213'
    definition_path = Path(args.definition)
    assert base.sha(definition_path) == args.definition_sha256
    definition = json.loads(definition_path.read_text())
    assert definition['schema'] == 'streetshots-geographic-evaluation-v1'
    for source in (Path(__file__), Path(base.__file__), Path(phone.__file__)):
        assert base.sha(source) == definition['scripts'][source.name]
    assert definition['fixed_phone_threshold'] == phone.PHONE_THRESHOLD
    assert definition['matching_iou'] == .5 and definition['source_nms_iou'] == .45
    assert definition['inference_floor'] == .25 and definition['per_pass_proposal_cap'] == 12
    assert definition['quantize'] == 32 and definition['tile'] is False
    root = Path(args.root).resolve()
    manifest_path = base.checked_path(root, definition['reference_manifest'], definition['reference_manifest_sha256'])
    manifest = json.loads(manifest_path.read_text())
    assert manifest['schema'] == 'streetshots-blind-audit-references-v1'
    assert manifest['complete'] and manifest['student_predictions_seen'] is False
    frames = manifest['frames']
    assert frames and all(r['annotation_complete'] and r['admitted'] for r in frames)
    native_root = root / definition['native_directory']
    native_path = base.checked_path(native_root, 'manifest.json', definition['native_manifest_sha256'])
    native = json.loads(native_path.read_text())
    assert native['source_images'] == len(frames)
    rows = {(r['image_id'], r['mode'], r['pass_index']): r for r in native['frames']}
    assert len(rows) == len(native['frames'])
    specs = definition['models']
    assert [s['name'] for s in specs] == ['d4', 'd8']
    for spec in specs:
        assert base.sha(spec['path']) == spec['sha256']
        assert .25 <= spec['development_phone_threshold'] <= .99
    output = root / 'evaluation'
    output.mkdir(exist_ok=False)  # Never silently re-evaluate or overwrite a consumed audit.
    (output / 'images').mkdir()
    base.write(output / 'started.json', {'definition_sha256': args.definition_sha256})
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    summary = {}
    for spec in specs:
        checkpoint = spec['path']
        if spec['name'] == 'd4':
            assert spec['sha256'] == base.D4_SHA
            checkpoint = output / 'd4-runtime.pt'
            base.save_yolo(checkpoint, base.sign_model('d4', args.coco, spec['path']), 0)
        model = YOLO(checkpoint)
        records = []
        for frame in frames:
            path = base.checked_path(root, frame['image_path'], frame['image_sha256'])
            with Image.open(path) as src:
                image = src.convert('RGB')
            assert list(image.size) == frame['dimensions']
            passes = []
            for index, window in enumerate(phone.windows(*image.size)):
                row = rows[(frame['image_id'], 'phone_windows', index)]
                assert row['source_sha256'] == frame['image_sha256']
                assert row['window_xyxy'] == list(window)
                path = base.checked_path(native_root, row['path'], row['sha256'])
                with Image.open(path) as src:
                    rendered = src.convert('RGB')
                assert rendered.size == (1024, 1024)
                result = model.predict(rendered, imgsz=1024, conf=.25, iou=.45,
                    max_det=300, rect=False, device=0, quantize=32, tile=False,
                    channels_last=False, verbose=False)[0]
                proposals = []
                for box, score, cls in zip(result.boxes.xyxy.cpu().tolist(),
                                          result.boxes.conf.cpu().tolist(), result.boxes.cls.cpu().tolist()):
                    mapped = phone.source_box(box, window)
                    if cls == 0 and mapped:
                        proposals.append({'box': mapped, 'score': score})
                passes.append(proposals)
            records.append({'image_id': frame['image_id'], 'group_id': frame['group_id'],
                            'truth': frame['boxes_xyxy'], 'passes': passes,
                            'acceptable_extra_candidates': frame['acceptable_extra_candidates']})
        base.write(output / (spec['name'] + '-raw-passes.json'), records)
        for setting, threshold in [('fixed_phone', phone.PHONE_THRESHOLD),
                                   ('development_selected', spec['development_phone_threshold'])]:
            scored = []
            for frame, record in zip(frames, records):
                predictions, truncated = phone.admit(record['passes'], threshold)
                scored.append({**record, 'predictions': predictions, 'truncated': truncated})
                path = base.checked_path(root, frame['image_path'], frame['image_sha256'])
                with Image.open(path) as src:
                    image = src.convert('RGB')
                stem = f"{spec['name']}-{setting}-{frame['image_id']}"
                phone.visual(image, record['truth'], predictions, output / 'images' / (stem + '.jpg'))
            result = base.score_frames(scored, threshold)
            result['bootstrap'] = base.bootstrap_groups(result)
            result['proposals_per_image'] = (result['tp'] + result['fp']) / len(frames)
            summary[f"{spec['name']}-{setting}"] = result
            base.write(output / f"{spec['name']}-{setting}-predictions.json", scored)
    comparisons = {setting: paired_intervals(summary['d4-' + setting], summary['d8-' + setting])
                   for setting in ('fixed_phone', 'development_selected')}
    base.write(output / 'summary.json', {'schema': 'streetshots-geographic-audit-results-v1',
        'definition_sha256': args.definition_sha256, 'reference_manifest_sha256': base.sha(manifest_path),
        'images': len(frames), 'groups': len({f['group_id'] for f in frames}),
        'reference_boxes': sum(len(f['boxes_xyxy']) for f in frames),
        'results': summary, 'paired_candidate_minus_baseline': comparisons,
        'script_sha256': base.sha(__file__), 'models': specs,
        'new_holdout_evaluation': True, 'human_certified': False,
        'ios_coreml_parity_verified': False, 'thresholds_selected_on_audit': False})
    base.write(output / 'complete.json', {'complete': True, 'summary_sha256': base.sha(output / 'summary.json')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('definition', 'definition-sha256', 'root', 'coco'):
        parser.add_argument('--' + name, required=True)
    main(parser.parse_args())
