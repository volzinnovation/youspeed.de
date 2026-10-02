#!/usr/bin/env python3
"""Audit logged lane continuity during a named recording; no pixel/UTC equivalence assumed.

Displacement is observed screen motion, not an accuracy or motion-compensated jitter score.
Logs are sampled outputs; missing records are not invented camera frames.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
from audit_lane_runtime import summarize, quantiles


def utc_seconds(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def at(points, y):
    for a, b in zip(points, points[1:]):
        if a[1] <= y <= b[1] and b[1] > a[1]:
            return a[0] + (b[0]-a[0])*(y-a[1])/(b[1]-a[1])
    return None


def visible(d):
    p = d.get('lanePresentation', {})
    bs = d.get('boundaries', [])
    indices = set(p.get('visibleBoundaryIndices', []))
    if not d.get('overlayPublished', False):
        return {}
    return {i['trackId']: bs[i['boundaryIndex']] for i in p.get('items', [])
            if i.get('boundaryIndex') in indices and 0 <= i['boundaryIndex'] < len(bs)}


def continuity(rows):
    steps, gaps, jumps, changes = [], [], [], []
    lifetimes = defaultdict(list)
    counts = Counter()
    provenance, cues, reasons, temporal = Counter(), Counter(), Counter(), Counter()
    for _, d in rows:
        t = d['sourceTimestampSeconds']
        v = visible(d)
        counts[len(v)] += 1
        for key, b in v.items():
            lifetimes[key].append(t)
            provenance[b.get('provenance')] += 1
            cues[b.get('cue')] += 1
        reasons[str(d.get('lanePresentation', {}).get('reason'))] += 1
        temporal[str(d.get('temporalResetReason'))] += 1
    for (_, a), (_, b) in zip(rows, rows[1:]):
        dt = b['sourceTimestampSeconds']-a['sourceTimestampSeconds']
        gaps.append(dt)
        av, bv = visible(a), visible(b)
        changes.append((bool(av) != bool(bv), set(av) != set(bv)))
        if not 0 < dt <= .75:
            continue
        for key in av.keys() & bv.keys():
            pa, pb = av[key]['points'], bv[key]['points']
            top, bottom = max(pa[0][1], pb[0][1]), min(pa[-1][1], pb[-1][1])
            if bottom-top < .12:
                continue
            xs = [abs(at(pa, top+(bottom-top)*i/4)-at(pb, top+(bottom-top)*i/4)) for i in range(5)]
            pixels = max(xs)*(b.get('analysisWidth', 288)-1)
            steps.append(pixels)
            if pixels > 5:
                jumps.append(dict(frameId=b['frameId'], capturedAtSeconds=b['capturedAtSeconds'],
                                  previousFrameId=a['frameId'], trackId=key, dt=dt,
                                  maxDisplacementPixels=pixels, cue=bv[key]['cue'],
                                  speedMps=b.get('laneMotionHint', {}).get('speedMetersPerSecond')))
    return dict(frames=len(rows), visibleCountHistogram=dict(counts), visibleProvenance=dict(provenance),
                visibleCues=dict(cues), presentationReasons=dict(reasons), temporalResetReasons=dict(temporal),
                exposureGapSeconds=quantiles(gaps), gapsOver750ms=sum(t>.75 for t in gaps),
                availabilityTransitions=sum(x[0] for x in changes), identitySetTransitions=sum(x[1] for x in changes),
                uniqueVisibleTrackIds=len(lifetimes), visibleTrackSpanSeconds=quantiles([v[-1]-v[0] for v in lifetimes.values()]),
                sameIdSteps=len(steps), sameIdMaxDisplacementPixels=quantiles(steps),
                sameIdStepsOver5Pixels=len(jumps), largestSteps=sorted(jumps,key=lambda x:-x['maxDisplacementPixels'])[:20])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime', type=Path, required=True)
    p.add_argument('--matches', type=Path, required=True)
    p.add_argument('--video-name', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists(): p.error('Output exists')
    raw, malformed = [], 0
    for line in a.runtime.open():
        try: raw.append(json.loads(line))
        except ValueError: malformed += 1
    anchors = [json.loads(r['evidence']) for r in raw if r.get('event')=='tsr_path_recording_v1']
    anchors = [r for r in anchors if r.get('videoFile')==a.video_name]
    starts, stops = [x for x in anchors if x['event']=='start'], [x for x in anchors if x['event']=='stop']
    if len(starts)!=1 or len(stops)!=1: p.error('Need exactly one recorded start and stop')
    start, stop = starts[0]['observedAtSeconds'], stops[0]['observedAtSeconds']
    evidence = {}
    duplicate = 0
    for r in raw:
        if r.get('event') != 'tsr_path_evidence_v1': continue
        d=json.loads(r['evidence'])
        if start <= d['capturedAtSeconds'] <= stop:
            duplicate += d['frameId'] in evidence
            evidence[d['frameId']] = (r['timestampUTC'], d)
    rows = sorted(evidence.values(), key=lambda x:x[1]['sourceTimestampSeconds'])
    inferences = [r for r in raw if r.get('event')=='traffic_sign_inference' and start<=utc_seconds(r['timestampUTC'])<=stop]
    moving = [x for x in rows if x[1].get('laneMotionHint', {}).get('speedMetersPerSecond', 0)>1]
    overlay = [r for r in raw if r.get('event')=='lane_overlay_presentation' and start<=utc_seconds(r['timestampUTC'])<=stop]
    matches = [json.loads(l) for l in a.matches.open()]
    matches = [r for r in matches if start<=utc_seconds(r['timestampUTC'])<=stop]
    offsets = [r['observedAtSeconds']-r['recordedDurationSeconds'] for r in anchors if r['event']=='progress' and r['recordedDurationSeconds']>0]
    hint = [d['laneMotionHint'] for _,d in rows if d.get('laneMotionHint',{}).get('used')]
    report = dict(schemaVersion=1, videoName=a.video_name, anchors=dict(start=starts[0],stop=stops[0],
                  progressCount=len(offsets),estimatedUtcMinusPtsSeconds=quantiles(offsets),
                  offsetSpreadSeconds=max(offsets)-min(offsets)),
                  inputHashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [a.runtime,a.matches]},
                  malformedRuntimeRows=malformed, duplicateFrameIds=duplicate,
                  recording=summarize(rows,inferences), moving=summarize(moving,inferences),
                  continuity=continuity(rows), movingContinuity=continuity(moving),
                  hint=dict(used=len(hint),headingAccuracyOver20Degrees=sum(h.get('courseAccuracyDegrees',0)>20 for h in hint),
                            ageSeconds=quantiles([h.get('sourceAgeSeconds') for h in hint])),
                  overlayEvents=dict(count=len(overlay),modes=dict(Counter(r['mode'] for r in overlay)),
                    reasons=dict(Counter(r['reason'] for r in overlay)),
                    modeTransitions=sum(a['mode']!=b['mode'] for a,b in zip(overlay,overlay[1:])),
                    observedReferenceTransitions=sum({a['mode'],b['mode']}=={'observed','calibration_reference'} for a,b in zip(overlay,overlay[1:]))),
                  roadMatch=dict(rows=len(matches),statuses=dict(Counter(r['status'] for r in matches)),
                    stable=sum(r.get('result',{}).get('matchedWayStable',False) for r in matches),
                    uniqueWays=len(set(r.get('way_id') for r in matches)),
                    queryMs=quantiles([r.get('query_ms') for r in matches])),
                  qualification='Logged evaluated exposures during recording callbacks. Screen displacement includes true ego-motion; identity spans and gaps refer to sampled logs. Callback UTC/video offsets are estimates, not a verified exposure mapping. Moving subset uses >1 m/s and is not necessarily contiguous.')
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['inputHashes','continuity','movingContinuity']},indent=2))


if __name__=='__main__': main()
