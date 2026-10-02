#!/usr/bin/env python3
"""Score frozen visual keyframe labels separately from unlabelled output-continuity proxies."""
import argparse,gzip,hashlib,json,math
from collections import defaultdict,Counter
from pathlib import Path

def read_replay(path):
    """Read plain or losslessly archived NDJSON; hash the original content bytes."""
    path=Path(path);opener=gzip.open if path.suffix=='.gz' else open
    rows=[];digest=hashlib.sha256()
    with opener(path,'rb') as stream:
        for line in stream:
            digest.update(line)
            if line.strip():rows.append(json.loads(line))
    return rows,digest.hexdigest()

def x_at(points,y):
    points=sorted(points,key=lambda p:p[1])
    for a,b in zip(points,points[1:]):
        if a[1]<=y<=b[1] and b[1]>a[1]:return a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1])
    return None

def geometry_error(pred,truth,min_overlap=.08):
    lo=max(min(p[1] for p in pred),min(p[1] for p in truth),.58);hi=min(max(p[1] for p in pred),max(p[1] for p in truth),.95)
    if hi-lo<min_overlap:return None
    errors=[abs(x_at(pred,lo+(hi-lo)*i/16)-x_at(truth,lo+(hi-lo)*i/16)) for i in range(17)]
    return sum(errors)/len(errors)

def score_frame(row,label,settings):
    pred=row['confirmedBoundaries'];truth=label['borders'];candidates=[]
    for pi,p in enumerate(pred):
        for ti,t in enumerate(truth):
            e=geometry_error(p['points'],t['geometry'],settings['matchingMinimumOverlapY'])
            if e is not None and e<=settings['geometryToleranceX']:candidates.append((e,pi,ti))
    used_p=set();used_t=set();matches=[]
    for e,pi,ti in sorted(candidates):
        if pi not in used_p and ti not in used_t:used_p.add(pi);used_t.add(ti);matches.append(dict(prediction=pi,truth=ti,errorX=e,side=truth[ti]['side']))
    ignored=[]
    for pi,p in enumerate(pred):
        if pi in used_p:continue
        for region in label.get('ignoreGeometry',[]):
            e=geometry_error(p['points'],region['points'],settings['matchingMinimumOverlapY'])
            if e is not None and e<=region['tolerance']:ignored.append(pi);break
    drawn=0.;unsupported=0.;support_by_prediction=[]
    for pi,p in enumerate(pred):
        if pi in ignored:continue
        total=0.;bad=0.
        # Legacy renderers draw the whole model polyline. New renderers draw only
        # observedSegments. Never count the model's interpolated gaps as observed paint.
        segments=p.get('observedSegments') or [p['points']]
        for segment in segments:
            for a,b in zip(segment,segment[1:]):
                length=math.hypot((b[0]-a[0])*row['width'],(b[1]-a[1])*row['height']);n=max(1,math.ceil(length))
                for i in range(n):
                    u=(i+.5)/n;x=a[0]+(b[0]-a[0])*u;y=a[1]+(b[1]-a[1])*u
                    if not(label['evaluationYRange'][0]<=y<=label['evaluationYRange'][1]):continue
                    if any((q:=x_at(region['points'],y)) is not None and abs(q-x)<=region['tolerance'] for region in label.get('ignoreGeometry',[])):continue
                    is_supported=False
                    for t in truth:
                        tx=x_at(t['geometry'],y)
                        if tx is not None and abs(tx-x)<=settings['paintToleranceX'] and any(lo-settings['paintEndpointToleranceY']<=y<=hi+settings['paintEndpointToleranceY'] for lo,hi in t['paintedYIntervals']):is_supported=True;break
                    total+=length/n
                    if not is_supported:bad+=length/n
        drawn+=total;unsupported+=bad;support_by_prediction.append(dict(index=pi,drawnLengthPixels=total,unsupportedLengthPixels=bad,unsupportedFraction=bad/total if total else None))
    return dict(id=row['id'],split=label['split'],sequenceId=row['sequenceId'],truthBorders=len(truth),predictedBorders=len(pred),truePositive=len(matches),falsePositive=len(pred)-len(matches)-len(ignored),falseNegative=len(truth)-len(matches),ignoredPredictions=len(ignored),matches=matches,drawnLengthPixels=drawn,unsupportedLengthPixels=unsupported,unsupportedFraction=unsupported/drawn if drawn else None,paintSupportByPrediction=support_by_prediction)

