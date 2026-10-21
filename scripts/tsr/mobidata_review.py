#!/usr/bin/env python3
"""Match a visually proposed town-sign target to source annotations and SGBlur boxes.

Source classifications only describe a target when their own box overlaps it.
Registry proximity and labels on neighbouring signs do not establish a match.
"""
import math


def valid_box(box):
    return (isinstance(box, (list, tuple)) and len(box) >= 4
            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in box[:4])
            and box[2] > box[0] and box[3] > box[1])


def iou(a, b):
    if not valid_box(a) or not valid_box(b):
        return 0.0
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union


def annotation_box(annotation):
    shape = annotation.get('shape', {})
    if shape.get('type') != 'Polygon':
        return None
    points = [point for ring in shape.get('coordinates', []) for point in ring]
    if not points or any(not isinstance(p, (list, tuple)) or len(p) != 2
                         or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in p) for p in points):
        return None
    box = [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]
    return box if valid_box(box) else None


def source_target_assessment(annotations, target, expected_code, threshold=0.5):
    matches = []
    for a in annotations:
        semantics = a.get('semantics', [])
        codes = [s['value'] for s in semantics if s.get('key') == 'osm|traffic_sign' and isinstance(s.get('value'), str)]
        box = annotation_box(a)
        overlap = iou(target, box)
        if not codes or overlap < threshold:
            continue
        matches.append(dict(annotation_id=a.get('id'), bbox_xyxy=box, target_iou=overlap,
            original_sign_codes=codes, original_semantics=semantics,
            detection_models=[s['value'] for s in semantics if s.get('key', '').startswith('detection_model[')],
            classification_models=[s['value'] for s in semantics if s.get('key', '').startswith('classification_model[')]))
    matches.sort(key=lambda m: m['target_iou'], reverse=True)
    codes = {c for m in matches for c in m['original_sign_codes']}
    if not matches:
        status = 'no_stored_target_box'
    elif expected_code in codes:
        status = 'classified_expected_code'
    elif codes - {'yes'}:
        status = 'detected_but_wrong_code_proposal'
    else:
        status = 'detected_but_unclassified_yes'
    return dict(source_target_status=status, source_target_annotation_id=matches[0]['annotation_id'] if matches else None,
        source_target_matches=matches, source_target_match_iou=threshold,
        source_target_original_codes=sorted(codes), source_annotations_changed=False)


def baseline_target_assessment(detections, target, threshold=0.5):
    signs = [b for b in detections if len(b) >= 6 and int(b[5]) == 0]
    others = [b for b in detections if len(b) >= 6 and int(b[5]) != 0]
    sign_iou = max((iou(target, b) for b in signs), default=0)
    other = max(others, key=lambda b: iou(target, b), default=None)
    other_iou = iou(target, other)
    detected = sign_iou >= threshold
    issue = 'detected_sign' if detected else ('wrong_object_class' if other_iou >= threshold else 'missed_sign')
    return dict(sgblur_yolo11n_target_detected=detected, sgblur_yolo11n_target_iou=sign_iou,
        sgblur_yolo11n_other_class_iou=other_iou,
        sgblur_yolo11n_other_class=int(other[5]) if other is not None and other_iou >= threshold else None,
        sgblur_yolo11n_target_issue=issue)
