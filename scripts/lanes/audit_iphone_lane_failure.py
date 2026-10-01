#!/usr/bin/env python3
"""Summarize saved iPhone lane diagnostics without changing recordings or logs."""
import argparse
from collections import Counter, defaultdict
import json
import statistics
from pathlib import Path


def quantiles(values):
    values=sorted(values)
    if not values:return None
    return {'min':values[0],'median':statistics.median(values),'p95':values[int(.95*(len(values)-1))],'max':values[-1]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('log',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();groups=defaultdict(list);invalid=Counter()
    keys=['lane_preview_frame_v1','lane_presentation_v1','tsr_path_evidence_v1','capture_configuration','tsr_path_recording_v1']
    for line in args.log.open():
        for key in keys:
            if key+'=' in line:
                try:groups[key].append({'loggedAt':line.split()[0].replace('timestamp=','',1),'data':json.loads(line.split(key+'=',1)[1])})
                except ValueError:invalid[key]+=1
    lanes=[r['data'] for r in groups['lane_preview_frame_v1']]
    presentation=groups['lane_presentation_v1'];timeline=[]
    for row in presentation:
        r=row['data']
        if not timeline or timeline[-1]['reason']!=r['reason']:
            timeline.append({'loggedAtUtc':row['loggedAt'],'reason':r['reason'],'calibrationRevision':r.get('visualCalibration',{}).get('revision')})
    simultaneous=[]
    if lanes:
        start,end=lanes[0]['capturedAtSeconds'],lanes[-1]['capturedAtSeconds']
        simultaneous=[r['data'] for r in groups['tsr_path_evidence_v1'] if start<=r['data']['capturedAtSeconds']<=end]
    calibrated=[r for r in simultaneous if 'calibration' in r]
    pairs=[(a,b) for a,b in zip(calibrated,calibrated[1:]) if a['geometryId']==b['geometryId'] and a['calibration']['revision']==b['calibration']['revision']]
    report={'schemaVersion':1,'source':str(args.log),'eventCounts':{k:len(v) for k,v in groups.items()},'invalidJson':dict(invalid),
        'preview':{'frames':len(lanes),'budgetFailures':sum(r['geometryBudgetExceeded'] for r in lanes),
            'framesWithVisibleBoundaries':sum(bool(r['boundaries']) for r in lanes),
            'preparationMs':quantiles([r['preparationMs'] for r in lanes]),
            'exposureIntervalSeconds':quantiles([b['sourceTimestampSeconds']-a['sourceTimestampSeconds'] for a,b in zip(lanes,lanes[1:])]),
            'presentationReasons':dict(Counter(r['presentation'].get('reason') for r in lanes))},
        'displayReasonEventCounts':dict(Counter(r['data']['reason'] for r in presentation)),
        'displayTransitions':timeline,'recordingAnchors':groups['tsr_path_recording_v1'],
        'simultaneousTsr':{'frames':len(simultaneous),'stageTimesMs':{k:quantiles([r[k] for r in simultaneous if k in r]) for k in ['lumaSamplingMs','laneFilterMs','geometryMs','preparationAddedMs']}},
        'intrinsics':{'sameGeometryAndRevisionPairs':len(pairs),'pairsWithDifferentValues':sum(a['calibration']!=b['calibration'] for a,b in pairs),
            'absoluteChanges':{k:quantiles([abs(a['calibration'][k]-b['calibration'][k]) for a,b in pairs]) for k in ['fx','fy','cx','cy']}},
        'qualification':'Event counts are sampled diagnostics, not duration-weighted state percentages. TSR stage timings are simultaneous evidence, not per-stage preview measurements. Recording anchors are callback estimates.'}
    args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report['preview'],indent=2))


if __name__=='__main__':main()
