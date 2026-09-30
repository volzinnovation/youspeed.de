#!/usr/bin/env python3
"""Sequence audit on frozen partial labels, with interval-censored duration metrics.

Score coverage first with score_recorded_pipeline.py. This adds labelled temporal
metrics only; unlabelled pixels never become negative ground truth.
"""
import argparse
from collections import defaultdict,Counter
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from score_recorded_pipeline import poly
from compare_recorded_filters import score_response


def interval_metrics(times, flags):
    # No extrapolation beyond the first/last annotation. Trapezoidal sampled occupancy.
    occupied=sum((b-a)*(int(x)+int(y))/2 for a,b,x,y in zip(times,times[1:],flags,flags[1:]))
    longest=0.;start=None
    for t,on in zip(times,flags):
        if on:
            if start is None:start=t
            longest=max(longest,t-start)
        else:start=None
    return dict(estimatedSeconds=occupied,longestObservedSpanSeconds=longest,
                transitions=sum(x!=y for x,y in zip(flags,flags[1:])))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scores',type=Path,required=True);p.add_argument('--annotations',type=Path,required=True);p.add_argument('--runs',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():p.error('Output exists')
    cv2.setNumThreads(1)
    labels={f['id']:f for f in json.loads(a.annotations.read_text())['frames']}
    scores=json.loads(a.scores.read_text());lookup={(r['variant'],r['stage'],r['id']):r for r in scores['perFrame']}
    groups=defaultdict(list)
    for fid,f in labels.items():groups[f['sequence']].append(fid)
    results=[];summaries={};diagnostics={}
    for folder in sorted(a.runs.iterdir()):
        if not (folder/'summary.json').exists():continue
        variant=folder.name;pred={};counts=Counter()
        for line in (folder/'frames.ndjson').open():
            r=json.loads(line);counts.update(r.get('experimentDiagnostics') or {})
            if r['id'] in labels:pred[r['id']]=r
        diagnostics[variant]=dict(counts);summaries[variant]=json.loads((folder/'summary.json').read_text())['total']
        for seq,fids in groups.items():
            fids.sort(key=lambda f:pred[f]['time']);times=[pred[f]['time'] for f in fids]
            sc=[lookup[variant,'visible',f] for f in fids]
            covered=[r.get('annotatedPaintCoverage') is not None and r.get('annotatedPaintCoverage')>=.5 for r in sc]
            false=[r['falseResponsePixelsInNoPaintRoi']>0 for r in sc]
            ids=[]
            # Identity controls only where the same solid stripe is annotated in all frames.
            stable=all(len(labels[f]['boundaries'])==1 and labels[f]['boundaries'][0].get('identity') for f in fids)
            if stable:
                for fid in fids:
                    row=pred[fid];matches=[]
                    for b in row['confirmedBoundaries']:
                        if b['cue']!='paint':continue
                        mask=np.zeros((row['height'],row['width']),np.uint8)
                        cv2.polylines(mask,[poly(b['points'],row['width'],row['height'])],False,255,1)
                        coverage=score_response(mask>0,labels[fid],scores['tolerancePixels'])['annotatedPaintCoverage']
                        if coverage is None or coverage<.5:continue
                        indices=[i for i,raw in enumerate(row['rawBoundaries']) if raw['points']==b['points']]
                        if len(indices)!=1:continue
                        tracks=[i['trackId'] for i in row['lanePresentation']['items'] if i.get('boundaryIndex')==indices[0]]
                        if len(tracks)==1:matches.append((coverage,tracks[0]))
                    matches.sort(reverse=True)
                    ids.append(matches[0][1] if len(matches)==1 or (len(matches)>1 and matches[0][0]-matches[1][0]>.1) else None)
            reacquisition=[];lost=None;seen=False
            for t,on in zip(times,covered):
                if on:
                    if lost is not None:reacquisition.append(t-lost)
                    seen=True;lost=None
                elif seen and lost is None:lost=t
            baseline=[lookup['baseline-top-hat','visible',f] for f in fids]
            results.append(dict(variant=variant,sequence=seq,condition=labels[fids[0]]['condition'],frames=len(fids),spanSeconds=times[-1]-times[0],
                annotatedPixels=sum(r.get('annotatedPaintPixels',0) for r in sc),coveredPixels=sum(r.get('coveredPaintPixels',0) for r in sc),
                visibleCoverage=[r.get('annotatedPaintCoverage') for r in sc],falseVisiblePixels=[r['falseResponsePixelsInNoPaintRoi'] for r in sc],
                falseVisible=interval_metrics(times,false),paintAboveHalfCoverage=interval_metrics(times,covered),
                firstAboveHalfOffsetSeconds=next((t-times[0] for t,on in zip(times,covered) if on),None),
                reacquisitionAfterFirstMissingSampleSeconds=reacquisition,rightCensoredLoss=lost is not None,
                identityApplicable=stable,matchedPresentationIDs=ids,
                identityChangesOnAdjacentMatchedFrames=sum(x is not None and y is not None and x!=y for x,y in zip(ids,ids[1:])),
                identityChangesIncludingReappearance=sum(x!=y for x,y in zip([i for i in ids if i is not None],[i for i in ids if i is not None][1:])),
                lostBaselineCoveredPixels=sum(max(0,b.get('coveredPaintPixels',0)-r.get('coveredPaintPixels',0)) for b,r in zip(baseline,sc))))
    # Cluster by sequence; samples inside a sequence are correlated. These intervals
    # describe this tiny audit, not a population guarantee or independent-drive CI.
    uncertainty=[];rng=np.random.default_rng(20260930)
    for variant in summaries:
        for condition in ['shadow','bright']:
            selected=[r for r in results if r['variant']==variant and (('shadow' in r['condition'] or 'shade' in r['condition']) if condition=='shadow' else r['condition'].startswith('bright')) and r['annotatedPixels']]
            base={r['sequence']:r for r in results if r['variant']=='baseline-top-hat'}
            deltas=[]
            for _ in range(2000):
                chosen=[selected[i] for i in rng.integers(0,len(selected),len(selected))]
                deltas.append(100*sum(r['coveredPixels']-base[r['sequence']]['coveredPixels'] for r in chosen)/sum(r['annotatedPixels'] for r in chosen))
            uncertainty.append(dict(variant=variant,condition=condition,sequences=len(selected),pairedSequenceBootstrapDeltaPP95=np.quantile(deltas,[.025,.975]).tolist()))
    report=dict(schemaVersion=1,definitions=dict(paintPresence='At least 50% of annotated paint pixels covered within scorer tolerance.',duration='Trapezoidal occupancy between adjacent 2 Hz annotations; longest span uses first/last positive sample. No extrapolation.',identity='Same manually labelled solid right stripe only. Match one visible PAINT boundary with >=50% coverage, require unique geometry-to-presentation mapping; ambiguous IDs excluded.',reacquisition='First positive sample after first missing sample, only after a previous positive sample; tails censored.',uncertainty='Paired sequence bootstrap, seed 20260930, 2000 resamples; tiny previously seen drives, not population confidence.'),
        inputHashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [a.scores,a.annotations,Path(__file__),*sorted(a.runs.glob('*/summary.json'))]},
        hostRuns=summaries,experimentCandidateCounters=diagnostics,sequenceMetrics=results,uncertainty=uncertainty)
    a.output.write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
