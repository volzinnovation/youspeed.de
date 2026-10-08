#!/usr/bin/env python3
"""Inventory post-temporal lane-selection opportunities on bound reviewed frames.

This is an offline diagnostic, not a semantic ablation or adoption decision.
Raw replay boundaries are post-temporal hypotheses, not raw detector ridges.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_teacher_labels as review
import evaluate_fragment_replay as evaluation

COMPETITION = {'lower_side_score'}
AMBIGUOUS_SCORE_OR_DWELL = {'challenger_margin_or_dwell'}
HOLDS = {'incumbent_reacquisition_hold'}
GATES = {'not_mature', 'empty_geometry', 'tracked_only', 'confidence', 'support_rows',
         'vertical_span', 'lower_anchor_missing', 'center_exclusion', 'lateral_distance', 'pair_geometry'}
REASONS = COMPETITION | AMBIGUOUS_SCORE_OR_DWELL | HOLDS | GATES | {'selected', 'candidate'}
CATEGORIES = ('visible_match', 'score_competition', 'score_margin_or_temporal_dwell', 'temporal_hold', 'not_mature',
              'other_gate', 'unclassified_scored_candidate', 'candidate_assignment_conflict',
              'no_post_temporal_match')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(rows, kind):
    require(all(isinstance(r.get('id'), str) and r['id'] for r in rows), 'Missing ' + kind + ' ID')
    return review.unique(rows, kind)


def load_replay(directory):
    """Verify the frozen manifest, source snapshots, geometry and original luma bytes."""
    directory = Path(directory)
    metadata = read_json(directory / 'metadata.json')
    manifest_path = directory / 'input.normalized.json'
    manifest = read_json(manifest_path)
    require(metadata.get('schemaVersion') == manifest.get('schemaVersion') == 1, 'Unsupported replay schema')
    require(sha(manifest_path) == metadata.get('normalizedManifestSha256'), 'Normalized manifest hash mismatch')
    original_path = Path(metadata['manifest'])
    if not original_path.is_absolute():
        original_path = directory / original_path
    require(sha(original_path) == metadata.get('manifestSha256'), 'Original manifest hash mismatch')
    original = unique(read_json(original_path)['frames'], 'source manifest')
    require(isinstance(metadata.get('sourceHashes'), dict) and metadata['sourceHashes'], 'Missing frozen source hashes')
    for name, digest in metadata['sourceHashes'].items():
        require(Path(name).name == name, 'Invalid frozen source filename')
        require(sha(directory / 'sources' / name) == digest, 'Frozen source hash mismatch: ' + name)
    rows, replay_hash = evaluation.read_replay(directory / 'frames.ndjson')
    byid = unique(rows, 'replay')
    inputs = unique(manifest['frames'], 'normalized manifest')
    require(list(byid) == list(inputs) == list(original), 'Replay/source frame IDs or ordering differ')
    require(len(rows) == metadata.get('frameCount') and rows, 'Replay frame count mismatch')
    require(manifest.get('variant') == metadata.get('variant'), 'Manifest variant mismatch')
    for option in ('previewMode', 'useSearchBands', 'groupFragments', 'fragmentTracking', 'retainTentativeIdentity', 'jointSelection'):
        require(manifest.get(option) == metadata.get(option), 'Replay option mismatch: ' + option)
    sequence, previous, closed, splits = None, None, set(), {}
    for row in rows:
        frame, source = inputs[row['id']], original[row['id']]
        require(row.get('schemaVersion') == 1 and row.get('variant') == metadata['variant'], 'Replay schema/variant mismatch')
        for key in ('sequenceId', 'time', 'width', 'height', 'decodedWidth', 'decodedHeight'):
            require(key in frame and row.get(key) == frame[key], 'Replay identity mismatch: ' + key)
        require(review.finite(row['time']), 'Nonfinite replay time')
        require(isinstance(row['sequenceId'], str) and row['sequenceId'], 'Missing sequence ID')
        require(source.get('sequenceId', source.get('clipId')) == row['sequenceId'], 'Source sequence mismatch')
        require(source.get('time', source.get('actualVideoSeconds')) == row['time'], 'Source time mismatch')
        for key in ('width', 'height'):
            require(source.get(key) == row[key], 'Source dimension mismatch: ' + key)
        require(source.get('sceneTags', []) == frame.get('sceneTags', []), 'Source scenario metadata mismatch')
        require(isinstance(frame.get('split'), str) and frame['split'] and source.get('split') == frame['split'], 'Source split mismatch')
        if 'split' in row:
            require(row['split'] == frame['split'], 'Replay split mismatch')
        row['split'] = frame['split']  # Enriched only from the hash-bound normalized source.
        row['sceneTags'] = frame.get('sceneTags', [])
        require(row['sequenceId'] not in splits or splits[row['sequenceId']] == row['split'], 'Sequence crosses splits')
        splits[row['sequenceId']] = row['split']
        if row['sequenceId'] != sequence:
            require(row['sequenceId'] not in closed, 'Noncontiguous sequence')
            if sequence is not None:
                closed.add(sequence)
            sequence, previous = row['sequenceId'], None
        require(previous is None or row['time'] > previous, 'Replay times do not increase')
        previous = row['time']
        w, h = row['width'], row['height']
        require(type(w) is int and type(h) is int and 64 <= w <= 384 and 64 <= h <= 216, 'Invalid analysis dimensions')
        gray_path = Path(frame['grayPath'])
        if not gray_path.is_absolute():
            gray_path = directory / gray_path
        digest = sha(gray_path)
        require(gray_path.stat().st_size == w*h and digest == frame.get('graySha256') == row.get('inputSha256'), 'Luma hash/size mismatch')
        require(source.get('graySha256', source.get('rawSha256', source.get('sha256'))) == digest, 'Source luma hash mismatch')
        validate_boundaries(row)
    return rows, metadata, dict(replaySha256=replay_hash, metadataSha256=sha(directory/'metadata.json'),
                                normalizedManifestSha256=sha(manifest_path), sourceManifestSha256=sha(original_path),
                                frozenSourceHashes=metadata['sourceHashes'])


def validate_boundaries(row):
    raw, visible = row['rawBoundaries'], row['confirmedBoundaries']
    for boundary in raw + visible:
        review.validate_geometry(boundary['points'])
        for segment in boundary.get('observedSegments', []):
            review.validate_geometry(segment)
    indices = row['visibleBoundaryIndices']
    require(len(indices) == len(set(indices)) == len(visible) == len(row['visibleIDs']), 'Visible boundary count/identity mismatch')
    require(all(type(i) is int and 0 <= i < len(raw) for i in indices), 'Visible boundary index invalid')
    require(all(raw[i] == boundary for i, boundary in zip(indices, visible)), 'Visible boundary differs from selected raw hypothesis')
    presentation = row['lanePresentation']
    decisions = presentation['selectionDecisions']
    require(len(decisions) == len(raw) and sorted(d['boundaryIndex'] for d in decisions) == list(range(len(raw))), 'Selection decision indices differ from boundaries')
    for d in decisions:
        require(d.get('reason') in REASONS, 'Unknown selection reason')
        require(d.get('score') is None or review.finite(d['score']), 'Invalid selection score')
        require(d.get('side') in ('none', 'left', 'right'), 'Unknown selection side')
        if d['reason'] in COMPETITION | AMBIGUOUS_SCORE_OR_DWELL | HOLDS | {'selected', 'candidate'}:
            require(d.get('score') is not None and d['side'] in ('left', 'right'), 'Scored candidate lacks score/side')
    for i in indices:
        require(next(d for d in decisions if d['boundaryIndex'] == i)['reason'] == 'selected', 'Visible candidate is not selected')


def geometry_edges(boundaries, truth, settings):
    edges = []
    for pi, boundary in enumerate(boundaries):
        for ti, border in enumerate(truth):
            error = evaluation.geometry_error(boundary['points'], border['geometry'], settings['matchingMinimumOverlapY'])
            if error is not None and error <= settings['geometryToleranceX']:
                edges.append((error, pi, ti))
    return sorted(edges)


def one_to_one(edges, blocked_predictions=(), blocked_truth=()):
    """Deterministic distance-first matching, identical policy to existing scorer."""
    used_p, used_t, matches = set(blocked_predictions), set(blocked_truth), []
    for error, pi, ti in sorted(edges):
        if pi not in used_p and ti not in used_t:
            matches.append((error, pi, ti))
            used_p.add(pi)
            used_t.add(ti)
    return matches


def category(decision):
    reason = decision['reason']
    if reason in COMPETITION:
        return 'score_competition'
    if reason in AMBIGUOUS_SCORE_OR_DWELL:
        return 'score_margin_or_temporal_dwell'
    if reason in HOLDS:
        return 'temporal_hold'
    if reason == 'not_mature':
        return 'not_mature'
    if reason in GATES:
        return 'other_gate'
    return 'unclassified_scored_candidate'


def frame_inventory(row, label, settings):
    baseline = evaluation.score_frame(row, label, settings)
    raw, truth = row['rawBoundaries'], label['borders']
    decisions = {d['boundaryIndex']: d for d in row['lanePresentation']['selectionDecisions']}
    edges = geometry_edges(raw, truth, settings)
    matches = {m['truth']: (m['errorX'], row['visibleBoundaryIndices'][m['prediction']], m['truth']) for m in baseline['matches']}
    visible_truth = set(matches)
    used = {m[1] for m in matches.values()}
    # Preserve displayed matches; do not let duplicate candidates create extra recoverable truth.
    for match in one_to_one(edges, used, visible_truth):
        matches[match[2]] = match
    inventory = []
    for ti, border in enumerate(truth):
        possible = [dict(boundaryIndex=pi, errorX=e, reason=decisions[pi]['reason'],
                         side=decisions[pi]['side'], score=decisions[pi]['score']) for e, pi, t in edges if t == ti]
        match = matches.get(ti)
        stage = ('visible_match' if ti in visible_truth else category(decisions[match[1]]) if match else
                 'candidate_assignment_conflict' if possible else 'no_post_temporal_match')
        inventory.append(dict(truthIndex=ti, side=border['side'], stage=stage,
                              assignedBoundaryIndex=match[1] if match else None, matchingHypotheses=possible))
    ignored = set()
    matched_visible = {m['prediction'] for m in baseline['matches']}
    for pi, p in enumerate(row['confirmedBoundaries']):
        if pi in matched_visible:
            continue
        for region in label.get('ignoreGeometry', []):
            error = evaluation.geometry_error(p['points'], region['points'], settings['matchingMinimumOverlapY'])
            if error is not None and error <= region['tolerance']:
                ignored.add(pi)
                break
    wrong = []
    for pi in sorted(set(range(len(row['confirmedBoundaries']))) - matched_visible - ignored):
        raw_index = row['visibleBoundaryIndices'][pi]
        side = decisions[raw_index]['side']
        alternatives = [dict(boundaryIndex=i, truthIndex=ti, errorX=e, reason=decisions[i]['reason'],
                             category=category(decisions[i])) for e, i, ti in edges
                        if i not in row['visibleBoundaryIndices'] and decisions[i]['side'] == side
                        and truth[ti]['side'] == side and ti not in visible_truth and decisions[i]['score'] is not None]
        wrong.append(dict(predictionIndex=pi, boundaryIndex=raw_index, visibleId=row['visibleIDs'][pi], side=side,
                          matchingScoredSameSideAlternatives=alternatives,
                          anyCorrectPostTemporalHypothesis=bool(edges)))
    return dict(id=row['id'], sequenceId=row['sequenceId'], time=row['time'], split=row['split'],
                inputSha256=row['inputSha256'], sceneTags=row['sceneTags'], baseline=baseline,
                truthInventory=inventory, wrongVisibleSelections=wrong)


def aggregate(frames):
    counts = Counter(t['stage'] for f in frames for t in f['truthInventory'])
    # Loose optimistic ceiling: each missed truth with any unused competition hypothesis
    # counts once. Joint geometry, score budget, identity dwell and shared candidates can
    # reduce realizable benefit. These are observed opportunities, never predicted gains.
    possible = sum(t['stage'] != 'visible_match' and any(h['reason'] in COMPETITION for h in t['matchingHypotheses'])
                   for f in frames for t in f['truthInventory'])
    wrong = [w for f in frames for w in f['wrongVisibleSelections']]
    return dict(labelled=evaluation.aggregate_labelled([f['baseline'] for f in frames]),
                truthStages={k: counts[k] for k in CATEGORIES},
                looseOptimisticScoreCompetitionMissCeiling=possible,
                wrongVisibleSelectionCount=len(wrong),
                wrongSelectionsWithScoredSameSideAlternative=sum(bool(w['matchingScoredSameSideAlternatives']) for w in wrong),
                wrongSelectionsWithCompetitionAlternative=sum(any(a['category'] == 'score_competition' for a in w['matchingScoredSameSideAlternatives']) for w in wrong),
                wrongSelectionsWithAnyCorrectPostTemporalHypothesis=sum(w['anyCorrectPostTemporalHypothesis'] for w in wrong))


def dense_negative(rows, labels):
    # Reuse strict interval identity/hash/time binding and gap-capped duration helper.
    rois, bounds = {}, []
    for interval in labels['intervals']:
        lo, hi = review.y_range(interval['evaluationYRange'])
        start, end = interval['startSeconds'], interval['endSeconds']
        require(review.finite(start) and review.finite(end) and start < end, 'Invalid negative interval bounds')
        require(not any(seq == interval['sequenceId'] and start < previous_end and end > previous_start
                        for seq, previous_start, previous_end in bounds), 'Overlapping negative time intervals')
        bounds.append((interval['sequenceId'], start, end))
        for fid in interval['frameIDs']:
            require(fid not in rois, 'Overlapping negative frame IDs')
            rois[fid] = (lo, hi)
    adapted = []
    for row in rows:
        points = []
        if row['id'] in rois:
            lo, hi = rois[row['id']]
            for b in row['confirmedBoundaries']:
                for segment in b.get('observedSegments') or [b['points']]:
                    for a, z in zip(segment, segment[1:]):
                        start, end = max(lo, min(a[1], z[1])), min(hi, max(a[1], z[1]))
                        if start <= end:
                            points.append(dict(point=[.5, (start+end)/2]))
        adapted.append(dict(row, positivePoints=points))
    score = review.negative_scores(adapted, labels)
    return dict(scoredFrames=score['scoredFrames'], framesWithUnsupportedDisplay=score['framesWithCandidatePoints'],
                reviewedSampleDurationSeconds=score['reviewedSampleDurationSeconds'],
                unsupportedVisibleDurationSeconds=score['candidatePositiveDurationSeconds'],
                longestUnsupportedRunSeconds=score['longestPositiveRunSeconds'],
                durationDefinition=score['durationDefinition'], qualification=score['qualification'],
                semantics='A displayed polyline segment intersects the reviewed negative Y region. Segment intersections are not inferred paint pixels.',
                intervals=score['intervals'])


def run(replay_dir, labels_path, negative_path, output):
    require(not output.exists(), 'Output directory exists; choose a new directory')
    rows, metadata, hashes = load_replay(replay_dir)
    byid = unique(rows, 'replay')
    settings = read_json(labels_path)
    require(settings.get('schemaVersion') == 1, 'Unsupported label schema')
    for key in ('geometryToleranceX', 'matchingMinimumOverlapY', 'paintToleranceX', 'paintEndpointToleranceY'):
        require(review.finite(settings.get(key)) and 0 <= settings[key] <= 1, 'Invalid review tolerance: ' + key)
    require(settings['matchingMinimumOverlapY'] > 0, 'Zero matching overlap')
    labels = unique(settings['frames'], 'review')
    require(labels and set(labels) <= set(byid), 'Missing reviewed replay frames')
    frames = []
    for fid, label in labels.items():
        review.bind_label(label, byid[fid])
        require(all(b.get('side') in ('left', 'right') for b in label['borders']), 'Unknown reviewed border side')
        frames.append(frame_inventory(byid[fid], label, settings))
    report = dict(schemaVersion=1, decision='DEFER',
        decisionScope='Semantic selection adoption remains unqualified. This inventory is not proof that no algorithm can help.',
        stageScope='Post-temporal, pre-presentation hypotheses only. No raw extraction or fragment-association trace is available.',
        qualification=settings['qualification'], reviewer=settings['reviewer'],
        matchingPolicy='Existing distance-first one-to-one geometry matching; preserve displayed matches before inventorying remaining hypotheses.',
        settings={k: settings[k] for k in ('geometryToleranceX', 'matchingMinimumOverlapY', 'paintToleranceX', 'paintEndpointToleranceY')},
        provenance=dict(hashes, labelsSha256=sha(labels_path),
            auditSourceHashes={p.name: sha(p) for p in (Path(__file__), Path(review.__file__), Path(evaluation.__file__))}),
        replayConfiguration={k: v for k, v in metadata.items() if k not in ('sourceHashes', 'manifest')},
        replayFrames=len(rows), unlabelledFramesExcludedFromAccuracy=len(rows)-len(labels),
        overall=aggregate(frames),
        bySequence={seq: aggregate([f for f in frames if f['sequenceId'] == seq]) for seq in sorted({f['sequenceId'] for f in frames})},
        bySplit={split: aggregate([f for f in frames if f['split'] == split]) for split in sorted({f['split'] for f in frames})},
        opportunityCeilingQualification='Loose observed-competition ceiling only; correlated approximate reviews, one-to-one capacity, bounded scores, joint geometry and dwell prevent treating it as an achievable gain. No data-driven threshold or policy tuning performed.',
        incompleteAcceptance=['No raw ridge/pre-association diagnostics; absent hypotheses cannot be called extraction failures.',
            'No reviewed-mask ablation, actual semantic reranking, invalid-hint replay equivalence or frozen value gate.',
            'No independent drive-separated acceptance truth or drive-level uncertainty estimate.',
            'Sparse keyframes do not establish unsupported duration; dense negative duration is separate.',
            'The challenger_margin_or_dwell trace cannot distinguish score margin from mandatory dwell; excluded from the score-only ceiling.',
            'Scored temporal holds remain temporal constraints. Same-frame semantics do not provide new temporal confirmations.'],
        frames=frames)
    if negative_path:
        report['denseNegative'] = dense_negative(rows, read_json(negative_path))
        report['provenance']['negativeLabelsSha256'] = sha(negative_path)
    output.mkdir(parents=True)
    write_json(output/'audit.json', report)
    short = dict(report)
    short.pop('frames')
    write_json(output/'summary.json', short)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay-dir', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--negative-intervals', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.replay_dir, args.labels, args.negative_intervals, args.output_dir)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(dict(decision=result['decision'], overall=result['overall'], denseNegative=result.get('denseNegative')), indent=2))


if __name__ == '__main__':
    main()
