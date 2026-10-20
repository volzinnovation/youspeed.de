#!/usr/bin/env python3
"""One fixed two-arm SGBlur -> TSR scoring pass on 15 known city targets.

No optimization or checkpoint selection. Classify every post-NMS sign crop
before consulting GT boxes for matching. Never read a GT-crop path or file.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from collections import defaultdict
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def summarize(rows):
    result = {'known_targets': len(rows),
              'detector_misses': sum(r['result'] == 'detector_miss' for r in rows),
              'detected_but_wrong_tsr_class': sum(r['result'] == 'detected_but_wrong_tsr_class' for r in rows),
              'correct_city_known_targets': sum(r['result'] == 'correct_city_known_target' for r in rows)}
    detected = len(rows)-result['detector_misses']
    result['detected_known_targets'] = detected
    result['known_target_pipeline_recall'] = result['correct_city_known_targets']/len(rows) if rows else None
    result['conditional_tsr_accuracy_on_matched_detections'] = result['correct_city_known_targets']/detected if detected else None
    return result


def balanced(rows, field):
    groups = defaultdict(list)
    for r in rows:
        groups[r[field]].append(r)
    detail = {key: summarize(values) for key, values in sorted(groups.items())}
    return {'units': len(groups), 'unit_field': field,
            'definition': 'Mean of within-unit known-target pipeline recall; equal weight per conservative candidate unit, not proof of independence.',
            'macro_known_target_pipeline_recall': sum(v['known_target_pipeline_recall'] for v in detail.values())/len(detail) if detail else None,
            'per_unit': detail}


def run_arm(name, sg_model, tsr_model, sg, mu, classes, images, output, device):
    torch, np, Image = sg.torch, sg.np, sg.Image
    tsr_model.eval()
    frame_outputs = []
    with torch.inference_mode():
        for frame_index, frame in enumerate(images):
            # This phase receives only the full-image path and checksum. The GT
            # box/crop is deliberately absent from the function's image records.
            source_path = Path(frame['input_image_absolute_path'])
            assert sha(source_path) == frame['input_sha256']
            tensor, _, transform = sg.read_image(frame, 1280, verify=True)
            with Image.open(source_path) as source:
                # Fresh RGB raster removes inherited EXIF from all native crops.
                rgb = Image.fromarray(np.asarray(source.convert('RGB')).copy())
            decoded, _ = sg.raw_forward(sg_model, tensor.unsqueeze(0).to(device))
            nms = sg.non_max_suppression(decoded, conf_thres=.25, iou_thres=.7,
                                         nc=3, max_det=300)[0].cpu().tolist()
            ratio, left, top, width, height = transform
            detections = []
            for index, det in enumerate(nms):
                native = [max(0., min(width, (det[0]-left)/ratio)),
                          max(0., min(height, (det[1]-top)/ratio)),
                          max(0., min(width, (det[2]-left)/ratio)),
                          max(0., min(height, (det[3]-top)/ratio))]
                class_id = int(det[5])
                record = {'detection_id': f'{name}-f{frame_index:02d}-d{index:03d}',
                          'post_nms_index': index, 'detector_class_id': class_id,
                          'detector_class': {0: 'sign', 1: 'plate', 2: 'face'}[class_id],
                          'detector_score': det[4], 'bbox_xyxy_letterbox': det[:4],
                          'bbox_xyxy_native_float': native, 'crop_path': None,
                          'crop_sha256': None, 'crop_pixel_sha256': None,
                          'tsr_predicted_label': None, 'matched_gt_sample_ids': []}
                if class_id == 0:
                    box = [max(0, min(width, math.floor(native[0]))),
                           max(0, min(height, math.floor(native[1]))),
                           max(0, min(width, math.ceil(native[2]))),
                           max(0, min(height, math.ceil(native[3])))]
                    record['crop_box_xyxy_native_integer'] = box
                    if box[2] > box[0] and box[3] > box[1]:
                        crop = rgb.crop(tuple(box))
                        crop_path = output/'predicted-crops'/name/(record['detection_id']+'.png')
                        crop_path.parent.mkdir(parents=True, exist_ok=True)
                        crop.save(crop_path)
                        pixels = np.asarray(crop.resize((224, 224), Image.Resampling.BILINEAR), dtype=np.float32).copy()/255.
                        input_tensor = torch.from_numpy(pixels).permute(2, 0, 1).unsqueeze(0).to(device)
                        logits = mu.logits_from_output(tsr_model(input_tensor))[0]
                        probabilities = logits.softmax(0)
                        predicted = int(logits.argmax())
                        record.update(crop_path=crop_path.relative_to(output).as_posix(),
                                      crop_sha256=sha(crop_path),
                                      crop_dimensions=list(crop.size),
                                      crop_pixel_sha256=hashlib.sha256(f'RGB:{crop.width}x{crop.height}:'.encode()+crop.tobytes()).hexdigest(),
                                      classifier_input_float32_hwc_sha256=hashlib.sha256(pixels.astype('<f4').tobytes()).hexdigest(),
                                      tsr_predicted_index=predicted, tsr_predicted_label=classes[predicted],
                                      tsr_max_softmax_score=float(probabilities[predicted]),
                                      tsr_logits=logits.cpu().tolist(), tsr_probabilities=probabilities.cpu().tolist())
                    else:
                        record['classification_not_run_reason'] = 'Empty clamped predicted crop'
                detections.append(record)
            frame_outputs.append({**frame, 'width': width, 'height': height,
                                  'native_coordinate_system': 'original registered RGB raster; pixel-edge xyxy',
                                  'detections': detections})
            print(json.dumps({'arm': name, 'completed_full_frames': frame_index+1,
                              'post_nms_signs_classified': sum(d['tsr_predicted_label'] is not None for d in detections)}), flush=True)
    return frame_outputs


def match_targets(frames, targets, sg):
    by_image = defaultdict(list)
    for row in targets:
        by_image[(row['input_image_absolute_path'], row['input_sha256'])].append(row)
    results = []
    for frame in frames:
        gt = by_image[(frame['input_image_absolute_path'], frame['input_sha256'])]
        signs = [d for d in frame['detections'] if d['detector_class_id'] == 0]
        pairs = sorted([(sg.box_iou(t['bbox_xyxy'], d['bbox_xyxy_native_float']), i, j)
                        for i, t in enumerate(gt) for j, d in enumerate(signs)], reverse=True)
        assigned, used = {}, set()
        for overlap, i, j in pairs:
            if overlap >= .5 and i not in assigned and j not in used:
                assigned[i] = (j, overlap)
                used.add(j)
        for i, target in enumerate(gt):
            match = assigned.get(i)
            detection = signs[match[0]] if match else None
            if detection is not None:
                detection['matched_gt_sample_ids'].append(target['sample_id'])
            predicted = detection['tsr_predicted_label'] if detection else None
            status = 'detector_miss' if detection is None else 'correct_city_known_target' if predicted == target['label'] else 'detected_but_wrong_tsr_class'
            results.append({'sample_id': target['sample_id'], 'picture_id': target['picture_id'],
                            'sequence_id': target['sequence_id'], 'label': target['label'],
                            'site_id': target['site_id'], 'group_id': target['group_id'], 'subset': target['subset'],
                            'gt_bbox_xyxy': target['bbox_xyxy'], 'matched_detection_id': detection['detection_id'] if detection else None,
                            'matched_iou': match[1] if match else None,
                            'predicted_label_from_detected_crop': predicted,
                            'detected_crop_sha256': detection['crop_sha256'] if detection else None,
                            'result': status, 'gt_crop_used_for_classification': False})
    assert len(results) == 15
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--sg-root', type=Path, required=True)
    parser.add_argument('--tsr-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--device', default='cuda:0')
    args = parser.parse_args()
    assert sha(args.plan) == args.plan_sha256
    plan = json.loads(args.plan.read_text())
    assert plan['script_sha256'] == sha(__file__)
    assert plan['no_tuning_or_selection'] is True
    assert not args.output.exists(), 'New output required; one scoring event only'
    sg_script = args.sg_root/'frozen_sign_adapt.py'
    assert sha(sg_script) == plan['sg_helper_sha256']
    assert sha(args.tsr_root/'code/model_utils.py') == plan['tsr_helper_sha256']
    assert sha(args.sg_root/'reviewed-test.json') == plan['frozen_target_manifest_sha256']
    assert sha(args.tsr_root/'final-label-qa.json') == plan['blind_peer_label_manifest_sha256']
    document = json.loads((args.sg_root/'reviewed-test.json').read_text())
    peer = json.loads((args.tsr_root/'final-label-qa.json').read_text())
    targets = [r for r in document['rows'] if r['label'] in ['city:start', 'city:end']]
    assert {r['sample_id']: r['label'] for r in targets} == plan['city_target_labels']
    assert all(peer['primary_label_by_id'].get(r['sample_id']) == r['label'] for r in targets)
    assert len(targets) == 15 and sum(r['label'] == 'city:start' for r in targets) == 3
    sg = load_module('fixed_pipeline_sg', sg_script)
    mu = load_module('fixed_pipeline_tsr', args.tsr_root/'code/model_utils.py')
    sg.dependencies()
    torch, ultralytics = sg.torch, __import__('ultralytics')
    torch.set_num_threads(2)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    classes = mu.load_classes(args.tsr_root/'code/class-index.json')
    manifest, manifest_sha = mu.load_manifest(args.tsr_root/'data/dataset-v1', classes)
    assert manifest_sha == plan['tsr_training_manifest_sha256']
    paths = {'sg_baseline': args.sg_root/'source/yolo11n_panoramax.pt',
             'sg_candidate': args.sg_root/'run-01/best.pt',
             'tsr_baseline': args.tsr_root/'models/baseline.pt',
             'tsr_candidate': args.tsr_root/'runs/versuch-01/weights/best.pt'}
    assert {key: sha(path) for key, path in paths.items()} == plan['model_sha256']
    baseline_sg = sg.load_model(paths['sg_baseline'], args.device)
    candidate_sg = sg.load_model(paths['sg_baseline'], args.device, paths['sg_candidate'])
    baseline_tsr = mu.load_baseline(torch, ultralytics, paths['tsr_baseline'], classes).to(args.device).eval()
    candidate_tsr, metadata = mu.load_candidate(torch, copy.deepcopy(baseline_tsr), paths['tsr_candidate'], classes, manifest_sha)
    candidate_tsr.to(args.device).eval()
    assert metadata['epoch'] == 4
    assert torch.load(paths['sg_candidate'], map_location='cpu', weights_only=True)['epoch'] == 9
    images = []
    seen = set()
    for row in targets:
        key = (row['input_image_absolute_path'], row['input_sha256'])
        if key not in seen:
            # Deliberately drop all GT-crop paths, GT boxes and target labels
            # before the detector/classifier prediction phase.
            images.append({k: row[k] for k in ['picture_id', 'source_url', 'input_image_absolute_path', 'input_sha256']})
            seen.add(key)
    args.output.mkdir(parents=True)
    arms = {}
    for name, detector, classifier in [('baseline_pair', baseline_sg, baseline_tsr), ('candidate_pair', candidate_sg, candidate_tsr)]:
        frames = run_arm(name, detector, classifier, sg, mu, classes, images, args.output, args.device)
        rows = match_targets(frames, targets, sg)
        arms[name] = {'summary': summarize(rows),
                      'by_label': {label: summarize([r for r in rows if r['label'] == label]) for label in ['city:start', 'city:end']},
                      'by_subset': {s: summarize([r for r in rows if r['subset'] == s]) for s in sorted({r['subset'] for r in rows})},
                      'site_balanced': balanced(rows, 'site_id'), 'group_balanced': balanced(rows, 'group_id'),
                      'known_target_results': rows, 'full_frames_and_all_post_nms_detections': frames}
    assert arms['baseline_pair']['summary']['correct_city_known_targets'] == 0, 'Baseline134 unexpectedly produced a city label'
    report = {'schema_version': 'fixed-city-sgblur-tsr-pipeline-v1', 'plan_sha256': args.plan_sha256,
              'script_sha256': sha(__file__), 'model_sha256': plan['model_sha256'],
              'frozen_target_manifest_sha256': plan['frozen_target_manifest_sha256'],
              'tsr_training_manifest_sha256': manifest_sha, 'known_city_targets': 15,
              'uses_actual_post_nms_detected_native_pixel_crops': True, 'gt_crops_used_for_classification': False,
              'no_model_selection_or_tuning': True, 'human_reviewed': False,
              'classifier_preprocessing': mu.PREPROCESSING, 'arms': arms,
              'limits': ['Known-target pipeline recall only. Incomplete full-frame GT prevents precision/AP.',
                         'Baseline134 has no city outputs; baseline-pair zero is expected by vocabulary, not a universal quality comparison.',
                         'Actual detected crops can differ from reviewed GT crops; this is a separate frozen pipeline score.',
                         'Small assistant-reviewed purposive set; native/projected and grouping support retained; no app/device/general deployment claim.']}
    save(args.output/'pipeline-results.json', report)
    artifacts = [{'path': p.relative_to(args.output).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)}
                 for p in sorted(args.output.rglob('*')) if p.is_file()]
    save(args.output/'artifact-sha256.json', {'schema_version': 'fixed-pipeline-artifacts-v1', 'files': artifacts})
    print(json.dumps({arm: value['summary'] for arm, value in arms.items()}), flush=True)


if __name__ == '__main__':
    main()
