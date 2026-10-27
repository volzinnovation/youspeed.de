#!/usr/bin/env python3
"""Hash-bound, stateful native paint-hint ablations on recorded development frames.

Scores come from a previously trained, target-only model. Labels are read only
for reporting. Replay clocks/delays are explicitly simulated; no device schedule
or calibrated confidence is inferred. The native selector retains its gates and
dwell. No road-area model is synthesized from the available paint-only head.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_selection_opportunity as audit
import evaluate_auxiliary_video as video
import qualify_semantic_hints as hints

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = ('baseline', 'unqualified_paint', 'qualified_paint', 'uniform_control',
            'host_cost_deadline_5ms', 'host_cost_deadline_20ms', 'missing', 'stale',
            'wrong_generation', 'declared_shift', 'concealed_shift', 'wrong_model',
            'malformed_mask', 'out_of_order', 'mixed_clock')
FALLBACK = {'baseline', 'missing', 'stale', 'wrong_generation', 'declared_shift',
            'wrong_model', 'malformed_mask', 'out_of_order', 'mixed_clock'}
MAX_BONUS = .10
MAX_AGE_NS = 200_000_000


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def stable_output(row):
    """All output fields except enumerated timing and experiment labels/trace.

    Publication, suppression, deadline and budget flags remain part of equality.
    """
    excluded = {'filterMs', 'geometryMs', 'preparationMs', 'componentMs',
                'totalAddedProcessingMs', 'stageMs', 'detectorTrace', 'variant'}
    if isinstance(row, dict):
        return {k: stable_output(v) for k, v in row.items() if k not in excluded}
    if isinstance(row, list):
        return [stable_output(v) for v in row]
    return row


def compatibility(boundary, probabilities, validity):
    """Mean 2-pixel band maximum on geometry; a score, never observed support.

    One sample per image row in [0.58,0.95], on observed segments if available,
    otherwise the legacy polyline. Unknown cells are excluded, not negatives.
    Sampling settings are fixed independently of the reviewed labels.
    """
    height, width = probabilities.shape
    values = []
    segments = boundary.get('observedSegments') or [boundary['points']]
    for y in range(math.ceil(.58*(height-1)), math.floor(.95*(height-1))+1):
        row_values = []
        for segment in segments:
            x = audit.evaluation.x_at(segment, y/(height-1))
            if x is None or not 0 <= x <= 1:
                continue
            center = int(round(x*(width-1)))
            lo, hi = max(0, center-2), min(width, center+3)
            valid = validity[y, lo:hi]
            if valid.any():
                row_values.append(float(probabilities[y, lo:hi][valid].max()))
        if row_values:
            values.append(max(row_values))
    return float(np.mean(values)) if values else 0.


def envelope(row, rgb, probability, policy, start_pts, mapping_id):
    # An artificial monotonic clock for scheduling experiments, explicitly not a
    # recovered phone clock. Original encoded PTS has an independent clock ID.
    relative = Fraction(rgb['ptsValue']) * Fraction(rgb['timeBase']) - start_pts
    source_ns = round(relative * 1_000_000_000)
    captured_ns = 1_000_000_000 + source_ns
    clock_id = 'simulated-replay-clock:' + row['sequenceId']
    exposure = dict(frameId=row['id'], sourceTimeNs=source_ns,
                    sourceClockId='encoded-pts:' + rgb['sourceVideoSha256'],
                    capturedAtNs=captured_ns, clockId=clock_id, clockKnown=True)
    scope = dict(sessionId='offline:' + row['sequenceId'], sessionGeneration=0,
                 cameraId='archived-camera-unidentified', cameraGeneration=0, calibrationGeneration=0)
    geometry = dict(sourceWidth=rgb['decodedWidth'], sourceHeight=rgb['decodedHeight'],
        crop=dict(x=0, y=0, width=rgb['decodedWidth'], height=rgb['decodedHeight']),
        rotationDegrees=0, mirrored=False, analysisWidth=row['width'], analysisHeight=row['height'],
        mappingId=mapping_id, fullScene=True)
    instant = dict(atNs=captured_ns, clockId=clock_id, clockKnown=True)
    context = dict(schemaVersion=1, scope=scope, exposure=exposure, geometry=geometry, now=instant)
    hint = dict(schemaVersion=1, scope=copy.deepcopy(scope), exposure=copy.deepcopy(exposure),
                geometry=copy.deepcopy(geometry), arrival=copy.deepcopy(instant),
                modelIdentity=policy.model_identity,
                provenance=dict(kind='model_inference', sourceId=rgb['sourceFrameId']),
                alignment=dict(mode='exact_exposure'),
                mask=dict(width=row['width'], height=row['height'],
                          probabilities=probability.reshape(-1).tolist(), validity=[True]*probability.size))
    return context, hint


def apply_variant(name, context, hint, probability, host_ms, previous_exposure):
    """Return bounded-map input or an explicit qualification/fault reason."""
    if name in ('baseline', 'missing'):
        return None, 'missing_hint', None
    if name == 'unqualified_paint':
        return probability, 'qualification_bypassed_control', np.ones_like(probability, dtype=bool)
    # Shallow copies of mask arrays avoid millions of unnecessary allocations.
    h = dict(hint, exposure=dict(hint['exposure']), scope=dict(hint['scope']),
             geometry=dict(hint['geometry']), arrival=dict(hint['arrival']), mask=dict(hint['mask']))
    c = dict(context, now=dict(context['now']))
    if name.startswith('host_cost_deadline_'):
        budget = 5_000_000 if name.endswith('5ms') else 20_000_000
        c['now']['atNs'] += budget
        h['arrival']['atNs'] += round(host_ms * 1_000_000)
        if h['arrival']['atNs'] > c['now']['atNs']:
            return None, 'not_arrived_by_simulated_deadline', None
    elif name == 'stale':
        c['now']['atNs'] += 250_000_000
    elif name == 'wrong_generation':
        h['scope']['cameraGeneration'] += 1
    elif name == 'declared_shift':
        h['geometry']['mappingId'] += ':shifted-32px'
    elif name == 'concealed_shift':
        shifted = np.zeros_like(probability)
        shifted[:, 32:] = probability[:, :-32]
        h['mask']['probabilities'] = shifted.reshape(-1).tolist()
    elif name == 'uniform_control':
        h['provenance'] = dict(kind='synthetic_fixture', sourceId='spatial-mean-control:' + context['exposure']['frameId'])
        h['mask']['probabilities'] = [float(probability.mean())] * probability.size
    elif name == 'wrong_model':
        h['modelIdentity'] = dict(h['modelIdentity'], revision='wrong-revision')
    elif name == 'malformed_mask':
        h['mask']['width'] += 1
    elif name == 'out_of_order':
        if previous_exposure is None:
            return None, 'missing_previous_exposure', None
        h['exposure'] = previous_exposure
    elif name == 'mixed_clock':
        h['arrival']['clockId'] += ':foreign'
    elif name != 'qualified_paint':
        raise ValueError('Unknown experiment arm: ' + name)
    policy = hints.QualificationPolicy(hint['modelIdentity']['modelId'], hint['modelIdentity']['revision'],
                                       probability.shape[1], probability.shape[0], MAX_AGE_NS)
    result = hints.qualify(h, c, policy)
    if not result.accepted:
        return None, result.reason, None
    values = np.asarray(result.hint.probabilities).reshape(probability.shape)
    valid = np.asarray(result.hint.validity, dtype=bool).reshape(probability.shape)
    return values, result.reason, valid


def bind_probabilities(rows, probability_path, checkpoint, detector):
    directory = probability_path.parent
    summary = audit.read_json(directory/'summary.json')
    source = Path(summary['inputManifest'])
    audit.require(audit.sha(source) == summary['inputManifestSha256'], 'Inference source manifest hash mismatch')
    rgb_rows = video.load_bound_manifest(source)
    raw = audit.read_json(probability_path)
    audit.require(raw.get('schemaVersion') == 1, 'Invalid probability manifest schema')
    probabilities = audit.unique(raw['frames'], 'probability')
    rgb = audit.unique(rgb_rows, 'RGB')
    audit.require(list(probabilities) == list(rgb) == [r['id'] for r in rows], 'Probability/RGB/replay targets differ')
    audit.require(audit.sha(checkpoint) == summary['checkpointSha256'], 'Checkpoint changed')
    audit.require(audit.sha(detector) == summary['detectorSha256'], 'Frozen detector changed')
    config_hash = video.canonical_sha(summary['config'])
    audit.require(config_hash == summary['configSha256'], 'Inference config changed')
    for row in rows:
        p, r = probabilities[row['id']], rgb[row['id']]
        for key in ('sequenceId', 'time', 'split', 'width', 'height'):
            audit.require(p[key] == r[key] == row[key], 'Probability target mismatch: ' + key)
        for key in ('checkpointSha256', 'detectorSha256', 'configSha256'):
            audit.require(p[key] == summary[key], 'Probability model mismatch: ' + key)
        for key in ('rgbSha256', 'graySha256', 'sourceVideoSha256', 'ptsValue', 'timeBase'):
            audit.require(p[key] == r[key], 'Probability image mismatch: ' + key)
        audit.require(p['graySha256'] == row['inputSha256'], 'Probability/native exposure mismatch')
        audit.require(p.get('targetOnly') is True and p.get('usesFutureFrames') is False,
                      'Current-frame-only model provenance required')
        audit.require(audit.sha(p['probabilityPath']) == p['probabilitySha256'], 'Probability bytes changed')
        audit.require(audit.review.finite(p['warmedHostInferenceMilliseconds']) and p['warmedHostInferenceMilliseconds'] >= 0,
                      'Invalid host inference duration')
    return probabilities, rgb, summary


def execute_replay(manifest, output, reuse=None):
    command = [sys.executable, str(ROOT/'scripts/lanes/replay_recorded_pipeline.py'),
               '--manifest', str(manifest), '--output-dir', str(output), '--preview-mode', '--variant', output.name]
    if reuse:
        command += ['--reuse-build-dir', str(reuse)]
    with output.with_suffix('.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    return audit.load_replay(output)[0]


def require_unguided_source(frames):
    audit.require(all(not any(key in row for key in ('semanticScoreAdjustments', 'semanticSourceInputSha256'))
                      for row in frames), 'Baseline source already contains semantic guidance')


def run(args):
    audit.require(not args.output_dir.exists(), 'Output exists; choose a new experiment directory')
    rows, metadata, replay_hashes = audit.load_replay(args.replay_dir)
    for key in ('useSearchBands', 'groupFragments', 'fragmentTracking', 'retainTentativeIdentity', 'jointSelection'):
        audit.require(not metadata.get(key), 'This experiment requires the unchanged baseline configuration')
    audit.require(metadata.get('previewMode') is True, 'Preview baseline required')
    original = audit.read_json(metadata['manifest'])
    require_unguided_source(original['frames'])
    require_unguided_source(audit.read_json(args.replay_dir/'input.normalized.json')['frames'])
    probs, rgb, inference = bind_probabilities(rows, args.probabilities, args.checkpoint, args.detector)
    settings = audit.read_json(args.labels) if args.labels else dict(frames=[],
        qualification='Unlabelled archived frames: output/fault diagnostics only; no accuracy or unsupported-duration estimate.')
    labels = audit.unique(settings['frames'], 'review')
    byid = audit.unique(rows, 'baseline')
    audit.require(set(labels) <= set(byid), 'Missing reviewed exposure')
    if args.labels:
        audit.require(labels, 'A supplied review file must contain reviewed exposures')
    for fid, label in labels.items():
        audit.review.bind_label(label, byid[fid])
    negative = audit.read_json(args.negative_intervals) if args.negative_intervals else None
    if negative:
        audit.dense_negative(rows, negative)  # Validate complete interval before any run.
    out = args.output_dir.resolve()
    out.mkdir(parents=True)
    sources = out/'sources'
    sources.mkdir()
    for source in (Path(__file__), Path(hints.__file__), Path(audit.__file__), Path(video.__file__),
                   Path(audit.review.__file__), Path(audit.evaluation.__file__)):
        shutil.copy2(source, sources/source.name)
    protocol = dict(schemaVersion=1, status='development_experiment_not_acceptance', variants=list(VARIANTS),
        maxBonus=MAX_BONUS, maxCaptureAgeNs=MAX_AGE_NS, spatialShiftPixels=32,
        scoring='Mean per-row 2px band maximum, Y .58..95, observed segments or legacy polyline; bonus=.1*score.',
        nativeSemantics='Scores applied after native eligibility gates; existing stateful selection, margin, dwell and pair checks execute unchanged.',
        schedule='Synthetic replay clock from relative encoded PTS; zero-latency ideal or measured host inference costs against hypothetical 5/20ms decision budgets. No phone clock recovered; no waiting or old-frame rerun.',
        faultScope='Declared faults must fall back. Concealed pixel shifts keep false metadata and intentionally demonstrate that identity validation cannot detect misdeclared spatial alignment.',
        qualification=settings['qualification'],
        unavailableArms={'road_only': 'No trained road-area output in run-002', 'combined_road_paint': 'No road-area output',
                         'reviewed_dense_mask': 'Sparse paint spans are not a dense mask'},
        provenance=dict(replay_hashes, probabilityManifestSha256=audit.sha(args.probabilities),
                        inferenceSummarySha256=audit.sha(args.probabilities.parent/'summary.json'),
                        labelsSha256=audit.sha(args.labels) if args.labels else None,
                        negativeLabelsSha256=audit.sha(args.negative_intervals) if args.negative_intervals else None,
                        checkpointSha256=audit.sha(args.checkpoint), detectorSha256=audit.sha(args.detector)),
        sourceHashes={p.name: audit.sha(p) for p in sorted(sources.iterdir())},
        selection='Fixed defaults; no threshold/head/checkpoint fitting on this footage. Previously exposed development data, not a blind preregistration.')
    write_json(out/'protocol.json', protocol)  # Saved before scoring/execution.
    manifests = {name: dict(schemaVersion=1, frames=[]) for name in VARIANTS}
    counts = {name: Counter() for name in VARIANTS}
    frame_diagnostics = []
    source_frames = audit.unique(original['frames'], 'original')
    starts, previous, vectors = {}, {}, []
    for row in rows:
        p, source = probs[row['id']], rgb[row['id']]
        probability = np.load(p['probabilityPath'], allow_pickle=False)
        audit.require(probability.shape == (row['height'], row['width']) and np.isfinite(probability).all()
                      and probability.min() >= 0 and probability.max() <= 1, 'Malformed model probability array')
        policy = hints.QualificationPolicy('a2d2-visible-paint-run-002', inference['checkpointSha256'],
                                          row['width'], row['height'], MAX_AGE_NS)
        seq = row['sequenceId']
        first = seq not in starts
        starts.setdefault(seq, Fraction(source['ptsValue'])*Fraction(source['timeBase']))
        context, hint = envelope(row, source, probability, policy, starts[seq], 'verified-upright-bilinear-analysis-v1')
        if first:
            # Full-resolution genuine model outputs, plus bad generation, for
            # independent Swift/Kotlin contract parity using the same values.
            vectors.append(dict(id=row['id']+':valid', context=context, hint=hint, expectedReason='qualified'))
            bad = dict(hint, scope=dict(hint['scope'], cameraGeneration=1))
            vectors.append(dict(id=row['id']+':generation', context=context, hint=bad, expectedReason='scope_mismatch'))
        diag = dict(id=row['id'], inputSha256=row['inputSha256'], probabilitySha256=p['probabilitySha256'], variants={})
        for name in VARIANTS:
            values, reason, valid = apply_variant(name, context, hint, probability,
                                                 p['warmedHostInferenceMilliseconds'], previous.get(seq))
            counts[name][reason] += 1
            scores = [MAX_BONUS*compatibility(b, values, valid) for b in row['rawBoundaries']] if values is not None else None
            frame = dict(source_frames[row['id']])
            if scores is not None:
                frame.update(semanticScoreAdjustments=scores, semanticSourceInputSha256=row['inputSha256'])
            manifests[name]['frames'].append(frame)
            diag['variants'][name] = dict(reason=reason, scoreAdjustments=scores)
        frame_diagnostics.append(diag)
        previous[seq] = hint['exposure']
    for name, manifest in manifests.items():
        write_json(out/(name+'.input.json'), manifest)
    policy_json = dict(schemaVersion=1, modelIdentity=policy.model_identity, maskWidth=policy.mask_width,
                       maskHeight=policy.mask_height, maxCaptureAgeNs=policy.max_capture_age_ns)
    write_json(out/'native-vectors.json', dict(schemaVersion=1, policy=policy_json, qualificationCases=vectors,
                                               cacheSequences=[], clockCases=[]))
    write_json(out/'qualification.json', dict(schemaVersion=1, frames=frame_diagnostics))
    results, baseline = {}, None
    for name in VARIANTS:
        native = execute_replay(out/(name+'.input.json'), out/name, out/'baseline' if baseline is not None else None)
        if baseline is None:
            baseline = native
        for old, new, reference in zip(rows, native, baseline):
            audit.require(new['id'] == old['id'] and new['rawBoundaries'] == old['rawBoundaries'], 'Semantic experiment changed extraction/tracking')
            audit.require(new['lanePresentation']['items'] == old['lanePresentation']['items'], 'Semantic experiment changed maturity/identities')
            if name in FALLBACK:
                audit.require(stable_output(new) == stable_output(reference), 'Rejected/missing hint changed native output')
            if name == 'baseline':
                audit.require(stable_output(new) == stable_output(old), 'Default-off native behavior changed')
        nb = audit.unique(native, name)
        scores = [audit.evaluation.score_frame(nb[fid], label, settings) for fid, label in labels.items()]
        results[name] = dict(frames=len(native), qualificationReasons=dict(counts[name]),
            changedSelectionFrames=sum(n['visibleBoundaryIndices'] != b['visibleBoundaryIndices'] for n, b in zip(native, baseline)),
            changedSelectionFrameIDs=[n['id'] for n,b in zip(native,baseline) if n['visibleBoundaryIndices'] != b['visibleBoundaryIndices']],
            changedReviewedSelectionFrames=sum(n['id'] in labels and n['visibleBoundaryIndices'] != b['visibleBoundaryIndices'] for n,b in zip(native,baseline)),
            scoredCandidateCount=sum(d['score'] is not None for n in native for d in n['lanePresentation']['selectionDecisions']),
            labelled=audit.evaluation.aggregate_labelled(scores) if scores else None,
            bySequence={seq: audit.evaluation.aggregate_labelled([s for s in scores if s['sequenceId'] == seq])
                        for seq in sorted({n['sequenceId'] for n in native})},
            denseNegative=audit.dense_negative(native, negative) if negative else None, continuity=audit.evaluation.continuity(native),
            nativeReplaySha256=audit.sha(out/name/'frames.ndjson'),
            extractionTrackingAndMaturityUnchanged=True,
            invalidMissingNativeBaselineEquivalent=True if name in FALLBACK else None)
        write_json(out/'results.partial.json', results)
    report = dict(schemaVersion=1, protocolSha256=audit.sha(out/'protocol.json'), protocol=protocol, results=results,
        nativeVectorCount=len(vectors), decision='DEFER_ADOPTION',
        limitations=['Approximate, sparse development labels; no independent acceptance truth or drive-level confidence intervals.',
            'Only paint-only model exists; road/combined ablations unavailable.',
            'Native selection executes on this host; clocks and deadlines simulated, not production asynchronous scheduling.',
            'No thermal, power, steady-state memory, TSR passage or small-sign acceptance on phones.',
            'A valid contract cannot detect a shifted map whose producer falsely preserves alignment metadata.'])
    write_json(out/'summary.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('replay-dir', 'probabilities', 'checkpoint', 'detector', 'output-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--labels', type=Path, help='Optional bound sparse reviews; omission means no accuracy claims')
    parser.add_argument('--negative-intervals', type=Path, help='Optional bound dense negative intervals')
    args = parser.parse_args()
    try:
        report = run(args)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({name: dict(changedSelectionFrames=r['changedSelectionFrames'], qualificationReasons=r['qualificationReasons'],
                                labelled=r['labelled'], denseNegative=r['denseNegative']) for name, r in report['results'].items()}, indent=2))


if __name__ == '__main__':
    main()
