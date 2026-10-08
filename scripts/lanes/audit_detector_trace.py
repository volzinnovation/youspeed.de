#!/usr/bin/env python3
"""Audit native detector trace against hash-bound approximate development labels.

No detector is reimplemented here. Row-neighborhood counts are diagnostics, not
lane reconstructions, accuracy estimates, or evidence that reranking can recover
an absent hypothesis. Existing sparse geometry tolerances remain unchanged.
"""
import argparse
from collections import Counter
import json
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_selection_opportunity as selection
import evaluate_fragment_replay as evaluation

require = selection.require


def geometry_match(points, truth, settings):
    if len(points) < 2:
        return None
    error = evaluation.geometry_error(points, truth, settings['matchingMinimumOverlapY'])
    return error if error is not None and error <= settings['geometryToleranceX'] else None


def validate_trace(row):
    events = row.get('detectorTrace')
    require(isinstance(events, list) and events, 'Missing detector trace')
    configuration = [e for e in events if e.get('stage') == 'configuration']
    completion = [e for e in events if e.get('stage') == 'completion']
    require(len(configuration) == len(completion) == 1 and completion[0]['status'] == 'complete', 'Incomplete detector trace')
    config = configuration[0]
    require(config['schemaVersion'] == 1 and config['width'] == row['width'] and config['height'] == row['height'], 'Trace dimensions/schema mismatch')
    rows = [e for e in events if e['stage'] == 'row']
    require([e['row'] for e in rows] == list(range(len(config['samplingRows']))), 'Missing/duplicate sampling rows')
    samples, kept = {}, set()
    for e, pixel_y in zip(rows, config['samplingRows']):
        require(abs(e['y']-pixel_y/(row['height']-1)) < 1e-12, 'Trace sampling coordinate mismatch')
        before, after = e['preCap'], e['postCap']
        require(len(after) <= 12, 'Post-cap candidates exceed detector cap')
        before_ids = set()
        for sample in before:
            sid = sample['sampleID']
            require(type(sid) is int and sid not in samples, 'Duplicate/invalid sample ID')
            x, y = sample['point']
            require(all(selection.review.finite(v) for v in (x,y,sample['strength'])) and 0 <= x <= 1 and y == e['y'] and sample['strength'] > 0, 'Invalid trace sample')
            require(sample['row'] == e['row'] and sid == e['row']*row['width']+int(x*(row['width']-1)+.5), 'Trace sample identity mismatch')
            require(sample['cue'] in ('paint','edge'), 'Unknown sample cue')
            samples[sid] = sample
            before_ids.add(sid)
        require(len({s['sampleID'] for s in after}) == len(after), 'Duplicate post-cap sample')
        for sample in after:
            require(sample['sampleID'] in before_ids and samples[sample['sampleID']] == sample, 'Post-cap sample differs from observed sample')
            kept.add(sample['sampleID'])
    associations = [e for e in events if e['stage'] == 'association']
    require(len(associations) == len(kept) and {e['sampleID'] for e in associations} == kept, 'Missing/duplicate association disposition')
    track_samples = {}
    for event in associations:
        sid = event['sampleID']
        require(event['row'] == samples[sid]['row'], 'Association row mismatch')
        outcome = event['outcome']
        require(outcome in ('created','assigned','active_track_capacity'), 'Unknown association outcome')
        if outcome == 'created':
            require(event['trackID'] == sid and sid not in track_samples, 'Invalid track creation')
            track_samples[sid] = [sid]
        elif outcome == 'assigned':
            require(event['trackID'] in track_samples, 'Association references absent track')
            track_samples[event['trackID']].append(sid)
    tracks = [e for e in events if e['stage'] == 'track']
    require(len(tracks) == len(track_samples) and {e['trackID'] for e in tracks} == set(track_samples), 'Missing/duplicate completed track')
    for track in tracks:
        require(track['outcome'] in ('accepted','track_support','track_span','confidence'), 'Unknown track outcome')
        require([s['sampleID'] for s in track['samples']] == track_samples[track['trackID']], 'Completed track association mismatch')
        require(all(s == samples[s['sampleID']] for s in track['samples']), 'Completed track changed observed samples')
    fresh = [e for e in events if e['stage'] == 'fresh_hypothesis']
    retained = [e['outputIndex'] for e in fresh if e['outputIndex'] is not None]
    require(sorted(retained) == list(range(len(retained))) and len(retained) <= 6, 'Invalid fresh output indices')
    for e in fresh:
        selection.review.validate_geometry(e['points'])
        require(e['origin'] in ('measured','fragment') and e['cue'] in ('paint','edge'), 'Unknown fresh origin/cue')
    return dict(rows=rows, tracks=tracks, fresh=fresh, associations=associations)


