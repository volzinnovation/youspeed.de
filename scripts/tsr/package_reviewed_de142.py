#!/usr/bin/env python3
"""Promote the reviewed DE142 checkpoint after measured native device parity."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = 'e10f4a7f8a2d2c3554dc0ef2d0e1f96e98948c7648432ed13098ef05ff6c3299'
PACK_ID = 'de-youspeed-reviewed142-v1'
COMPONENT_ID = 'youspeed-de-reviewed142-v1'


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_sha(path):
    path = Path(path)
    digest = hashlib.sha256()
    for child in sorted(p for p in path.rglob('*') if p.is_file()):
        if child.is_symlink():
            raise ValueError('Model tree contains a symbolic link')
        digest.update(child.relative_to(path).as_posix().encode() + b'\0' + child.read_bytes() + b'\0')
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--android-model', type=Path, required=True)
    parser.add_argument('--android-precision', choices=('float16', 'float32'), required=True)
    parser.add_argument('--coreml-compiled', type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence
    configuration = read(evidence / 'results/configuration.json')
    comparison = read(evidence / 'results/comparison.json')
    selection = read(evidence / 'results/selection-frozen.json')
    catalogue_path = ROOT / 'shared/tsr/prolix-de-class-catalog-v1.json'
    catalogue = read(catalogue_path)
    classes = catalogue['class_labels']
    if len(classes) != 142 or configuration['classes'] != classes:
        raise ValueError('The frozen 142-class order is required')
    if comparison['candidate_checkpoint_sha256'] != CHECKPOINT or selection['checkpoint_sha256'] != CHECKPOINT:
        raise ValueError('Training and selected checkpoint differ')
    compiled_metadata = read(args.coreml_compiled / 'metadata.json')[0]
    if compiled_metadata['classLabels'] != classes:
        raise ValueError('Core ML labels differ from the frozen class order')
    hashes = {'android': sha(args.android_model), 'ios': tree_sha(args.coreml_compiled)}
    parity = {}
    for platform, name in (('android', 'android-native-parity.json'), ('ios', 'iphone-native-parity.json')):
        measured = read(evidence / name)
        if (measured['checkpoint_sha256'] != CHECKPOINT or measured['passed'] is not True
                or measured['images'] != 96 or measured['top1_agree_count'] != 96
                or measured['tolerance'] != .02 or measured['measured_max_abs_difference'] > .02
                or measured['artifact_sha256'] != hashes[platform]):
            raise ValueError(f'{platform} device parity does not cover the promoted artifact')
        parity[platform] = measured
    dataset_sha = configuration['dataset_sha256']
    training = {key: configuration[key] for key in (
        'seed', 'baseline_sha256', 'dataset_sha256', 'script_sha256', 'gpu', 'torch',
        'ultralytics', 'unique_train', 'exposures_per_epoch', 'source_train_counts',
        'training_class_counts', 'selection', 'augmentation', 'schedule')}
    training.update(checkpoint_sha256=CHECKPOINT, class_count=142,
                    epochs_completed=comparison['epochs_completed'], selected_epoch=comparison['selected_epoch'])
    evaluation = {key: comparison[key] for key in (
        'baseline_checkpoint_sha256', 'candidate_checkpoint_sha256', 'test_crop_count',
        'test_class_counts', 'complete_scene_count', 'crop_city_metrics',
        'same_new_detector_pipeline', 'new_detector_general_sign',
        'legacy_report_diagnostic_macro_f1', 'classifier_thresholds', 'scope', 'source_limit')}
    evaluation['limitations'] = [
        'Fresh exact class references cover DE:310/DE:311 and reviewed negatives, not all 142 classes.',
        'Some historical HF crops lack recoverable route metadata.',
        'The six emphasized exits are training examples, excluded from fresh test metrics.',
        'One manual code DE:282-50 needs a class mapping.',
        'Raw model scores remain uncalibrated.'
    ]
    catalogue['classifier_checkpoint_sha256'] = CHECKPOINT
    catalogue['provenance']['class_labels_source_sha256'] = sha(args.coreml_compiled / 'metadata.json')
    catalogue['provenance']['classifier_revision'] = 'de-reviewed-2026-11-10-epoch6'
    catalogue['provenance']['reviewed_training'] = {
        'checkpoint_sha256': CHECKPOINT, 'dataset_sha256': dataset_sha,
        'evaluation': 'provenance/reviewed142-evaluation.json'}
    for sign in catalogue['signs']:
        note = sign.get('notes', '')
        if 'fresh field F1 awaits review' in note:
            sign['notes'] = note.replace('fresh field F1 awaits review',
                'town-entry and town-exit metrics are recorded in reviewed142-evaluation.json')

    for platform, relative in (
        ('android', 'android/app/src/main/assets/tsr'),
        ('ios', 'iphone/SpeedConsumerApp/TSRModelPacks'),
    ):
        pack = ROOT / relative / 'DE.panoramax-bootstrap.tsrmodelpack'
        manifest = read(pack / 'manifest.json')
        if [row['class_id'] for row in manifest['class_mapping']] != classes:
            raise ValueError('Existing pack has another class order')
        detector = deepcopy(manifest['detector'])
        thresholds = deepcopy(manifest['thresholds'])
        provenance = pack / 'provenance'
        write(provenance / 'reviewed142-training.json', training)
        write(provenance / 'reviewed142-evaluation.json', evaluation)
        write(provenance / 'reviewed142-device-parity.json', parity)
        export = read(evidence / 'exports' / ('tflite' if platform == 'android' else 'coreml') / 'export-report.json')
        export.update(promoted_artifact_sha256=hashes[platform], native_parity_pending=False,
                      device_measurement_pending=False, device_parity=parity[platform])
        export['selected_artifact'] = {
            'file_name': args.android_model.name if platform == 'android' else args.coreml_compiled.name,
            'precision': args.android_precision if platform == 'android' else 'float16',
            'sha256': hashes[platform],
            'execution': parity[platform]['execution'],
        }
        artifact = manifest['classifier']['artifacts'][0]
        target = pack / artifact['path']
        if platform == 'android':
            new_name = 'classify_de_road_signs_' + args.android_precision + '.tflite'
            new_target = pack / new_name
            shutil.copyfile(args.android_model, new_target)
            if target != new_target and target.exists():
                target.unlink()
            artifact.update(path=new_name, precision=args.android_precision)
        else:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(args.coreml_compiled, target)
        artifact.update(sha256=hashes[platform], source_checkpoint_sha256=CHECKPOINT,
                        calibration_dataset_sha256=dataset_sha,
                        parity={key: parity[platform][key] for key in ('passed', 'tolerance', 'measured_max_abs_difference')})
        artifact['exporter']['configuration'] = (
            'imgsz=224,batch=1,dynamic=false,nms=false; RGB/255; frozen142; '
            + ('weights=' + args.android_precision if platform == 'android' else 'Core ML Float16, computeUnits=all'))
        write(provenance / 'reviewed142-export.json', export)
        manifest['classifier'].update(component_id=COMPONENT_ID, source_checkpoint={
            'uri': 'urn:sha256:' + CHECKPOINT, 'revision': 'de-reviewed-2026-11-10-epoch6', 'sha256': CHECKPOINT})
        manifest['pack_id'] = PACK_ID
        manifest['calibration'].update(revision='uncalibrated-de-reviewed142-v1', dataset_sha256=dataset_sha)
        lineage = manifest['lineage']
        lineage['dataset_inventory_sha256s'] = list(dict.fromkeys(lineage['dataset_inventory_sha256s'] + [dataset_sha]))
        lineage.update(training_run_id='de-reviewed-2026-11-10-epoch6',
                       training_run_sha256=sha(provenance / 'reviewed142-training.json'),
                       evaluation_report_sha256=sha(provenance / 'reviewed142-evaluation.json'),
                       parity_report_sha256=sha(provenance / 'reviewed142-device-parity.json'))
        assert manifest['detector'] == detector and manifest['thresholds'] == thresholds
        write(pack / 'manifest.json', manifest)
        shadow = pack / 'shadow-runtime-v2.json'
        if shadow.exists():
            value = read(shadow)
            value.update(source_pack_id=PACK_ID, pack_id='de-youspeed-reviewed142-shadow-v2')
            value['classifier'].update(component_id=COMPONENT_ID, artifact_sha256=hashes[platform],
                                       artifact_id='youspeed-de142-reviewed-coreml-' + hashes[platform][:8])
            value['classifier']['calibration'].update(id='youspeed-de142-reviewed-uncalibrated-v1', dataset_sha256=dataset_sha)
            write(shadow, value)
        notice = pack / 'THIRD_PARTY_NOTICES.txt'
        marker = '\nReviewed DE142 classifier, 2026-11-10\n'
        text = notice.read_text()
        if marker not in text:
            notice.write_text(text + marker +
                'Fine-tuned from the preserved DE142 v3 model with reviewed Panoramax crops,\n'
                'manual annotations and historical replay. Public source attribution is\n'
                'retained with the predecessor notices and reviewed142 attribution record.\n'
                'Aggregate training, evaluation and native device parity are recorded in\n'
                'provenance/reviewed142-*.json. Raw scores remain uncalibrated.\n')
    write(catalogue_path, catalogue)
    print(json.dumps({'pack_id': PACK_ID, 'checkpoint_sha256': CHECKPOINT, 'artifacts': hashes}))


if __name__ == '__main__':
    main()
