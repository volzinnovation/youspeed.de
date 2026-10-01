#!/usr/bin/env python3
"""Compare identical-image lane replays. Continuity is not a road accuracy score."""
import argparse
import json
from pathlib import Path
from compare_replay_cadence import continuity
from replay_recorded_pipeline import summarize


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',required=True,type=Path)
    p.add_argument('--candidate',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--require-unchanged',action='store_true',help='Assert default TSR geometry, identities and work limits are unchanged')
    a=p.parse_args()
    rows=[[json.loads(l) for l in path.open()] for path in [a.baseline,a.candidate]]
    if not rows[0] or len(rows[0])!=len(rows[1]): p.error('Frame count mismatch or empty input')
    for old,new in zip(*rows):
        if any(old[k]!=new[k] for k in ['id','inputSha256','sequenceId','time']): p.error('Inputs/order/timestamps differ')
    keys=['rawBoundaries','visibleBoundaryIndices','visibleIDs','lanePresentation','road','geometryBudgetExceeded','temporalResetReason','temporalOperationCount']
    report={'frames':len(rows[0]),'baseline':dict(continuity(rows[0]),summary=summarize(rows[0])),
            'candidate':dict(continuity(rows[1]),summary=summarize(rows[1])),
            'qualification':'Identical encoded pixels and timestamps; no accuracy labels, metric/GPS validation or device performance qualification.'}
    if a.require_unchanged:
        report['comparedFields']=keys
        report['mismatches']=[{'id':old['id'],'fields':[k for k in keys if old[k]!=new[k]]} for old,new in zip(*rows) if any(old[k]!=new[k] for k in keys)]
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    if a.require_unchanged and report['mismatches']: raise SystemExit('Geometry regression; see '+str(a.output))
    print('Compared',len(rows[0]),'frames; report:',a.output)


if __name__=='__main__':main()