def border_diagnostic(trace, border, settings):
    truth = border['geometry']
    fresh = [dict(origin=e['origin'], outputIndex=e['outputIndex'], confidence=e['confidence'], cue=e['cue'],
                  supportRows=e['supportRows'], errorX=error)
             for e in trace['fresh'] if (error := geometry_match(e['points'], truth, settings)) is not None]
    tracks = [dict(trackID=e['trackID'], outcome=e['outcome'], sampleCount=len(e['samples']),
                   errorX=error, points=[s['point'] for s in reversed(e['samples'])])
              for e in trace['tracks']
              if (error := geometry_match([s['point'] for s in reversed(e['samples'])], truth, settings)) is not None]
    support = []
    for row in trace['rows']:
        y = row['y']
        if not truth[0][1] <= y <= truth[-1][1]:
            continue
        target_x = evaluation.x_at(truth, y)
        entry = dict(row=row['row'], y=y, targetX=target_x,
                     withinReviewedPaintInterval=any(lo <= y <= hi for lo, hi in border['paintedYIntervals']))
        for key in ('preCap','postCap'):
            nearby = [s for s in row[key] if abs(s['point'][0]-target_x) <= settings['geometryToleranceX']]
            entry[key] = [dict(sampleID=s['sampleID'], cue=s['cue'], errorX=abs(s['point'][0]-target_x)) for s in nearby]
        support.append(entry)
    before = sum(bool(r['preCap']) for r in support)
    after = sum(bool(r['postCap']) for r in support)
    lost = sum(bool(r['preCap']) and not r['postCap'] for r in support)
    nearby_ids = {s['sampleID'] for r in support for s in r['postCap']}
    dropped = [e['sampleID'] for e in trace['associations'] if e['outcome'] == 'active_track_capacity' and e['sampleID'] in nearby_ids]
    touching = []
    for track in trace['tracks']:
        ids = [s['sampleID'] for s in track['samples'] if s['sampleID'] in nearby_ids]
        if ids:
            points = [s['point'] for s in reversed(track['samples'])]
            error = evaluation.geometry_error(points, truth, settings['matchingMinimumOverlapY']) if len(points) >= 2 else None
            touching.append(dict(trackID=track['trackID'], outcome=track['outcome'], nearbySampleIDs=ids,
                                 nearbySampleCount=len(ids), totalSampleCount=len(points),
                                 points=points, errorX=error))
    if any(e['outputIndex'] is not None for e in fresh):
        stage = 'fresh_match_lost_or_changed_in_temporal_fusion'
    elif fresh:
        stage = 'fresh_output_capacity'
    elif tracks:
        stage = 'associated_track_rejected'
    elif before == 0:
        stage = 'no_nearby_post_nms_stripes'
    elif after == 0:
        stage = 'nearby_stripes_removed_by_row_cap'
    else:
        stage = 'nearby_stripes_without_matching_associated_geometry'
    return dict(stage=stage, matchingFreshHypotheses=fresh, matchingAssociatedTracks=tracks,
                rowsInReviewedGeometry=len(support), rowsWithNearbyPreCapStripes=before,
                rowsWithNearbyPostCapStripes=after, rowsLosingAllNearbyStripesAtCap=lost,
                nearbySamplesDroppedAtActiveTrackCapacity=dropped, tracksTouchingNearbySamples=touching, rowSupport=support)


# Enumerated telemetry exclusions: never remove arbitrary keys whose name contains
# "time", because source timestamps, evidence ages and ordering are behavior.
TIMING_KEYS = frozenset(('filterMs','geometryMs','preparationMs','componentMs','totalAddedProcessingMs','stageMs'))


def without_trace_and_timing(value):
    if isinstance(value, dict):
        return {k: without_trace_and_timing(v) for k, v in value.items() if k not in TIMING_KEYS and k != 'detectorTrace'}
    if isinstance(value, list):
        return [without_trace_and_timing(v) for v in value]
    return value


