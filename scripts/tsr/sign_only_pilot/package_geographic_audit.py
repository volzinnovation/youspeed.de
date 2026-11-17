#!/usr/bin/env python3
"""Package the completed, frozen geographic evaluation and visual error audit."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil


PREFIX = 'reviews/detector-expanded-2026-11-15/geographic-audit-v1/results'
REFERENCE_REV = '70dfe9e66eaa3582ef7e1727a5f2e5a0b85afb7c'
DEFINITION_REV = '49dc93bcca5ae5a73942c55df3ee05c80e5dc7dc'
TRAINING_REV = '8f21612d3c5a2db310896f168bc6f6cedb84d12c'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n')


def main(root):
    evaluation = root / 'evaluation'
    summary = json.loads((evaluation / 'summary.json').read_text())
    complete = json.loads((evaluation / 'complete.json').read_text())
    assert complete['complete'] and complete['summary_sha256'] == sha(evaluation / 'summary.json')
    manifest = json.loads((root / 'references/manifest.json').read_text())
    assert sha(root / 'references/manifest.json') == summary['reference_manifest_sha256']
    assert sha(root / 'evaluation-definition.json') == summary['definition_sha256']
    assert (summary['images'], summary['groups'], summary['reference_boxes']) == (18, 18, 13)
    assessment = json.loads((root / 'error-review/assessment.json').read_text())
    assert assessment['all_cases_inspected'] and assessment['case_count'] == 56
    assert not assessment['reference_labels_changed'] and not assessment['thresholds_changed']
    for name, digest in assessment['reviewed_assets'].items():
        assert sha(root / 'error-review' / name) == digest
    out = root / 'results-publication/dataset' / PREFIX
    out.mkdir(parents=True, exist_ok=False)
    shutil.copytree(evaluation, out / 'evaluation', ignore=shutil.ignore_patterns('*.pt'))
    shutil.copytree(root / 'error-review', out / 'error-review')
    shutil.copy2(root / 'evaluation-definition.json', out / 'definition.json')
    shutil.copy2(root / 'references/manifest.json', out / 'references.json')
    shutil.copy2(root / 'native-inputs/manifest.json', out / 'native-input-manifest.json')
    (out / 'recipe').mkdir()
    for name in ('package_geographic_audit.py', 'evaluate_geographic_audit.py', 'freeze_geographic_evaluation.py',
                 'assemble_blind_references.py', 'test_blind_audit.py', 'train_evaluate.py', 'mobile_replay.py',
                 'NativeDetectorRender.swift'):
        shutil.copy2(Path(__file__).parent / name, out / 'recipe' / name)
    shutil.copy2(Path(__file__).parents[3] / 'iphone/SpeedConsumerApp/TrafficSignDetectorInput.swift',
                 out / 'recipe/TrafficSignDetectorInput.swift')
    native = json.loads((out / 'native-input-manifest.json').read_text())
    assert sha(out / 'recipe/TrafficSignDetectorInput.swift') == native['app_source_sha256']
    assert sha(out / 'recipe/NativeDetectorRender.swift') == native['wrapper_sha256']
    table = '| Model / threshold | TP | FP | FN | Recall | Precision | F2 | Proposals/image |\n|---|---:|---:|---:|---:|---:|---:|---:|\n'
    rows = []
    for name, result in summary['results'].items():
        precision = f"{result['precision']:.1%}" if result['tp'] + result['fp'] else '—'
        table += (f"| {name} ({result['threshold']}) | {result['tp']} | {result['fp']} | {result['fn']} | "
                  f"{result['recall']:.1%} | {precision} | {result['f2']:.3f} | {result['proposals_per_image']:.3f} |\n")
        rows.append({'configuration': name, **{k: result[k] for k in
            ('threshold', 'tp', 'fp', 'fn', 'precision', 'recall', 'f2', 'proposals_per_image', 'fp_on_reviewed_traffic_lights')}})
    with (out / 'metrics.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    gallery = ['# Geographic comparison: all admitted images',
        'Green: matched reference; yellow: missed reference; red: unmatched proposal. Labels and thresholds were frozen before student inference. Mac Core Image plus KI FP32 does not certify iOS Core ML equivalence.']
    for frame in manifest['frames']:
        uid = frame['image_id']
        gallery.append('## ' + uid)
        for setting in ('fixed_phone', 'development_selected'):
            gallery.append('### ' + setting)
            gallery.append('| d4 | d8 |\n|---|---|\n' +
                f'| ![d4](evaluation/images/d4-{setting}-{uid}.jpg) | ![d8](evaluation/images/d8-{setting}-{uid}.jpg) |')
    (out / 'gallery.md').write_text('\n\n'.join(gallery) + '\n')
    errors = ['# Inspected reference and error crops',
        'All 13 reference faces and all 43 unique unmatched d4 proposals were inspected. The fixed-threshold false positives are a subset of these. d8 has no unmatched proposals on this small sample at either frozen threshold. One d4 roadside panel remains taxonomically unresolved; the pre-inference reference labels and official scores are unchanged.',
        '[Per-case assessments and exact crop hashes](error-review/assessment.json)']
    for path in sorted((out / 'error-review').glob('sheet-*.jpg')):
        errors.append(f'![Inspected cases {path.stem}](error-review/{path.name})')
    (out / 'errors.md').write_text('\n\n'.join(errors) + '\n')
    reference_url = f'https://huggingface.co/datasets/loffenauer/streetshots/blob/{REFERENCE_REV}/reviews/detector-expanded-2026-11-15/geographic-audit-v1/references/README.md'
    definition_url = f'https://huggingface.co/datasets/loffenauer/streetshots/blob/{DEFINITION_REV}/reviews/detector-expanded-2026-11-15/geographic-audit-v1/evaluation-definition/definition.json'
    narrative = f'''# d8 geographic audit: fewer extra candidates, threshold change required

The selected d8 model finds eight of thirteen frozen reference signs with zero unmatched proposals at its development-selected threshold 0.43. d4 finds eight with 43 unmatched proposals at its separately development-selected threshold 0.51. Seven found signs are shared: d8 gains a small speed-30 face and loses an oblique red-border face. Equal counts do not mean identical detections.

At the unchanged phone threshold 0.840783, d8 finds no signs; d4 finds four with six unmatched proposals. **d8 is not a drop-in replacement.** It is a promising candidate for reducing downstream classification workload after recalibration, but this small audit does not establish a production recall improvement.

{table}

Precision is shown as a dash when there are no proposals. Raw JSON uses zero by convention in this case. Traffic lights are not positives; reviewed-light overlaps remain included in raw FP. None of this audit's unmatched proposals overlaps the explicitly reviewed traffic-light regions. Vehicle lamps and warning beacons are separate qualitative categories.

[All-image comparison](gallery.md) · [Inspected error crops](errors.md) · [Counts and metrics](metrics.csv) · [Raw results and bootstrap intervals](evaluation/summary.json)

## Frozen evaluation

[The references]({reference_url}) and [evaluation definition]({definition_url}) were published before student inference. Candidate epoch 54 was selected by maximum whole-frame development AP50–95, with earliest-epoch tie break and epoch zero eligible. Each model's phone threshold was selected solely on the original 17 development images, maximizing F2 on the fixed 0.25–0.99 grid. There was no geographic threshold search, model reselection or label revision.

All inference used Ultralytics 8.4.213, KI GPU0, FP32 and the unchanged iPhone Swift/Core Image input code compiled on macOS. The pipeline uses 1024 input, the app's two full-height edge crops for landscape images, portrait whole-frame fallback, per-pass cap 12 and source NMS 0.45. This does not measure iOS Core ML numerical parity, downstream classification, temporal behavior or phone latency.

## Error audit and uncertainty

The assistant inspected all 56 unique reference/error cases. d4's 43 unmatched proposals comprise 10 direction-board detections/fragments, six building windows, six vehicle-lamp detections, four vegetation regions, four road markers, three truck conspicuity markings, three vehicle-body regions, and one each of vehicle window, vehicle wheel, roof/sky, small information plate, equipment reverse, warning beacon and unresolved roadside panel. These are assistant visual assessments, not human certification.

d8's five missed references are the narrowing warning, bus-stop H, parking P, opposite-side red-border face and motorway-gore hazard face. Their nominal input sizes range from about 5 to 22 pixels per side. The teacher also missed the bus stop, parking and gore hazard during blinded reference preparation. This is evidence that teacher-negative frames can still contain signs, not proof of the cause of d8's misses.

One unmatched d4 white/blue roadside panel remains taxonomically unresolved after wider-context inspection. The official frozen score is retained. As a transparent hypothetical sensitivity bound, if that exact d4 proposal were one additional valid reference, d4 at 0.51 would have 9 TP / 42 FP / 5 FN and d8 at 0.43 would have 8 TP / 0 FP / 6 FN. This is not a relabeled evaluation or a new threshold choice.

The 24 preselected geographic groups yielded 18 admitted images: eight positive and ten without identified in-scope signs. One indoor/nonroad frame and five unresolved road frames were excluded before predictions. These exclusions bias the audit toward interpretable scenes. The source is a detector export, not a random road sample. Upstream pretraining/classifier exposure is unknown despite the known sequence and 500 m training separation.

The paired geographic bootstrap gives d8-minus-d4 recall difference from −28.6 to +16.7 percentage points at the development-selected settings (95% percentile interval, 2,000 resamples). The corresponding F2 difference interval is +4.5 to +42.6 points. These conditional intervals describe a tiny assistant-reviewed sample; zero observed d8 FP and the bootstrap precision interval must not be interpreted as guaranteed perfect precision.

## Training and next experiment

[The completed training report](https://huggingface.co/loffenauer/streetshots/blob/{TRAINING_REV}/detector/d8/results/README.md) contains all 150 epochs, losses, improvement deltas and weights. The expanded set has 5,288 images and 4,410 boxes, predominantly teacher pseudo-labels. Whole-frame development AP50–95 increased from 20.827% to 23.675% at epoch 54, then fell to 18.326% by epoch 150. More epochs alone did not provide a better final model.

Keep d4 initialization rather than starting from scratch. The next training experiment should review missed-sign and pseudo-negative training scenes, strengthen small/blurred sign coverage, and mix exact phone crops or whole images with positive-balanced tiles. The completed native-tile pilot had only 97 positive tiles among 830, so compare matched optimizer steps and explicitly control sample balance. Candidate selection should prioritize phone-pipeline recall subject to a downstream workload budget, rather than whole-frame AP alone. Retain separate fresh geography for any new model or threshold choices; this audit is now consumed.

Before deployment, validate d8 with its proposed calibration on a larger independently human-reviewed geographic set and measure exported Core ML behavior and latency on the device. No model, threshold or app policy has been deployed or changed by this work.
'''
    (out / 'README.md').write_text(narrative)
    write(out / 'release.json', {'schema': 'streetshots-geographic-audit-release-v1',
        'reference_revision': REFERENCE_REV, 'definition_revision': DEFINITION_REV,
        'training_results_revision': TRAINING_REV, 'packager_sha256': sha(Path(__file__)),
        'files': {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    print(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    main(parser.parse_args().root)
