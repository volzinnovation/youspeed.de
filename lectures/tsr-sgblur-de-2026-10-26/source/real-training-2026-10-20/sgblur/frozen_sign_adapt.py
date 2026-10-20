#!/usr/bin/env python3
"""Conservative partial-GT SGBlur experiment; no production/export integration.

Only row 0 of the three final classification convolutions may change. Known
positive sign anchors use GT=1. All remaining sign anchors retain soft baseline
teacher supervision (weight 1). Regression, other logits and BN stay frozen.
Incomplete annotations support target recall, never detection AP/precision.
"""
import argparse
import copy
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

BASELINE_SHA = '698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a'
FORMAT = 'sgblur-frozen-sign-output-v1'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    temp.replace(path)


def dependencies():
    global torch, np, F, Image, LetterBox, non_max_suppression, make_anchors, dist2bbox, TaskAlignedAssigner, YOLO
    import torch
    import torch.nn.functional as F
    import numpy as np
    from PIL import Image
    from ultralytics import YOLO
    from ultralytics.data.augment import LetterBox
    from ultralytics.utils.nms import non_max_suppression
    from ultralytics.utils.tal import make_anchors, dist2bbox, TaskAlignedAssigner
    import ultralytics
    if ultralytics.__version__ != '8.4.56':
        raise ValueError('This experiment requires the inspected Ultralytics 8.4.56')


def load_model(baseline, device, candidate=None):
    assert sha(baseline) == BASELINE_SHA, 'Baseline SHA mismatch'
    model = YOLO(str(baseline)).model.float().to(device).eval()
    head = model.model[-1]
    assert model.names == {0: 'sign', 1: 'plate', 2: 'face'}
    assert head.nc == 3 and head.nl == 3 and not head.end2end
    assert all(list(branch[-1].weight.shape) == [3, 64, 1, 1] for branch in head.cv3)
    if candidate:
        saved = torch.load(candidate, map_location='cpu', weights_only=True)
        assert saved['format'] == FORMAT and saved['baseline_sha256'] == BASELINE_SHA
        model.load_state_dict(saved['model_state'], strict=True)
    return model


def freeze_sign_only(model):
    for p in model.parameters():
        p.requires_grad_(False)
    parameters = []
    names = {id(p): name for name, p in model.named_parameters()}
    allowed = []
    def gradient_sign_row_only(gradient):
        result = gradient.clone()
        result[1:] = 0
        return result
    for branch in model.model[-1].cv3:
        for p in [branch[-1].weight, branch[-1].bias]:
            p.requires_grad_(True)
            p.register_hook(gradient_sign_row_only)
            parameters.append(p)
            allowed.append(names[id(p)])
    assert len(parameters) == 6
    return parameters, allowed


def frozen_proof(model, reference, allowed):
    current = model.state_dict()
    changed_allowed, forbidden = 0, []
    for name, before in reference.items():
        after = current[name].detach().cpu()
        if name in allowed:
            if not torch.equal(after[1:], before[1:]):
                forbidden.append(name + '[1:]')
            changed_allowed += int((after[0] != before[0]).sum())
        elif not torch.equal(after, before):
            forbidden.append(name)
    assert not forbidden, f'Frozen-state violation: {forbidden}'
    return {'all_non_sign_state_bitwise_unchanged': True,
            'changed_sign_output_scalars': changed_allowed,
            'allowed_sign_output_scalars': 195, 'allowed_parameter_names': allowed,
            'forbidden_changes': forbidden}


def raw_forward(model, images):
    # Keep every module, including all BatchNorm instances, in eval mode. Eval
    # still permits gradients; raw head tensors are returned alongside decoding.
    model.eval()
    result = model(images)
    assert isinstance(result, tuple) and isinstance(result[1], dict)
    return result


def read_image(frame, imgsz, verify=True):
    path = Path(frame.get('image_path', frame.get('input_image_absolute_path', '')))
    expected = frame.get('image_sha256', frame.get('input_sha256'))
    if verify:
        assert sha(path) == expected, f'Image checksum mismatch: {path.name}'
    with Image.open(path) as im:
        rgb = np.asarray(im.convert('RGB'))
    height, width = rgb.shape[:2]
    ratio = min(imgsz/width, imgsz/height)
    left = round((imgsz-round(width*ratio))/2-.1)
    top = round((imgsz-round(height*ratio))/2-.1)
    transformed = LetterBox(new_shape=(imgsz, imgsz), auto=False, stride=32)(image=rgb)
    tensor = torch.from_numpy(np.ascontiguousarray(transformed.transpose(2, 0, 1))).float()/255
    boxes = []
    for box in frame.get('boxes', []):
        assert box['class_id'] == 0, 'This partial experiment supervises known sign boxes only'
        x1, y1, x2, y2 = box['bbox_xyxy']
        assert 0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height
        boxes.append([x1*ratio+left, y1*ratio+top, x2*ratio+left, y2*ratio+top])
    return tensor, boxes, (ratio, left, top, width, height)


