#!/usr/bin/env python3
"""Package completed d10 metrics, all epoch evidence and Mapillary comparison."""
import csv
import json
import shutil
import sys
from pathlib import Path

JOB = Path('/home/raphael/streetshots-d5-20261114')
ROOT = JOB / 'balanced-v1'
sys.path.insert(0, str(JOB / 'expanded-v1/recipe'))
from prepare_expanded_publication import sha, write, inventory


def main():
    run = ROOT / 'runs/panoramax'
    seal = json.loads((run / 'seal.json').read_text())
    history = json.loads((run / 'history.json').read_text())
    assert seal['complete'] and seal['completed_epochs'] == 20
    assert [r['epoch'] for r in history] == list(range(21))
    assert sha(run / 'history.json') == seal['history_sha256']
    assert sha(run / 'selected.pt') == seal['checkpoint_sha256']
    source = ROOT / 'panoramax-final-benchmark'
    complete = json.loads((source / 'complete.json').read_text())
    assert complete['complete'] and complete['summary_sha256'] == sha(source / 'summary.json')
    comparison = json.loads((source / 'summary.json').read_text())
    publication = ROOT / 'publication'
    target = publication / 'detector/d10/results'
    target.mkdir(parents=True, exist_ok=False)
    benchmark = target / 'mapillary'
    shutil.copytree(source, benchmark)
    # Original image links and hashes only: no media, signed URLs or raw reference payloads.
    provenance = ROOT / 'publication/detector/d9/mapillary-automatic-benchmark/sample-provenance.json'
    shutil.copy2(provenance, benchmark / 'sample-provenance.json')
    shutil.copy2(ROOT / 'panoramax-final-benchmark-launch.json', benchmark / 'launch.json')
    epochs = target / 'epochs'
    epochs.mkdir()
    for name in ['configuration.json', 'history.json', 'epochs.jsonl', 'selection.json', 'seal.json']:
        shutil.copy2(run / name, epochs / name)
    for path in run.glob('epoch-*-phone.json'):
        shutil.copy2(path, epochs / path.name)
    for name in ['results.csv', 'args.yaml']:
        shutil.copy2(run / 'fit' / name, epochs / ('ultralytics-' + name))
    shutil.copy2(ROOT / 'panoramax.log', epochs / 'training.log')
    for name in ['panoramax-definition.json', 'panoramax-launch.json', 'panoramax-head-check.json']:
        shutil.copy2(ROOT / name, target / name)
    recipes = target / 'recipe'
    recipes.mkdir()
    for name in ['benchmark_panoramax_final.py', 'package_panoramax_final.py',
                 'benchmark_mapillary_auto.py', 'train_balanced.py', 'train_latest.py',
                 'train_evaluate.py', 'mobile_replay.py', 'balanced_views.py']:
        shutil.copy2(ROOT / 'recipe' / name, recipes / name)
    rows = []
    baseline = history[0]['phone']['recall']
    previous = baseline
    for row in history:
        score = row['phone']
        rows.append({'epoch': row['epoch'], 'selected_checkpoint': row['epoch'] == seal['selected_epoch'],
            'development_threshold': score['threshold'], 'tp': score['tp'], 'unmatched': score['fp'],
            'fn': score['fn'], 'reference_recall': score['recall'],
            'recall_delta_from_baseline': score['recall'] - baseline,
            'recall_delta_from_previous_epoch': score['recall'] - previous,
            'fixed_phone_tp': row['phone_fixed']['tp'], 'fixed_phone_unmatched': row['phone_fixed']['fp'],
            'fixed_phone_fn': row['phone_fixed']['fn'], 'ap50_whole_image': row.get('ap50'),
            'ap50_95_whole_image': row.get('ap50_95'),
            'optimizer_calls_total': row['optimizer_step_calls_total'],
            'optimizer_updates_total': row['optimizer_actual_updates_total'],
            'draws': row.get('draws', 0), 'duration_seconds': row['duration_seconds']})
        previous = score['recall']
    with (target / 'epoch-improvements.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), layout='constrained')
    xs = [r['epoch'] for r in history]
    axes[0, 0].plot(xs, [r['phone']['tp'] for r in history], label='Dev-calibrated')
    axes[0, 0].plot(xs, [r['phone_fixed']['tp'] for r in history], label='Fixed phone threshold')
    axes[0, 0].set_ylabel('Matched development signs / 33')
    axes[0, 0].set_ylim(0, 33)
    axes[0, 0].legend()
    axes[0, 1].plot(xs, [r['phone']['fp'] for r in history], color='#ad723b')
    axes[0, 1].set_ylabel('Unmatched development predictions')
    for key in ['box_loss', 'cls_loss', 'dfl_loss']:
        axes[1, 0].plot(xs[1:], [r['train_loss'][key] for r in history[1:]], label=key)
        axes[1, 1].plot(xs[1:], [r['validation_loss']['val/' + key] for r in history[1:]], label=key)
    axes[1, 0].set_ylabel('Training loss')
    axes[1, 1].set_ylabel('Whole-image validation loss')
    axes[1, 0].legend()
    axes[1, 1].legend()
    for ax in axes.flat:
        ax.axvline(seal['selected_epoch'], color='#777777', linestyle='--', alpha=.7)
        ax.set_xlabel('Sampling epoch (1,024 draws; epoch 0 = initialization)')
        ax.grid(alpha=.2)
    fig.suptitle('Panoramax sign-only fine-tuning · selected epoch 10 (dashed line)')
    fig.savefig(target / 'learning-curves.png', dpi=150)
    plt.close(fig)
    selected = history[seal['selected_epoch']]
    summary = {'complete': True, 'completed_epochs': 20, 'selected_epoch': seal['selected_epoch'],
        'selected_threshold': seal['threshold'], 'selected_checkpoint_sha256': seal['checkpoint_sha256'],
        'checkpoint_location_ki': str(run / 'selected.pt'), 'checkpoint_uploaded': False,
        'total_training_draws': sum(r.get('draws', 0) for r in history),
        'optimizer_calls': history[-1]['optimizer_step_calls_total'],
        'optimizer_actual_updates': history[-1]['optimizer_actual_updates_total'],
        'development_baseline': history[0]['phone'], 'development_selected': selected['phone'],
        'development_final_epoch': history[-1]['phone'],
        'mapillary_summary_sha256': sha(benchmark / 'summary.json'),
        'baseline_reproduction_verified': comparison['baseline_replay_matches_previous'],
        'deployment_performed': False, 'training_seal_sha256': sha(run / 'seal.json')}
    write(target / 'summary.json', summary)
    text = '# Panoramax sign-only fine-tuning: final results\n\n'
    text += '**Completed:** all 20 sampling epochs on KI GPU 0, using Ultralytics 8.4.213. The pretrained YOLO11l sign/regression weights were retained; face and plate output channels were removed. The frozen development rule selected epoch 10 at threshold 0.28. This is an offline candidate; no app model was deployed.\n\n'
    text += '## Mapillary comparison\n\n'
    text += '| Model | Development threshold | Classified automatic references matched | Unmatched predictions over 29 images | Fixed phone threshold matches |\n|---|---:|---:|---:|---:|\n'
    for name, modes in comparison['results'].items():
        a = modes['development_calibrated']['classified_primary']
        fixed = modes['fixed']['classified_primary']
        text += f"| {name} | {a['threshold']:.2f} | {a['matched_references']}/23 | {a['unmatched_predictions']} | {fixed['matched_references']}/23 |\n"
    text += '\nFine-tuning improved agreement over original Panoramax, but d4 still matches more classified references. The fine-tuned model emits substantially fewer unmatched predictions than d4 at these operating points. This is a candidate-volume tradeoff, **not verified precision improvement**: automatic annotations are incomplete, and unmatched predictions may be real signs. No replacement is promoted on these results.\n\n'
    text += 'All models use the same 29 images, 58 actual SwiftMac crops and phone proposal logic, at 1024 px with FP32 inference on KI. The d4 and original Panoramax results exactly reproduce the earlier benchmark. No Mapillary threshold or checkpoint tuning was performed. CoreML numerical parity and iPhone latency were not measured.\n\n'
    text += '![Mapillary comparison](mapillary/comparison.png)\n\n[Full benchmark, caveats and broader-reference tier](mapillary/README.md) · [CSV comparison](mapillary/comparison.csv) · [Source image links and hashes](mapillary/sample-provenance.json)\n\n'
    text += '## Development and training\n\n| Checkpoint | Threshold | Matched / 33 | Unmatched | Missed |\n|---|---:|---:|---:|---:|\n'
    for label, row in [('Initialization', history[0]), ('Selected epoch 10', selected), ('Final epoch 20', history[-1])]:
        a = row['phone']
        text += f"| {label} | {a['threshold']:.2f} | {a['tp']} | {a['fp']} | {a['fn']} |\n"
    text += '\nDevelopment contains 17 images / 33 references. It is used for selection, so the improvement is not an independent test result. Thresholds maximize development recall under at most four proposals/image, then precision, higher threshold and earlier epoch; epoch 0 is eligible. The final epoch is reported separately from the selected checkpoint.\n\n'
    text += f"Training used {summary['total_training_draws']:,} balanced draws (1,024 per sampling epoch), not 20 complete passes through the source pool. There were {summary['optimizer_calls']:,} optimizer calls and {summary['optimizer_actual_updates']:,} actual AMP updates; overflow skips explain the difference. The corrected source pool has 5,264 images and 4,423 boxes, with 5,263 usable parents in the frozen schedules. Labels remain predominantly weak and incomplete. The first 20 frozen mixed-crop schedules were used, at 75% positive / 25% pseudo-negative draws, batch 4, nominal batch 16, 1024 px, AdamW 1e-4. Native `tile=True` is off: precomputed balanced small-sign views are mixed with phone crops.\n\n"
    text += '![All epoch learning curves](learning-curves.png)\n\n[Per-epoch improvement CSV](epoch-improvements.csv) · [Complete history](epochs/history.json) · [Raw training log](epochs/training.log) · [Ultralytics metrics CSV](epochs/ultralytics-results.csv) · [Configuration](epochs/configuration.json) · [Selection](epochs/selection.json) · [Completion seal](epochs/seal.json)\n\n'
    text += 'The epochs folder includes baseline and all 20 development prediction/sweep files, losses, learning rates, update counts and timings. The recipe folder contains the benchmark and training code. The completion seal predates this Mapillary replay; its `holdout_evaluated: false` records training-time status, while the separate benchmark completion record records this subsequent evaluation.\n\n'
    text += f"Selected checkpoint SHA-256: `{seal['checkpoint_sha256']}`. Checkpoint weights remain on KI at `{run / 'selected.pt'}`; this publication contains final results, provenance and epoch logs. Raw Mapillary media and annotation payloads are not republished.\n\n"
    text += 'Recommended next step: manually complete the independent sample annotations, including unmatched model predictions, before making a detector replacement decision. Any future tuning using this sample requires a new untouched test sample.\n'
    (target / 'README.md').write_text(text)
    inventory(publication, target, 'model', 'detector/d10/results/summary.json', ROOT / 'panoramax-final-results-inventory.json')


if __name__ == '__main__':
    main()
