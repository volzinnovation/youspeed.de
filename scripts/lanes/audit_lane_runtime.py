#!/usr/bin/env python3
"""Read saved app logs; deduplicate overlapping snapshots and report lane deadlines.

Does not establish UTC alignment with encoded video or compare experimental
mobile performance. Missing fields remain missing instead of becoming zero.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def quantiles(values):
    values = sorted(x for x in values if isinstance(x,(int,float)) and not isinstance(x,bool))
    return dict(n=len(values),p50=values[len(values)//2],p95=values[min(len(values)-1,int(len(values)*.95))],maximum=values[-1]) if values else dict(n=0)


def summarize(records, inferences):
    values = [d for _,d in records]
    def fields(key): return Counter(str(d[key]) for d in values if key in d)
    inference_ids = {r.get('frameId') for r in inferences if r.get('source')=='live_frame' and r.get('inferenceMs',0)>0}
    return dict(frames=len(values),firstUTC=records[0][0] if records else None,lastUTC=records[-1][0] if records else None,
        preparationMs=quantiles([d.get('preparationAddedMs') for d in values]),
        samplingMs=quantiles([d.get('lumaSamplingMs',d.get('preprocessingMs') if 'laneFilter' in d else None) for d in values]),
        filterMs=quantiles([d.get('laneFilterMs') for d in values]),geometryMs=quantiles([d.get('geometryMs') for d in values]),
        geometryDeadlineExceeded=dict(fields('geometryDeadlineExceeded')),deadlineExceeded=dict(fields('deadlineExceeded')),
        overlaySuppressionReasons=dict(fields('overlayPublicationSuppressionReason')),
        framesWithBoundaries=sum(bool(d.get('boundaries')) for d in values),
        inferenceWithExplicitEmptyBoundaries=sum(d.get('frameId') in inference_ids and d.get('boundaries')==[] for d in values),
        inferenceDespiteGeometryDeadline=sum(d.get('frameId') in inference_ids and d.get('geometryDeadlineExceeded') is True for d in values),
        analysisDimensions=dict(Counter(f"{d.get('analysisWidth')}x{d.get('analysisHeight')}" for d in values)),
        preparationBeforeTSR=dict(fields('preparationBeforeTSR')))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,action='append',required=True);p.add_argument('--after-utc',default='');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():p.error('Output exists')
    records={};inferences={};duplicates=0;malformed=0
    for path in a.input:
        for line in path.open():
            try:
                r=json.loads(line)
                if r.get('timestampUTC','')<a.after_utc:continue
                if r.get('event')=='traffic_sign_inference':inferences[r['frameId']]=r
                if r.get('event')!='tsr_path_evidence_v1':continue
                d=r['evidence'];d=json.loads(d) if isinstance(d,str) else d
                key=d['frameId'];duplicates+=key in records;records[key]=(r['timestampUTC'],d)
            except (ValueError,KeyError,TypeError):malformed+=1
    rows=sorted(records.values(),key=lambda r:r[0]);inferences=list(inferences.values())
    # Speed is explicitly logged; absence is unknown, not stationary.
    groups={'moving':[],'stationary':[],'unknown_motion':[]}
    for row in rows:
        speed=row[1].get('laneMotionHint',{}).get('speedMetersPerSecond')
        group='unknown_motion' if not isinstance(speed,(int,float)) else ('moving' if speed>1 else 'stationary')
        groups[group].append(row)
    report=dict(schemaVersion=1,afterUTC=a.after_utc,inputHashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in a.input},
        overlappingSnapshotsDeduplicated=duplicates,malformedRows=malformed,total=summarize(rows,inferences),
        byMotion={k:summarize(v,inferences) for k,v in groups.items()},
        qualification='Historical installed-app evidence, not performance of experimental variants. No inferred video UTC mapping. Motion threshold >1 m/s; missing hint is unknown.')
    a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report['total'],indent=2))

if __name__=='__main__':main()