def quantile(values):
    values=sorted(values)
    return dict(count=len(values),p50=values[len(values)//2],p95=values[min(len(values)-1,int(len(values)*.95))],maximum=values[-1]) if values else dict(count=0,p50=None,p95=None,maximum=None)

def aggregate_labelled(scores):
    keys=('truthBorders','predictedBorders','truePositive','falsePositive','falseNegative','ignoredPredictions','drawnLengthPixels','unsupportedLengthPixels')
    r={k:sum(s[k] for s in scores) for k in keys};r['labelledFrames']=len(scores)
    r['borderPrecision']=r['truePositive']/(r['truePositive']+r['falsePositive']) if r['truePositive']+r['falsePositive'] else None
    r['borderRecall']=r['truePositive']/r['truthBorders'] if r['truthBorders'] else None
    r['unsupportedDrawnLengthFraction']=r['unsupportedLengthPixels']/r['drawnLengthPixels'] if r['drawnLengthPixels'] else None
    r['framesWithMostlyUnsupportedPrediction']=sum(any((p['unsupportedFraction'] or 0)>.25 for p in s['paintSupportByPrediction']) for s in scores)
    r['unsupportedVisibleDurationSeconds']=None
    r['unsupportedDurationUnavailableReason']='Sparse keyframes do not establish continuous truth between samples.'
    return r

def continuity(rows):
    byseq=defaultdict(list)
    for r in rows:byseq[r['sequenceId']].append(r)
    ids=set();transitions=0;raw_displacements=[];gaps=[];reappear=[]
    for seq,frames in byseq.items():
        prev=None;last_seen={}
        for r in frames:
            visible={str(k):b for k,b in zip(r['visibleIDs'],r['confirmedBoundaries'])}
            for k in visible:
                ids.add((seq,k))
                if k in last_seen and r['time']-last_seen[k]>.15:reappear.append(r['time']-last_seen[k])
                last_seen[k]=r['time']
            if prev is not None:
                dt=r['time']-prev['time'];previous={str(k):b for k,b in zip(prev['visibleIDs'],prev['confirmedBoundaries'])}
                if set(visible)!=set(previous):transitions+=1
                if dt>.2:gaps.append(dt)
                if 0<dt<=.2:
                    for k in visible.keys()&previous.keys():
                        pa,pb=previous[k]['points'],visible[k]['points'];lo=max(min(p[1] for p in pa),min(p[1] for p in pb),.58);hi=min(max(p[1] for p in pa),max(p[1] for p in pb),.95)
                        if hi-lo>=.05:raw_displacements.append(sum(abs(x_at(pa,lo+(hi-lo)*i/8)-x_at(pb,lo+(hi-lo)*i/8))*r['width'] for i in range(9))/9)
            prev=r
    return dict(frames=len(rows),uniqueVisibleIDs=len(ids),identitySetTransitions=transitions,framesWithVisibleBorders=sum(bool(r['confirmedBoundaries']) for r in rows),maximumVisibleBorders=max((len(r['confirmedBoundaries']) for r in rows),default=0),sameIDRawDisplacementPixels=quantile(raw_displacements),sameIDReappearanceGapSeconds=quantile(reappear),sampleGapsOver200ms=len(gaps),preparationMs=quantile([r['preparationMs'] for r in rows]),qualification='Raw displacement includes real vehicle/road motion; it is not motion-corrected jitter. Identity reappearance is not ground-truth reacquisition. Host latency is not device acceptance.')

def negative_duration(rows,labels):
    byid={r["id"]:r for r in rows};total=0.;unsupported=0.;count=0;positive=0;longest=0.;run=0.
    for interval in labels["intervals"]:
        ordered=[byid[fid] for fid in interval["frameIDs"] if fid in byid]
        for i,r in enumerate(ordered):
            if r["inputSha256"]!=interval["inputSha256"][r["id"]]:raise ValueError("Dense negative input bytes changed")
            end=min(ordered[i+1]["time"] if i+1<len(ordered) else interval["endSeconds"],interval["endSeconds"])
            dt=min(.2,max(0,end-max(r["time"],interval["startSeconds"])))
            lo,hi=interval["evaluationYRange"]
            visible=any(any(max(a[1],b[1])>=lo and min(a[1],b[1])<=hi for a,b in zip(seg,seg[1:])) for b in r["confirmedBoundaries"] for seg in (b.get("observedSegments") or [b["points"]]))
            total+=dt;count+=1
            if visible:unsupported+=dt;positive+=1;run+=dt;longest=max(longest,run)
            else:run=0.
    return dict(scoredFrames=count,framesWithUnsupportedPaint=positive,reviewedDurationSeconds=total,unsupportedVisibleDurationSeconds=unsupported,longestUnsupportedRunSeconds=longest,qualification=labels["qualification"])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--labels',type=Path,required=True);p.add_argument('--frames',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--negative-intervals',type=Path);a=p.parse_args()
    settings=json.loads(a.labels.read_text());labels={l['id']:l for l in settings['frames']};rows,replay_sha=read_replay(a.frames);scores=[score_frame(r,labels[r['id']],settings) for r in rows if r['id'] in labels]
    report=dict(schemaVersion=1,labelsSha256=hashlib.sha256(a.labels.read_bytes()).hexdigest(),replaySha256=replay_sha,qualification=settings['qualification'],reviewer=settings['reviewer'],labelled=aggregate_labelled(scores),labelledBySplit={k:aggregate_labelled([s for s in scores if s['split']==k]) for k in sorted({s['split'] for s in scores})},continuity=continuity(rows),scores=scores)
    if a.negative_intervals:report['denseNegative']=negative_duration(rows,json.loads(a.negative_intervals.read_text()))
    a.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='scores'},indent=2))
if __name__=='__main__':main()
