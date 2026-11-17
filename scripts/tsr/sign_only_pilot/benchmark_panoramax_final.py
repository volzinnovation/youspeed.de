#!/usr/bin/env python3
"""Frozen d10 versus d4 replay; thresholds come only from development evidence."""
import csv
import json
from pathlib import Path

from PIL import Image
import train_latest as base
import mobile_replay as phone
from benchmark_mapillary_auto import measure

JOB = Path('/job')
ROOT = JOB / 'balanced-v1'
SAMPLE = JOB / 'mapillary-auto-v2'
SAMPLE_SHA = '022f5420b45e2a83178deac332fa6a5cff687398913a30cf689f8a8a9824c172'


def main():
    import torch
    import ultralytics
    from ultralytics import YOLO
    base.ml_dependencies()
    torch.set_num_threads(4)
    run = ROOT / 'runs/panoramax'
    seal = json.loads((run / 'seal.json').read_text())
    assert seal['complete'] and seal['completed_epochs'] == 20
    assert base.sha(run / 'selected.pt') == seal['checkpoint_sha256']
    assert base.sha(run / 'history.json') == seal['history_sha256']
    assert base.sha(run / 'configuration.json') == seal['configuration_sha256']
    assert base.sha(SAMPLE / 'manifest.json') == SAMPLE_SHA
    manifest = json.loads((SAMPLE / 'manifest.json').read_text())
    frames = manifest['frames']
    assert len(frames) == 29 and all(not f['training_allowed'] and not f['annotation_complete'] for f in frames)
    prior = ROOT / 'mapillary-benchmark'
    previous_definition = json.loads((prior / 'definition.json').read_text())
    previous = json.loads((prior / 'summary.json').read_text())
    assert previous_definition['sample_manifest_sha256'] == SAMPLE_SHA
    assert previous_definition['native_manifest_sha256'] == base.sha(SAMPLE / 'native-inputs/manifest.json')
    specs = [dict(next(r for r in previous_definition['models'] if r['name'] == name))
             for name in ['d4', 'Panoramax-original']]
    history = json.loads((run / 'history.json').read_text())
    selected = next(r for r in history if r['epoch'] == seal['selected_epoch'])
    assert selected['phone']['threshold'] == seal['threshold']
    specs.append({'name': 'd10-Panoramax-epoch-10', 'path': str(run / 'selected.pt'),
                  'sha256': seal['checkpoint_sha256'], 'threshold': seal['threshold'],
                  'development': selected['phone'], 'fixed_threshold': phone.PHONE_THRESHOLD})
    out = ROOT / 'panoramax-final-benchmark'
    out.mkdir(exist_ok=False)
    definition = {**previous_definition, 'schema': 'panoramax-final-benchmark-definition-v1',
                  'models': specs, 'script_sha256': base.sha(__file__),
                  'training_seal_sha256': base.sha(run / 'seal.json'),
                  'previous_definition_sha256': base.sha(prior / 'definition.json'),
                  'ultralytics': ultralytics.__version__, 'torch': str(torch.__version__),
                  'selection': 'd10 epoch 10 and threshold 0.28 frozen by completed development selection; d4/original thresholds frozen in prior benchmark. No Mapillary tuning.'}
    base.write(out / 'definition.json', definition)
    native = json.loads((SAMPLE / 'native-inputs/manifest.json').read_text())
    lookup = {(r['image_id'], r['mode'], r['pass_index']): r for r in native['frames']}
    images, mapping = [], []
    for frame in frames:
        assert base.sha(SAMPLE / frame['image_path']) == frame['image_sha256']
        for index, window in enumerate(phone.windows(frame['width'], frame['height'])):
            row = lookup[(frame['image_id'], 'phone_windows', index)]
            assert row['window_xyxy'] == list(window) and row['source_sha256'] == frame['image_sha256']
            path = SAMPLE / 'native-inputs' / row['path']
            assert base.sha(path) == row['sha256']
            with Image.open(path) as im:
                images.append(im.convert('RGB'))
            mapping.append((frame['image_id'], window))
    assert len(images) == 58
    results = {}
    for spec in specs:
        assert base.sha(spec['path']) == spec['sha256']
        model = YOLO(spec['path'])
        passes = {f['image_id']: [] for f in frames}
        for offset in range(0, len(images), 2):
            predictions = model.predict(images[offset:offset+2], imgsz=1024, batch=2,
                conf=.25, iou=.45, max_det=300, rect=False, device='0', quantize=32,
                tile=False, channels_last=False, verbose=False)
            for prediction, (identity, window) in zip(predictions, mapping[offset:offset+2]):
                rows = []
                for box, score, cls in zip(prediction.boxes.xyxy.cpu().tolist(),
                        prediction.boxes.conf.cpu().tolist(), prediction.boxes.cls.cpu().tolist()):
                    mapped = phone.source_box(box, window)
                    if cls == 0 and mapped:
                        rows.append({'box': mapped, 'score': score})
                passes[identity].append(rows)
        raw = [{'image_id': f['image_id'], 'passes': passes[f['image_id']]} for f in frames]
        base.write(out / (spec['name'] + '-sample-predictions.json'), raw)
        results[spec['name']] = {mode: {tier: measure(frames, raw, threshold, tier)
            for tier in ['classified_primary', 'broad_front']} for mode, threshold in
            [('fixed', phone.PHONE_THRESHOLD), ('development_calibrated', spec['threshold'])]}
        if spec['name'] in previous['results']:
            assert results[spec['name']] == previous['results'][spec['name']], 'Baseline replay differs'
        print(json.dumps({'model_complete': spec['name'], 'primary': {
            k: v for k, v in results[spec['name']]['development_calibrated']['classified_primary'].items()
            if k not in ['frames', 'size_bins']}}), flush=True)
        del model, predictions
        torch.cuda.empty_cache()
    summary = {'schema': 'panoramax-final-benchmark-results-v1', 'sample_images': len(frames),
        'sample_manifest_sha256': SAMPLE_SHA, 'definition_sha256': base.sha(out / 'definition.json'),
        'selected_epoch': seal['selected_epoch'], 'results': results,
        'baseline_replay_matches_previous': True, 'claim': previous['claim']}
    base.write(out / 'summary.json', summary)
    rows = []
    for name, modes in results.items():
        for mode, tiers in modes.items():
            for tier, score in tiers.items():
                rows.append({'model': name, 'operating_point': mode, 'reference_tier': tier,
                    **{k: v for k, v in score.items() if k not in ['frames', 'size_bins', 'interpretation']}})
    with (out / 'comparison.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    names = list(results)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout='constrained')
    for i, name in enumerate(names):
        a = results[name]['development_calibrated']['classified_primary']
        b = results[name]['fixed']['classified_primary']
        axes[0].barh(i-.18, a['matched_references'], height=.34, color='#187c91', label='Dev threshold' if i == 0 else None)
        axes[0].barh(i+.18, b['matched_references'], height=.34, color='#9bbac0', label='Phone threshold' if i == 0 else None)
        axes[1].barh(i, a['unmatched_per_image'], height=.6, color='#ad723b')
    for ax in axes:
        ax.set_yticks(range(len(names)), names)
        ax.invert_yaxis()
        ax.grid(axis='x', alpha=.2)
        ax.set_axisbelow(True)
    axes[0].set_xlim(0, 23)
    axes[0].set_xlabel('Classified automatic references matched / 23')
    axes[1].set_xlabel('Unmatched predictions / image (not verified FP)')
    fig.legend(*axes[0].get_legend_handles_labels(), loc='outside lower center', ncols=2)
    fig.suptitle('Frozen Mapillary sample · phone two-crop pipeline')
    fig.savefig(out / 'comparison.png', dpi=150)
    plt.close(fig)
    text = '# Fine-tuned Panoramax versus d4\n\n'
    text += 'All 29 frozen Mapillary images were replayed through 58 actual SwiftMac phone crops at 1024 px, FP32 on KI GPU 0, using Ultralytics 8.4.213. This matches the phone crop geometry and proposal logic; it does not measure iPhone CoreML numerical parity or latency. The d4 and original Panoramax metric results exactly reproduce the prior benchmark.\n\n'
    text += '| Model | Dev threshold | Classified matches / 23 | Broad matches / 68 | Unmatched predictions/image | Fixed phone threshold matches / 23 |\n|---|---:|---:|---:|---:|---:|\n'
    for spec in specs:
        score = results[spec['name']]
        a, b = score['development_calibrated']['classified_primary'], score['development_calibrated']['broad_front']
        fixed = score['fixed']['classified_primary']
        text += f"| {spec['name']} | {spec['threshold']:.2f} | {a['matched_references']} | {b['matched_references']} | {a['unmatched_per_image']:.2f} | {fixed['matched_references']} |\n"
    text += '\n**Interpretation:** agreement with incomplete automatic references is not recall over all visible signs. The 23 classified references occur in 10 images; the 68 broader front references occur in 14 images and may include excluded supplementary/direction panels. Images without references are not certified negatives. Unmatched predictions are not verified false positives. The sample spans 29 sequences and 11 location blocks, at least 10,817 m from current fine-tuning/development images; upstream pretraining exposure is unknown.\n\n'
    text += 'The selected Panoramax checkpoint is epoch 10, threshold 0.28, selected exclusively on 17 development images / 33 sign boxes. All 20 training epochs completed. No sample labels or metrics were used to select its checkpoint or threshold. The fixed phone threshold 0.840783 is reported separately. The frozen model selection rule remains unchanged.\n\n'
    text += '![Comparison](comparison.png)\n\n[Numeric comparison](comparison.csv) · [Detailed metrics and size bins](summary.json) · [Frozen settings and hashes](definition.json) · [Training logs and curves](../README.md)\n'
    (out / 'README.md').write_text(text)
    base.write(out / 'complete.json', {'complete': True, 'models': len(specs), 'summary_sha256': base.sha(out / 'summary.json')})


if __name__ == '__main__':
    main()