def partial_loss(student, teacher, images, boxes):
    _, raw = raw_forward(student, images)
    with torch.no_grad():
        _, original = raw_forward(teacher, images)
        head = teacher.model[-1]
        anchors, strides = make_anchors(original['feats'], head.stride, .5)
        dist = original['boxes'].permute(0, 2, 1).contiguous()
        b, n, _ = dist.shape
        distances = dist.view(b, n, 4, head.reg_max).softmax(3).matmul(
            torch.arange(head.reg_max, dtype=dist.dtype, device=dist.device))
        decoded = dist2bbox(distances, anchors, xywh=False)*strides
        count = max(len(x) for x in boxes)
        gt_boxes = torch.zeros((b, count, 4), device=images.device)
        mask = torch.zeros((b, count, 1), device=images.device, dtype=torch.bool)
        for i, row in enumerate(boxes):
            if row:
                gt_boxes[i, :len(row)] = torch.tensor(row, device=images.device)
                mask[i, :len(row)] = True
        assigner = TaskAlignedAssigner(topk=10, num_classes=3, alpha=.5, beta=6., stride=head.stride.tolist())
        assigned = assigner(original['scores'].sigmoid().permute(0, 2, 1), decoded,
                            anchors*strides, torch.zeros((b, count, 1), device=images.device), gt_boxes, mask)
        foreground = assigned[3]
    sign = raw['scores'][:, 0, :]
    teacher_logits = original['scores'][:, 0, :]
    assert foreground.any(), 'No assignable known positive anchors in batch'
    positive = F.binary_cross_entropy_with_logits(sign[foreground], torch.ones_like(sign[foreground]))
    background = F.binary_cross_entropy_with_logits(sign[~foreground], teacher_logits[~foreground].sigmoid())
    # Weight fixed before any validation/test predictions; no hard negatives are
    # inferred from the incomplete scene annotations.
    loss = positive + background
    with torch.no_grad():
        assert torch.equal(raw['boxes'], original['boxes'])
        assert torch.equal(raw['scores'][:, 1:], original['scores'][:, 1:])
        entropy = F.binary_cross_entropy_with_logits(teacher_logits[~foreground], teacher_logits[~foreground].sigmoid())
    return loss, {'positive_bce': float(positive.detach()), 'teacher_bce': float(background.detach()),
                  'teacher_kl': float((background-entropy).detach()), 'positive_anchors': int(foreground.sum())}