def run(traced_dir, untraced_dir, labels_path, output_dir):
    require(not output_dir.exists(), 'Output already exists')
    traced, metadata, hashes = selection.load_replay(traced_dir)
    untraced, control_metadata, control_hashes = selection.load_replay(untraced_dir)
    require(metadata.get('detectorTrace') is True and control_metadata.get('detectorTrace') is False, 'Expected trace-on and trace-off replays')
    require(metadata['sourceHashes'] == control_metadata['sourceHashes'], 'Trace/control frozen sources differ')
    require(metadata['manifestSha256'] == control_metadata['manifestSha256'], 'Trace/control source manifest differs')
    require({k:v for k,v in metadata.items() if k not in ('detectorTrace','normalizedManifestSha256')} ==
            {k:v for k,v in control_metadata.items() if k not in ('detectorTrace','normalizedManifestSha256')}, 'Trace/control configuration differs')
    require(without_trace_and_timing(traced) == without_trace_and_timing(untraced), 'Trace changed non-timing pipeline output')
    validated = {r['id']:validate_trace(r) for r in traced}
    byid = selection.unique(traced, 'trace replay')
    labels = selection.read_json(labels_path)
    for key in ('geometryToleranceX','matchingMinimumOverlapY','paintToleranceX','paintEndpointToleranceY'):
        require(selection.review.finite(labels.get(key)) and 0 <= labels[key] <= 1, 'Invalid matching tolerance')
    require(labels['matchingMinimumOverlapY'] > 0, 'Zero matching overlap')
    reviewed = selection.unique(labels['frames'], 'review')
    require(reviewed and set(reviewed) <= set(byid), 'Missing reviewed frames')
    frames = []
    for fid, label in reviewed.items():
        row = byid[fid]
        selection.review.bind_label(label,row)
        inventory = selection.frame_inventory(row,label,labels)
        for item in inventory['truthInventory']:
            if item['stage'] == 'no_post_temporal_match':
                item['detectorDiagnostic'] = border_diagnostic(validated[fid],label['borders'][item['truthIndex']],labels)
        frames.append(inventory)
    diagnosed = [dict(id=f['id'], sequenceId=f['sequenceId'], inputSha256=f['inputSha256'], **t)
                 for f in frames for t in f['truthInventory'] if 'detectorDiagnostic' in t]
    report = dict(schemaVersion=1, decision='DEFER', replayFrames=len(traced), reviewedFrames=len(frames),
        traceOnOffNonTimingEquivalent=True, overall=selection.aggregate(frames),
        missingHypothesisStages=dict(Counter(t['detectorDiagnostic']['stage'] for t in diagnosed)),
        qualification=labels['qualification'], matchingScope='Existing approximate geometry matching; row neighborhoods are diagnostic only, not reconstructed hypotheses or causal recovery estimates.',
        limitations=['Pre-cap means after ridge/edge thresholding and nonmaximum suppression; no claim about sub-threshold pixels.',
                     'Fragment join rejection reasons remain aggregate; baseline trace diagnoses original greedy association and fresh-track gates.',
                     'A geometry match can overlap only part of a reviewed border. Counts are not dense paint accuracy.',
                     'Same-drive correlated approximate reviews do not qualify semantic adoption or tune thresholds.'],
        provenance=dict(trace=hashes, control=control_hashes, labelsSha256=selection.sha(labels_path),
                        auditSourceHashes={p.name:selection.sha(p) for p in (Path(__file__),Path(selection.__file__),Path(selection.review.__file__),Path(evaluation.__file__))}),
        diagnosedMissingHypotheses=diagnosed)
    output_dir.mkdir(parents=True)
    sources = output_dir/'sources'
    sources.mkdir()
    for source in report['provenance']['auditSourceHashes']:
        shutil.copy2(Path(__file__).parent/source,sources/source)
    selection.write_json(output_dir/'audit.json',report)
    summary = dict(report)
    summary.pop('diagnosedMissingHypotheses')
    selection.write_json(output_dir/'summary.json',summary)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--traced-replay',type=Path,required=True)
    parser.add_argument('--untraced-replay',type=Path,required=True)
    parser.add_argument('--labels',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    try:
        report=run(args.traced_replay,args.untraced_replay,args.labels,args.output_dir)
    except (ValueError,KeyError,OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({k:report[k] for k in ('decision','replayFrames','reviewedFrames','traceOnOffNonTimingEquivalent','missingHypothesisStages')},indent=2))


if __name__ == '__main__':
    main()
