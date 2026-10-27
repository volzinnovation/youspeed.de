#!/usr/bin/env python3
"""Bound cold-still native paint diagnostics and frozen semantic-score variants.

Fitted/observed centerline support is not segmentation IoU, ego-lane accuracy,
sign applicability, temporal validation, or device performance. Reviewed labels
enter evaluation and the explicitly named oracle only, never learned guidance.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import a2d2_baseline as paint
import evaluate_semantic_guidance as guidance
import qualify_semantic_hints as hints

RADII = (2, 0)
ROI = (.58, .95)
SUPPRESSION_THRESHOLD = .5
COUNT_KEYS = ('predictedCenterlinePixels', 'supportedCenterlinePixels',
              'annotatedPaintPixels', 'coveredPaintPixels', 'ignoredUnknownCenterlinePixels')
FALLBACK = ('missing', 'stale', 'wrong_generation')
PROTOCOL = dict(
    schemaVersion=1, kind='native-cold-still-paint-diagnostics-v1',
    toleranceAnalysisPixels=list(RADII), evaluationYRange=list(ROI), maximumBonus=.10,
    learnedValidity='All native map cells; independent of annotation validity.',
    candidateCompatibility='Existing mean rowwise 2-pixel-band maximum; explicit observed segments if present, otherwise fitted points; y ceil(.58*(h-1)) through floor(.95*(h-1)).',
    supportRasterization='Union of one-pixel paint polylines; observed uses explicit segments only and never fitted fallback; ROI endpoints rounded; unknown target pixels excluded.',
    uniform='One spatial-mean control per model and frame, preserving mean probability; no location preference.',
    oracle='Reviewed binary paint + reviewed validity; bounded candidate-ranking diagnostic, neither deployable nor a universal upper bound.',
    suppression=dict(threshold=SUPPRESSION_THRESHOLD, rule='Retain each raw paint candidate iff learned compatibility >=0.5; no retuning. Report geometry and explicit observed unions of retained/rejected candidates.',
                     scope='Offline filtering only, not actual native integration or visible behavior; overlapping retained/rejected pixels need not form a partition.'),
    uncertainty='Descriptive counts only; no bootstrap or fresh-holdout claim.',
    qualification='Previously exposed development stills. Fresh session at time zero for every frame; no invented chronology or temporal confirmation. No sign-to-ego-path/exit truth or phone timing.')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + '\n')


def unique(rows, label):
    require(isinstance(rows, list) and bool(rows), label + ' must be a nonempty list')
    require(all(isinstance(r, dict) and isinstance(r.get('id'), str) and r['id'] for r in rows), label + ' IDs invalid')
    byid = {r['id']: r for r in rows}
    require(len(byid) == len(rows), label + ' duplicate IDs')
    return byid


def load_inputs(manifest_path, targets_path):
    manifest, target_data = read(manifest_path), read(targets_path)
    require(manifest.get('schemaVersion') == target_data.get('schemaVersion') == 1, 'Input schema mismatch')
    frames, targets = manifest['frames'], target_data['targets']
    require(list(unique(frames, 'input')) == list(unique(targets, 'target')), 'Input/target order differs')
    guidance.require_unguided_source(frames)
    masks = {}
    for frame, target in zip(frames, targets):
        require(frame['sequenceId'] == frame['id'] and frame['time'] == 0, 'Independent time-zero stills required')
        require(frame['graySha256'] == target['inputSha256'] == paint.sha(frame['grayPath']), 'Input bytes differ')
        shape = (frame['height'], frame['width'])
        require(shape == (target['height'], target['width']), 'Target shape differs')
        require(Path(frame['grayPath']).stat().st_size == shape[0]*shape[1], 'Gray size differs')
        require(frame['dataset'] == target['dataset'] and frame['split'] == target['split'], 'Dataset/split differs')
        require(frame['groupId'] == target['groupId'] and frame['sourceFrameId'] == target['sourceFrameId'], 'Source grouping differs')
        arrays = []
        for name in ('paint', 'valid'):
            require(paint.sha(target[name+'MaskPath']) == target[name+'MaskSha256'], 'Target bytes differ: ' + name)
            a = cv2.imread(target[name+'MaskPath'], cv2.IMREAD_UNCHANGED)
            require(a is not None and a.shape == shape and a.dtype == np.uint8, 'Target image shape/type differs')
            require(np.isin(a, (0, 255)).all(), 'Target mask must be binary 0/255')
            arrays.append(a > 0)
        require(not (arrays[0] & ~arrays[1]).any(), 'Paint outside valid target domain')
        masks[frame['id']] = tuple(arrays)
    return frames, targets, masks


def load_native(path, frames):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    require(list(unique(rows, 'native')) == [f['id'] for f in frames], 'Native frame order differs')
    for row, frame in zip(rows, frames):
        for key in ('id', 'sequenceId', 'time', 'width', 'height'):
            require(row.get(key) == frame[key], 'Native identity differs: ' + key)
        require(row.get('inputSha256') == frame['graySha256'], 'Native input hash differs')
        raw = row['rawBoundaries']
        require(isinstance(raw, list), 'Native raw boundaries missing')
        for boundary in raw:
            for segment in [boundary['points']] + boundary.get('observedSegments', []):
                require(isinstance(segment, list), 'Invalid native polyline')
                require(all(isinstance(p, list) and len(p) == 2 and
                            all(type(v) in (float, int) and math.isfinite(v) and 0 <= v <= 1 for v in p)
                            for p in segment), 'Native points outside normalized image')
        indices = row['visibleBoundaryIndices']
        require(isinstance(indices, list) and len(set(indices)) == len(indices) and
                all(type(i) is int and 0 <= i < len(raw) for i in indices), 'Invalid visible indices')
        require(row['confirmedBoundaries'] == [raw[i] for i in indices], 'Visible/raw boundary binding differs')
    return rows


def support_counts(prediction, truth, valid, radius=2):
    require(radius in RADII, 'Unfrozen tolerance')
    require(prediction.shape == truth.shape == valid.shape, 'Scoring mask shape differs')
    h, w = truth.shape
    roi = np.zeros((h, w), bool)
    roi[round(ROI[0]*(h-1)):round(ROI[1]*(h-1))+1] = True
    known = valid & roi
    p, t = prediction.astype(bool) & known, truth & known
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius+1, 2*radius+1))
    td = cv2.dilate(t.astype(np.uint8), kernel).astype(bool)
    pd = cv2.dilate(p.astype(np.uint8), kernel).astype(bool)
    return dict(predictedCenterlinePixels=int(p.sum()), supportedCenterlinePixels=int((p & td).sum()),
                annotatedPaintPixels=int(t.sum()), coveredPaintPixels=int((t & pd).sum()),
                ignoredUnknownCenterlinePixels=int((prediction.astype(bool) & roi & ~valid).sum()))


def aggregate(records):
    counts = {key: sum(r[key] for r in records) for key in COUNT_KEYS}
    return dict(frames=len(records), framesWithPrediction=sum(r['predictedCenterlinePixels'] > 0 for r in records),
                framesWithAnnotatedPaint=sum(r['annotatedPaintPixels'] > 0 for r in records), **paint.with_rates(counts))


def grouped(records):
    datasets, groups = defaultdict(list), defaultdict(list)
    for record in records:
        datasets[record['dataset']].append(record)
        groups[(record['dataset'], record['groupId'])].append(record)
    return dict(byDataset={k: aggregate(v) for k, v in sorted(datasets.items())},
                byGroup=[dict(dataset=k[0], groupId=k[1], **aggregate(v)) for k, v in sorted(groups.items())], frames=records)


def score_rows(rows, targets, masks, selector=None):
    results = {}
    for scope in ('raw', 'visible'):
        for field in ('geometry', 'observed'):
            for radius in RADII:
                records = []
                for row, target in zip(rows, targets):
                    boundaries = row['rawBoundaries'] if scope == 'raw' else row['confirmedBoundaries']
                    if selector is not None:
                        boundaries = selector(row, boundaries)
                    p = paint.rasterize(boundaries, target['width'], target['height'], field)
                    truth, valid = masks[row['id']]
                    counts = support_counts(p, truth, valid, radius)
                    records.append(dict(id=row['id'], dataset=target['dataset'], groupId=target['groupId'],
                                        **paint.with_rates(counts)))
                results[f'{scope}.{field}.radius{radius}'] = grouped(records)
    return results


def assert_guidance_invariants(baseline, guided, fallback=False):
    require(len(baseline) == len(guided), 'Variant count differs')
    changes = Counter()
    for a, b in zip(baseline, guided):
        require(a['id'] == b['id'], 'Variant order differs')
        require(a['rawBoundaries'] == b['rawBoundaries'], 'Guidance changed extracted geometry/support/confidence')
        require(a.get('lanePresentation', {}).get('items') == b.get('lanePresentation', {}).get('items'),
                'Guidance changed temporal observations/maturity')
        if fallback:
            require(guidance.stable_output(a) == guidance.stable_output(b), 'Rejected hint changed baseline behavior')
        changes['frames'] += 1
        changes['visibleIndexChanges'] += a['visibleBoundaryIndices'] != b['visibleBoundaryIndices']
        changes['visibleIdChanges'] += a.get('visibleIDs') != b.get('visibleIDs')
        changes['selectorDiagnosticChanges'] += a.get('lanePresentation') != b.get('lanePresentation')
    return dict(changes, exactFallbackVerified=fallback)


def load_probabilities(path, frames, targets):
    index = read(path)
    require(index.get('schemaVersion') == 1, 'Probability index schema differs')
    models = index['models']
    unique(models, 'models')
    expected = {(m['id'], f['id']) for m in models for f in frames}
    bykey = {(p['modelId'], p['id']): p for p in index['predictions']}
    require(len(bykey) == len(index['predictions']) and set(bykey) == expected, 'Probability coverage/uniqueness differs')
    maps = {}
    for model in models:
        require(all(isinstance(model.get(k), str) and len(model[k]) == 64 for k in ('checkpointSha256', 'sourceMetricsSha256')), 'Model source binding missing')
        for frame, target in zip(frames, targets):
            key = (model['id'], frame['id'])
            item = bykey[key]
            require(item['inputSha256'] == frame['graySha256'] and item['imageSha256'] == target['imageSha256'], 'Probability exposure differs')
            require((item['height'], item['width']) == (frame['height'], frame['width']), 'Probability dimensions differ')
            require(paint.sha(item['probabilityPath']) == item['probabilitySha256'], 'Probability bytes differ')
            a = np.load(item['probabilityPath'], allow_pickle=False)
            require(a.shape == (frame['height'], frame['width']) and a.dtype == np.float32 and
                    np.isfinite(a).all() and ((a >= 0) & (a <= 1)).all(), 'Invalid probability map')
            maps[key] = a
    return index, maps


def still_envelope(frame, probability, validity, model_id, revision, synthetic=False):
    policy = hints.QualificationPolicy(model_id, revision, frame['width'], frame['height'], guidance.MAX_AGE_NS)
    clock = 'simulated-independent-still:' + frame['id']
    exposure = dict(frameId=frame['id'], sourceTimeNs=0, sourceClockId='source-still:' + frame['graySha256'],
                    capturedAtNs=1_000_000_000, clockId=clock, clockKnown=True)
    scope = dict(sessionId='offline:' + frame['id'], sessionGeneration=0, cameraId='dataset-camera',
                 cameraGeneration=0, calibrationGeneration=0)
    geometry = dict(sourceWidth=frame['decodedWidth'], sourceHeight=frame['decodedHeight'],
                    crop=dict(x=0, y=0, width=frame['decodedWidth'], height=frame['decodedHeight']),
                    rotationDegrees=0, mirrored=False, analysisWidth=frame['width'], analysisHeight=frame['height'],
                    mappingId='full-frame-inverse-letterbox-v1', fullScene=True)
    instant = dict(atNs=1_000_000_000, clockId=clock, clockKnown=True)
    context = dict(schemaVersion=1, scope=scope, exposure=exposure, geometry=geometry, now=instant)
    hint = dict(schemaVersion=1, scope=copy.deepcopy(scope), exposure=copy.deepcopy(exposure), geometry=copy.deepcopy(geometry),
                arrival=copy.deepcopy(instant), modelIdentity=policy.model_identity,
                provenance=dict(kind='synthetic_fixture' if synthetic else 'model_inference', sourceId=frame['graySha256']),
                alignment=dict(mode='exact_exposure'), mask=dict(width=frame['width'], height=frame['height'],
                probabilities=probability.reshape(-1).tolist(), validity=validity.reshape(-1).tolist()))
    return policy, context, hint


def qualify_scores(frame, boundaries, probability, validity, model_id, revision, kind):
    if kind == 'missing':
        return None, 'missing_hint', []
    policy, context, hint = still_envelope(frame, probability, validity, model_id, revision, kind in ('uniform', 'oracle'))
    if kind == 'stale':
        context['now']['atNs'] += 250_000_000
    if kind == 'wrong_generation':
        hint['scope']['cameraGeneration'] += 1
    result = hints.qualify(hint, context, policy)
    if not result.accepted:
        return None, result.reason, []
    p = np.asarray(result.hint.probabilities).reshape(probability.shape)
    v = np.asarray(result.hint.validity, dtype=bool).reshape(probability.shape)
    compatibility = [guidance.compatibility(b, p, v) if b.get('cue') == 'paint' else 0. for b in boundaries]
    return [guidance.MAX_BONUS*c for c in compatibility], result.reason, compatibility


def variant_specs(models):
    specs = []
    for model in models:
        specs.extend([dict(id='learned-' + model['id'], kind='learned', model=model),
                      dict(id='uniform-' + model['id'], kind='uniform', model=model)])
    specs.append(dict(id='reviewed-mask-oracle', kind='oracle', model=None))
    specs.extend(dict(id=k, kind=k, model=models[0]) for k in FALLBACK)
    return specs


def prepare_variants(manifest, targets_path, probability_path, baseline_path, output):
    require(not output.exists(), 'Variant output already exists')
    frames, targets, masks = load_inputs(manifest, targets_path)
    baseline = load_native(baseline_path, frames)
    index, maps = load_probabilities(probability_path, frames, targets)
    output.mkdir(parents=True)
    # Written before scoring candidate compatibility or consulting resulting native output.
    write_new(output/'protocol.json', dict(PROTOCOL, inputManifestSha256=paint.sha(manifest),
              targetsSha256=paint.sha(targets_path), probabilitiesSha256=paint.sha(probability_path),
              baselineSha256=paint.sha(baseline_path), scriptSha256=paint.sha(__file__)))
    records = []
    for spec in variant_specs(index['models']):
        result_frames, diagnostics = [], []
        kind, model = spec['kind'], spec['model']
        for frame, target, row in zip(frames, targets, baseline):
            if kind == 'oracle':
                truth, valid = masks[frame['id']]
                probability = truth.astype(np.float32)
                model_id, revision = 'reviewed-mask-diagnostic', target['paintMaskSha256']
            else:
                probability = maps[(model['id'], frame['id'])]
                valid = np.ones(probability.shape, dtype=bool)
                model_id, revision = model['id'], model['checkpointSha256']
                if kind == 'uniform':
                    probability = np.full_like(probability, float(probability.mean()))
            scores, reason, compat = qualify_scores(frame, row['rawBoundaries'], probability, valid, model_id, revision, kind)
            if kind in ('learned', 'uniform'):
                require(scores is not None, 'Model hint unexpectedly rejected: ' + reason)
            if kind in FALLBACK:
                require(scores is None, 'Fault unexpectedly qualified')
            new_frame = dict(frame)
            if scores is not None:
                new_frame.update(semanticScoreAdjustments=scores, semanticSourceInputSha256=frame['graySha256'])
            result_frames.append(new_frame)
            diagnostics.append(dict(id=frame['id'], qualification=reason, compatibility=compat, bonuses=scores,
                candidateReasons=row.get('lanePresentation', {}).get('selectionDecisions', [])))
        path = output/(spec['id'] + '.json')
        write_new(path, dict(schemaVersion=1, frames=result_frames))
        diag = output/(spec['id'] + '.diagnostics.json')
        write_new(diag, dict(spec=spec, frames=diagnostics))
        records.append(dict(id=spec['id'], kind=kind, model=model, manifest=str(path.resolve()), manifestSha256=paint.sha(path),
                            diagnostics=str(diag.resolve()), diagnosticsSha256=paint.sha(diag)))
    result = dict(schemaVersion=1, protocolSha256=paint.sha(output/'protocol.json'), variants=records)
    write_new(output/'index.json', result)
    return dict(variants=len(records), frames=len(frames), index=str(output/'index.json'))


def score_native(manifest, targets_path, replay, output, baseline=None, fallback=False):
    frames, targets, masks = load_inputs(manifest, targets_path)
    rows = load_native(replay, frames)
    invariants = None
    if baseline:
        invariants = assert_guidance_invariants(load_native(baseline, frames), rows, fallback)
    else:
        require(not fallback, 'Fallback requires baseline')
    reasons = Counter(d.get('reason', 'unknown') for r in rows for d in r.get('lanePresentation', {}).get('selectionDecisions', []))
    result = dict(schemaVersion=1, protocol=PROTOCOL, inputManifestSha256=paint.sha(manifest),
                  targetsSha256=paint.sha(targets_path), replaySha256=paint.sha(replay), scriptSha256=paint.sha(__file__),
                  guidanceInvariants=invariants, candidateSelectionReasons=dict(reasons),
                  support=score_rows(rows, targets, masks))
    write_new(output, result)
    return dict(frames=len(rows), output=str(output), invariants=invariants)


def segmentation_counts(probability, truth, valid, roi=False):
    if roi:
        valid = valid.copy()
        valid[:round(ROI[0]*(len(valid)-1))] = False
        valid[round(ROI[1]*(len(valid)-1))+1:] = False
    pred = probability >= .5
    c = dict(tp=int((pred & truth & valid).sum()), fp=int((pred & ~truth & valid).sum()),
             fn=int((~pred & truth & valid).sum()), tn=int((~pred & ~truth & valid).sum()))
    return mask_rates(c)


def mask_rates(c):
    return dict(c, markingIoU=c['tp']/(c['tp']+c['fp']+c['fn']) if c['tp']+c['fp']+c['fn'] else None,
                precision=c['tp']/(c['tp']+c['fp']) if c['tp']+c['fp'] else None,
                recall=c['tp']/(c['tp']+c['fn']) if c['tp']+c['fn'] else None)


def probe_models(manifest, targets_path, probability_path, replay, output):
    frames, targets, masks = load_inputs(manifest, targets_path)
    rows = load_native(replay, frames)
    index, maps = load_probabilities(probability_path, frames, targets)
    # This explicitly separate offline intervention cannot be confused with replay output.
    models = []
    for model in index['models']:
        retained, rejected, candidate_scores, segmentation = [], [], [], []
        for row, target in zip(rows, targets):
            p = maps[(model['id'], row['id'])]
            compat = [guidance.compatibility(b, p, np.ones_like(p, dtype=bool)) if b.get('cue') == 'paint' else None for b in row['rawBoundaries']]
            keep = [b for b, c in zip(row['rawBoundaries'], compat) if c is not None and c >= SUPPRESSION_THRESHOLD]
            drop = [b for b, c in zip(row['rawBoundaries'], compat) if c is not None and c < SUPPRESSION_THRESHOLD]
            retained.append(dict(row, rawBoundaries=keep, confirmedBoundaries=[]))
            rejected.append(dict(row, rawBoundaries=drop, confirmedBoundaries=[]))
            candidate_scores.append(dict(id=row['id'], compatibility=compat, retainedPaintCandidates=len(keep), rejectedPaintCandidates=len(drop)))
            truth, valid = masks[row['id']]
            segmentation.append(dict(id=row['id'], dataset=target['dataset'], groupId=target['groupId'],
                                     fullImage=segmentation_counts(p, truth, valid), roi=segmentation_counts(p, truth, valid, roi=True)))
        mask_totals = {scope: {} for scope in ('fullImage', 'roi')}
        for dataset in sorted({t['dataset'] for t in targets}):
            rs = [r for r in segmentation if r['dataset'] == dataset]
            for scope in mask_totals:
                counts = {k: sum(r[scope][k] for r in rs) for k in ('tp', 'fp', 'fn', 'tn')}
                mask_totals[scope][dataset] = dict(frames=len(rs), **mask_rates(counts))
        models.append(dict(model=model, candidates=candidate_scores,
            retained={k: v for k, v in score_rows(retained, targets, masks).items() if k.startswith('raw.')},
            rejected={k: v for k, v in score_rows(rejected, targets, masks).items() if k.startswith('raw.')},
            segmentationAnalysisResolution=dict(byDataset=mask_totals, frames=segmentation)))
    result = dict(schemaVersion=1, protocol=PROTOCOL, inputManifestSha256=paint.sha(manifest), targetsSha256=paint.sha(targets_path),
                  probabilitiesSha256=paint.sha(probability_path), replaySha256=paint.sha(replay), scriptSha256=paint.sha(__file__),
                  baseline={k: v for k, v in score_rows(rows, targets, masks).items() if k.startswith('raw.')}, models=models,
                  maskMetricQualification='Threshold0.5 after inverse letterbox to native resolution; known-only, full image and fixed ROI reported separately. Any-area target occupancy differs from original640 evaluation; not comparable to line-support precision or an official dataset metric.')
    write_new(output, result)
    return dict(models=len(models), frames=len(rows), output=str(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('variants', 'score', 'probe'):
        p = sub.add_parser(name)
        p.add_argument('--manifest', type=Path, required=True)
        p.add_argument('--targets', type=Path, required=True)
        if name != 'score':
            p.add_argument('--probabilities', type=Path, required=True)
        if name == 'variants':
            p.add_argument('--baseline', type=Path, required=True)
            p.add_argument('--output-dir', type=Path, required=True)
        else:
            p.add_argument('--replay', type=Path, required=True)
            p.add_argument('--output', type=Path, required=True)
        if name == 'score':
            p.add_argument('--baseline', type=Path)
            p.add_argument('--fallback', action='store_true')
    args = parser.parse_args()
    if args.command == 'variants':
        result = prepare_variants(args.manifest, args.targets, args.probabilities, args.baseline, args.output_dir)
    elif args.command == 'score':
        result = score_native(args.manifest, args.targets, args.replay, args.output, args.baseline, args.fallback)
    else:
        result = probe_models(args.manifest, args.targets, args.probabilities, args.replay, args.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