def box_iou(a, b):
    overlap = max(0., min(a[2], b[2])-max(a[0], b[0]))*max(0., min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-overlap
    return overlap/union if union > 0 else 0.


def target_rows(frames):
    rows = []
    for frame in frames:
        for number, box in enumerate(frame['boxes']):
            rows.append({'sample_id': f'{frame["picture_id"]}:{number}', 'picture_id': frame['picture_id'],
                         'input_image_absolute_path': frame['image_path'], 'input_sha256': frame['image_sha256'],
                         'bbox_xyxy': box['bbox_xyxy'], 'label': box.get('city_label_proposal') or 'other_known_sign',
                         'subset': 'learning_validation', 'include_primary': True})
    return rows


def evaluate(model, teacher, rows, imgsz, device, verify=True):
    groups = defaultdict(list)
    for row in rows:
        if row.get('include_primary', True):
            groups[(row['input_image_absolute_path'], row['input_sha256'])].append(row)
    predictions, post_changes, raw_equal, drift_sum, drift_n = [], [], True, 0., 0
    with torch.inference_mode():
        for (path, digest), targets in groups.items():
            tensor, _, transform = read_image({'input_image_absolute_path': path, 'input_sha256': digest}, imgsz, verify)
            image = tensor.unsqueeze(0).to(device)
            y, raw = raw_forward(model, image)
            y0, original = raw_forward(teacher, image)
            equal = torch.equal(raw['boxes'], original['boxes']) and torch.equal(raw['scores'][:, 1:], original['scores'][:, 1:])
            raw_equal = raw_equal and equal
            difference = (raw['scores'][:, 0].sigmoid()-original['scores'][:, 0].sigmoid()).abs()
            drift_sum += float(difference.sum())
            drift_n += difference.numel()
            detections = non_max_suppression(y, conf_thres=.25, iou_thres=.7, nc=3, max_det=300)[0].cpu().tolist()
            base = non_max_suppression(y0, conf_thres=.25, iou_thres=.7, nc=3, max_det=300)[0].cpu().tolist()
            ratio, left, top, width, height = transform
            def native(detections):
                result = []
                for d in detections:
                    result.append([max(0., min(width, (d[0]-left)/ratio)), max(0., min(height, (d[1]-top)/ratio)),
                                   max(0., min(width, (d[2]-left)/ratio)), max(0., min(height, (d[3]-top)/ratio)), d[4], int(d[5])])
                return result
            detections, base = native(detections), native(base)
            # Post-NMS face/plate lists can differ because sign changes may win
            # argmax at a shared proposal. Record this separately from raw proof.
            old = [d for d in base if d[5] in [1, 2]]
            now = [d for d in detections if d[5] in [1, 2]]
            if old != now:
                post_changes.append({'picture_id': targets[0]['picture_id'], 'baseline_plate_face': old, 'candidate_plate_face': now})
            sign = [d for d in detections if d[5] == 0]
            pairs = sorted([(box_iou(t['bbox_xyxy'], d[:4]), i, j) for i, t in enumerate(targets) for j, d in enumerate(sign)], reverse=True)
            assigned_targets, used = {}, set()
            for overlap, i, j in pairs:
                if overlap >= .5 and i not in assigned_targets and j not in used:
                    assigned_targets[i] = (overlap, j)
                    used.add(j)
            for i, target in enumerate(targets):
                match = assigned_targets.get(i)
                best_iou = max((box_iou(target['bbox_xyxy'], d[:4]) for d in sign), default=0.)
                predictions.append({'sample_id': target['sample_id'], 'picture_id': target['picture_id'],
                                    'label': target['label'], 'subset': target.get('subset', 'unknown'),
                                    'matched': bool(match), 'best_sign_iou': best_iou,
                                    'matched_confidence': sign[match[1]][4] if match else None})
    def summary(selected):
        return {'targets': len(selected), 'matched': sum(r['matched'] for r in selected),
                'target_recall': sum(r['matched'] for r in selected)/len(selected) if selected else None}
    result = {'metric': 'known-target recall only; partial full-frame annotations', 'iou_threshold': .5,
              'confidence_threshold': .25, 'nms_iou': .7, 'imgsz': imgsz,
              'overall': summary(predictions),
              'by_label': {label: summary([r for r in predictions if r['label'] == label]) for label in sorted({r['label'] for r in predictions})},
              'city_all': summary([r for r in predictions if r['label'] in ['city:start', 'city:end']]),
              'old_sign_targets': summary([r for r in predictions if r['label'] not in ['city:start', 'city:end']]),
              'by_subset': {s: summary([r for r in predictions if r['subset'] == s]) for s in sorted({r['subset'] for r in predictions})},
              'pre_nms_regression_and_face_plate_logits_bitwise_unchanged': raw_equal,
              'post_nms_plate_face_changed_frames': post_changes,
              'mean_absolute_sign_probability_drift': drift_sum/drift_n if drift_n else 0.,
              'unmasked_face_plate_regression': 'NOT_EVALUABLE_NO_UNMASKED_GROUND_TRUTH',
              'full_image_precision_and_ap': 'NOT_EVALUABLE_INCOMPLETE_ANNOTATIONS', 'predictions': predictions}
    assert raw_equal, 'Frozen pre-NMS branches changed'
    return result


def save_checkpoint(path, model, epoch, metadata):
    torch.save({'format': FORMAT, 'baseline_sha256': BASELINE_SHA, 'epoch': epoch,
                'model_state': {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
                'experiment': metadata}, path)


def train(args):
    manifest = json.loads(Path(args.manifest).read_text())
    assert manifest['schema_version'] == 'sgblur-fullframe-review-v1'
    assert manifest['permitted_training_mode'].startswith('Freeze all model state except final sign output row')
    # The reviewed 20-frame candidate list includes seven reserved frames. They
    # are excluded before image loading, optimization and validation selection.
    frames = [r for r in manifest['frames'] if r['split'] in ['train', 'val']]
    reserved = [r for r in manifest['frames'] if r['split'] == 'reserved']
    training = [r for r in frames if r['split'] == 'train']
    validation = [r for r in frames if r['split'] == 'val']
    assert training and validation
    assert not {r['group_id'] for r in training} & {r['group_id'] for r in validation}
    assert all(r['review_status'] == 'target_approved_for_partial_gt_adaptation' for r in frames)
    assert all(r['target_sign_boxes_verified'] for r in frames)
    assert all(box['box_visually_verified_as_sign'] for r in frames for box in r['boxes'])
    assert all(not r['complete_all_visible_classes'] for r in frames)
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True, warn_only=True)
    model = load_model(args.baseline, args.device)
    teacher = copy.deepcopy(model).eval()
    for p in teacher.parameters():
        p.requires_grad_(False)
    reference = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    parameters, allowed = freeze_sign_only(model)
    initial_sign = [p[0].detach().clone() for p in parameters]
    optimizer = torch.optim.AdamW(parameters, lr=args.lr, weight_decay=0.)
    output = Path(args.output)
    assert not output.exists(), 'Choose a new experiment output directory'
    output.mkdir(parents=True)
    data = [(f, *read_image(f, args.imgsz)[:2]) for f in training]
    val_rows = target_rows(validation)
    metadata = {'training_manifest_sha256': sha(args.manifest), 'script_sha256': sha(__file__),
                'baseline_sha256': BASELINE_SHA, 'epochs': args.epochs, 'imgsz': args.imgsz,
                'batch': args.batch, 'optimizer': 'AdamW', 'lr': args.lr, 'seed': args.seed, 'weight_decay': 0.,
                'teacher_nonpositive_weight': 1., 'sign_delta_l2_weight': .0001,
                'augmentation': 'none; square RGB letterbox only; all source geometry preserved',
                'selection': 'validation target recall, then mean best IoU, then minimum sign probability drift; baseline epoch0 eligible',
                'training_frames': len(training), 'validation_frames': len(validation),
                'excluded_reserved_frames': len(reserved),
                'excluded_reserved_picture_ids': sorted(r['picture_id'] for r in reserved),
                'shared_split_sha256': manifest['shared_split_sha256'],
                'train_groups': sorted({r['group_id'] for r in training}), 'val_groups': sorted({r['group_id'] for r in validation}),
                'all_visible_object_annotation_complete': False, 'human_approved': False,
                'claim': '195-scalar sign output adaptation with partial assistant-reviewed GT, not full detector retraining'}
    write(output/'experiment.json', metadata)
    baseline_val = evaluate(model, teacher, val_rows, args.imgsz, args.device)
    write(output/'validation-epoch-00.json', baseline_val)
    def key(result):
        values = result['predictions']
        return (result['overall']['target_recall'], sum(r['best_sign_iou'] for r in values)/len(values), -result['mean_absolute_sign_probability_drift'])
    best_key, best_epoch, history = key(baseline_val), 0, []
    save_checkpoint(output/'best.pt', model, 0, metadata)
    for epoch in range(1, args.epochs+1):
        order = list(range(len(data)))
        random.shuffle(order)
        totals = Counter()
        for start in range(0, len(order), args.batch):
            batch = [data[i] for i in order[start:start+args.batch]]
            images = torch.stack([x[1] for x in batch]).to(args.device)
            boxes = [x[2] for x in batch]
            optimizer.zero_grad(set_to_none=True)
            loss, detail = partial_loss(model, teacher, images, boxes)
            l2 = sum((p[0]-initial).square().mean() for p, initial in zip(parameters, initial_sign))
            loss = loss + .0001*l2
            assert torch.isfinite(loss)
            loss.backward()
            optimizer.step()
            totals.update({**detail, 'loss': float(loss.detach()), 'batches': 1})
        proof = frozen_proof(model, reference, allowed)
        result = evaluate(model, teacher, val_rows, args.imgsz, args.device, verify=False)
        write(output/f'validation-epoch-{epoch:02d}.json', result)
        if key(result) > best_key:
            best_key, best_epoch = key(result), epoch
            save_checkpoint(output/'best.pt', model, epoch, metadata)
        save_checkpoint(output/'last.pt', model, epoch, metadata)
        row = {'epoch': epoch, 'loss': totals['loss']/totals['batches'],
               'positive_bce': totals['positive_bce']/totals['batches'],
               'teacher_kl': totals['teacher_kl']/totals['batches'],
               'positive_anchors': totals['positive_anchors'],
               'validation_target_recall': result['overall']['target_recall'],
               'sign_probability_drift': result['mean_absolute_sign_probability_drift'],
               'best_epoch': best_epoch, 'changed_sign_scalars': proof['changed_sign_output_scalars']}
        history.append(row)
        with (output/'progress.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row)); writer.writeheader(); writer.writerows(history)
        print(json.dumps(row), flush=True)
    write(output/'frozen-state-proof.json', frozen_proof(model, reference, allowed))
    write(output/'training-complete.json', {'epochs_completed': args.epochs, 'best_epoch': best_epoch,
          'best_checkpoint_sha256': sha(output/'best.pt'), 'last_checkpoint_sha256': sha(output/'last.pt'),
          'baseline_validation': baseline_val['overall'], 'best_validation_key': list(best_key),
          'no_test_predictions_used_for_selection': True})


def final_evaluation(args):
    test = json.loads(Path(args.manifest).read_text())
    assert test['role'] == 'test_only_no_training_or_selection'
    assert test['frozen_before_candidate_predictions']
    teacher = load_model(args.baseline, args.device)
    candidate = load_model(args.baseline, args.device, args.candidate)
    _, allowed = freeze_sign_only(candidate)
    reference = {k: v.detach().cpu().clone() for k, v in teacher.state_dict().items()}
    proof = frozen_proof(candidate, reference, allowed)
    output = Path(args.output)
    assert not output.exists()
    output.mkdir(parents=True)
    baseline = evaluate(teacher, teacher, test['rows'], args.imgsz, args.device)
    result = evaluate(candidate, teacher, test['rows'], args.imgsz, args.device)
    write(output/'baseline-target-recall.json', baseline)
    write(output/'candidate-target-recall.json', result)
    write(output/'frozen-state-proof.json', proof)
    write(output/'receipt.json', {'test_manifest_sha256': sha(args.manifest), 'baseline_sha256': BASELINE_SHA,
          'candidate_sha256': sha(args.candidate), 'test_predictions_used_for_selection': False,
          'baseline': baseline['overall'], 'candidate': result['overall'],
          'precision_ap_or_unmasked_face_plate_claim': False})
    print(json.dumps({'baseline': baseline['overall'], 'candidate': result['overall'], 'proof': proof}), flush=True)


def smoke(args):
    torch.set_num_threads(2)
    model = load_model(args.baseline, args.device)
    teacher = copy.deepcopy(model).eval()
    for p in teacher.parameters(): p.requires_grad_(False)
    reference = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    parameters, allowed = freeze_sign_only(model)
    optimizer = torch.optim.AdamW(parameters, lr=.001, weight_decay=0.)
    image = torch.full((1, 3, 128, 128), .5, device=args.device)
    loss, detail = partial_loss(model, teacher, image, [[[24., 24., 104., 104.]]])
    loss.backward(); optimizer.step()
    proof = frozen_proof(model, reference, allowed)
    with torch.no_grad():
        _, a = raw_forward(model, image); _, b = raw_forward(teacher, image)
        assert torch.equal(a['boxes'], b['boxes']) and torch.equal(a['scores'][:, 1:], b['scores'][:, 1:])
    write(args.output, {'smoke_only_not_real_training': True, 'device': args.device, 'loss': float(loss.detach()), 'loss_components': detail,
                        'proof': proof, 'raw_frozen_outputs_bitwise_equal': True, 'script_sha256': sha(__file__)})
    print(json.dumps({'status': 'PASS', 'proof': proof}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['train', 'evaluate', 'smoke'])
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--manifest')
    parser.add_argument('--candidate')
    parser.add_argument('--output', required=True)
    parser.add_argument('--device', default='cuda:0')
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--batch', type=int, default=2)
    parser.add_argument('--imgsz', type=int, default=1280)
    parser.add_argument('--lr', type=float, default=.001)
    parser.add_argument('--seed', type=int, default=20261026)
    args = parser.parse_args()
    if args.command != 'smoke':
        assert args.manifest and args.imgsz % 32 == 0
    if args.command == 'evaluate': assert args.candidate
    dependencies()
    if args.command == 'train': train(args)
    elif args.command == 'evaluate': final_evaluation(args)
    else: smoke(args)


if __name__ == '__main__':
    main()
