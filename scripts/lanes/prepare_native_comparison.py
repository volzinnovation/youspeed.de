#!/usr/bin/env python3
"""Export verified independent test stills and all frozen paint-head predictions.

No training, label tuning, sequence synthesis or production policy mutation.
Original-size RGB enters the model; native inputs use the established center-
sampled grayscale contract. Targets and predictions are separate artifacts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(2**20), b''):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--code-root', type=Path, required=True)
    p.add_argument('--prior-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--local-input-root', type=Path, required=True)
    a = p.parse_args()
    sys.path.insert(0, str(a.code_root / 'scripts/lanes'))
    import cv2
    import numpy as np
    import torch
    import train_a2d2_auxiliary as aux
    import train_mixed_auxiliary as mixed
    from a2d2_baseline import sample_indices
    from evaluate_auxiliary_video import inverse_letterbox
    protocol = json.loads((a.prior_root / 'protocol.json').read_text())
    device, runtime = aux.configure_execution('cuda:0', 20261009, 'seeded')
    if a.output.exists():
        raise ValueError('Refuse to overwrite prepared evidence')
    a.output.mkdir(parents=True)
    for directory in ('gray', 'paint', 'valid', 'rgb', 'probabilities'):
        (a.output / directory).mkdir()
    started = time.time()
    write(a.output / 'status.json', dict(status='running', startedUnix=started))
    detector_path = Path(protocol['detector']['path'])
    assert sha(detector_path) == protocol['detector']['sha256']
    detector = aux.load_detector(detector_path, device)
    heads, head_records, expected = {}, [], {}
    for seed in protocol['training']['seeds']:
        for arm in protocol['training']['arms']:
            directory = a.prior_root / 'runs' / ('seed-' + str(seed)) / arm
            checkpoint_path = directory / 'auxiliary-marking.pt'
            metrics = json.loads((directory / 'metrics.json').read_text())
            digest = sha(checkpoint_path)
            assert digest == metrics['checkpointSha256']
            checkpoint = torch.load(checkpoint_path, weights_only=True, map_location='cpu')
            assert checkpoint['config']['detectorSha256'] == sha(detector_path)
            assert metrics['bestEpoch'] == 10
            head = aux.AuxiliaryMarkingHead()
            head.load_state_dict(checkpoint['headState'])
            key = f'{arm}-seed-{seed}'
            heads[key] = head.to(device).eval()
            (a.output / 'probabilities' / key).mkdir()
            head_records.append(dict(id=key, arm=arm, seed=seed, checkpointSha256=digest,
                                     sourceMetricsSha256=sha(directory / 'metrics.json')))
            expected[key] = {(r['dataset'], r['frame_id']): r['counts']
                             for name, data in metrics['evaluation'].items() if name.endswith('/test')
                             for r in data['frameCounts']}
    frames, targets, predictions, sources, differences = [], [], [], [], []
    for dataset, group in [('ZOD', 'qualified_dataset'), ('A2D2', 'a2d2')]:
        spec = protocol[group]
        manifest_path = Path(spec['manifest_path'])
        assert sha(manifest_path) == spec['manifest_sha256']
        manifest = json.loads(manifest_path.read_text())
        objects = {r['key']: r for r in manifest['objects']}
        pairs = [r for r in manifest['pairs'] if r['split'] == 'test']
        assert len(pairs) == (100 if dataset == 'ZOD' else 32)
        sources.append(dict(dataset=dataset, manifestSha256=sha(manifest_path), frames=len(pairs)))
        for ordinal, pair in enumerate(pairs):
            keys = ('rgb', 'label', 'valid') if dataset == 'ZOD' else ('rgb', 'label')
            for field in keys:
                obj = objects[pair[field]]
                assert sha(obj['local_path']) == obj['sha256'], pair[field]
            if dataset == 'ZOD':
                rgb, positive, valid = mixed.load_zod_pair(pair, objects)
                source_id, group_id = pair['frame_id'], pair['group_id']
            else:
                rgb = cv2.cvtColor(cv2.imread(objects[pair['rgb']]['local_path']), cv2.COLOR_BGR2RGB)
                label = cv2.cvtColor(cv2.imread(objects[pair['label']]['local_path']), cv2.COLOR_BGR2RGB)
                positive, valid = aux.decode_labels(label, manifest['class_map'])
                source_id, group_id = pair['rgb'], pair['capture_date']
            height, width = rgb.shape[:2]
            xs, ys = sample_indices(width, height)
            w, h = len(xs), len(ys)
            fid = f'{dataset.lower()}-{ordinal:03d}'
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)[np.ix_(ys, xs)]
            paint_small = cv2.resize((positive & valid).astype(np.float32), (w, h), interpolation=cv2.INTER_AREA) > 0
            valid_small = cv2.resize(valid.astype(np.float32), (w, h), interpolation=cv2.INTER_AREA) >= .999999
            paint_small &= valid_small
            files = dict(gray=f'gray/{fid}.gray', paint=f'paint/{fid}.png', valid=f'valid/{fid}.png', rgb=f'rgb/{fid}.png')
            (a.output / files['gray']).write_bytes(gray.tobytes())
            for key, values in [('paint', paint_small.astype(np.uint8)*255), ('valid', valid_small.astype(np.uint8)*255),
                                ('rgb', cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), (w,h), interpolation=cv2.INTER_AREA))]:
                assert cv2.imwrite(str(a.output / files[key]), values)
            local = lambda key: str(a.local_input_root / files[key])
            gray_sha = sha(a.output / files['gray'])
            frames.append(dict(id=fid, sequenceId=fid, time=0., grayPath=local('gray'), graySha256=gray_sha,
                               width=w, height=h, decodedWidth=width, decodedHeight=height,
                               split='test', dataset=dataset, groupId=group_id, sourceFrameId=source_id))
            targets.append(dict(id=fid, dataset=dataset, split='test', captureGroup=group_id, groupId=group_id,
                                sourceFrameId=source_id, inputSha256=gray_sha, width=w, height=h,
                                imageSha256=objects[pair['rgb']]['sha256'], labelSha256=objects[pair['label']]['sha256'],
                                paintMaskPath=local('paint'), paintMaskSha256=sha(a.output / files['paint']),
                                validMaskPath=local('valid'), validMaskSha256=sha(a.output / files['valid']),
                                previewPath=local('rgb')))
            tensor, transform = aux.letterbox_rgb(rgb, 640)
            truth, validity = mixed.aligned_targets(positive, valid, transform)
            t, v = truth.numpy()[0].astype(bool), validity.numpy()[0].astype(bool)
            with torch.inference_mode():
                features = detector(tensor[None].to(device))
                for key, head in heads.items():
                    probability = torch.nn.functional.interpolate(head(features), (640,640), mode='bilinear', align_corners=False).sigmoid()[0,0].cpu().numpy()
                    pred = probability >= .5
                    counts = dict(tp=int((pred&t&v).sum()), fp=int((pred&~t&v).sum()), fn=int((~pred&t&v).sum()), tn=int((~pred&~t&v).sum()))
                    reference = expected[key][(dataset, source_id)]
                    if counts != reference:
                        differences.append(dict(id=fid, modelId=key, counts=counts, original=reference))
                    restored = inverse_letterbox(probability, transform, w, h)
                    path = Path('probabilities') / key / (fid + '.npy')
                    np.save(a.output / path, restored, allow_pickle=False)
                    predictions.append(dict(id=fid, modelId=key, inputSha256=gray_sha, imageSha256=objects[pair['rgb']]['sha256'],
                                            probabilityPath=str(a.local_input_root / path), probabilitySha256=sha(a.output / path),
                                            width=w, height=h, transform=transform, counts640=counts))
            print(json.dumps(dict(stage='prepared', dataset=dataset, frame=ordinal+1, total=len(pairs))), flush=True)
    write(a.output / 'manifest.json', dict(schemaVersion=1, frames=frames))
    write(a.output / 'targets.json', dict(schemaVersion=1, targets=targets, sources=sources,
          transform='Full-frame aspect preserved; center-sampled OpenCV RGB gray. Targets any-area paint occupancy; valid only when all contributing area valid. Independent stills, no temporal confirmation.',
          qualification='Previously exposed development frames; no ego-lane, sign applicability or device performance ground truth.'))
    write(a.output / 'probability-index.json', dict(schemaVersion=1, models=head_records, predictions=predictions,
          detectorSha256=sha(detector_path), protocolSha256=sha(a.prior_root / 'protocol.json'), runtime=runtime,
          differencesFromOriginalBatchedCounts=differences,
          transformation='Original RGB 640 letterbox; same frozen feature taps and all nine epoch-10 heads; bilinear logits, sigmoid; crop integer letterbox padding; bilinear inverse to native geometry.'))
    write(a.output / 'status.json', dict(status='complete', frames=len(frames), models=len(heads), predictions=len(predictions),
                                      elapsedSeconds=time.time()-started, originalCountDifferences=len(differences)))
    inventory = [dict(path=str(f.relative_to(a.output)), size=f.stat().st_size, sha256=sha(f)) for f in sorted(a.output.rglob('*')) if f.is_file()]
    write(a.output / 'artifact-manifest.json', dict(files=inventory, scriptSha256=sha(__file__)))


if __name__ == '__main__':
    main()
