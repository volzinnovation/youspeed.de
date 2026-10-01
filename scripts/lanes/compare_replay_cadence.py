#!/usr/bin/env python3
"""Compare a completed dense replay to its exact every-fifth-frame subset.

Reuses the frozen compiled pipeline. No production source or device is changed.
Availability and identity continuity are diagnostics, not accuracy scores.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
from replay_recorded_pipeline import summarize


def continuity(rows):
    groups = defaultdict(list)
    for r in rows: groups[r['sequenceId']].append(r)
    ids, transitions, span = set(), 0, 0
    lives = defaultdict(list)
    for seq, rs in groups.items():
        span += rs[-1]['time']-rs[0]['time']
        for r in rs:
            for i in r['visibleIDs']:
                ids.add((seq,i)); lives[seq,i].append(r['time'])
        transitions += sum(set(a['visibleIDs'])!=set(b['visibleIDs']) for a,b in zip(rs,rs[1:]))
    lengths = sorted(v[-1]-v[0] for v in lives.values())
    return dict(uniqueVisibleIds=len(ids),identitySetTransitions=transitions,
                observedSpanSeconds=span,identityTransitionsPerSecond=transitions/span,
                visibleIdSpanMedianSeconds=lengths[len(lengths)//2] if lengths else None,
                visibleCountHistogram=dict(Counter(len(r['visibleIDs']) for r in rows)))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dense-replay',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    a=p.parse_args()
    a.output_dir.mkdir(exist_ok=False)
    dense=[json.loads(l) for l in (a.dense_replay/'frames.ndjson').open()]
    manifest=json.loads((a.dense_replay/'input.normalized.json').read_text())
    manifest['variant']='build10022-matched-2fps'
    groups=defaultdict(list)
    for f in manifest['frames']:groups[f['sequenceId']].append(f)
    manifest['frames']=[f for fs in groups.values() for f in fs[::5]]
    inp=a.output_dir/'input.normalized.json';inp.write_text(json.dumps(manifest,indent=2)+'\n')
    binary=a.dense_replay/'pipeline-replay'
    out=a.output_dir/'frames.ndjson'
    subprocess.run([str(binary.resolve()),str(inp.resolve()),str(out.resolve())],check=True)
    sparse=[json.loads(l) for l in out.open()]
    assert len(sparse)==len(manifest['frames'])
    ids=set(r['id'] for r in sparse)
    matched=[r for r in dense if r['id'] in ids]
    assert len(matched)==len(sparse)
    assert {r['id']:r['inputSha256'] for r in matched}=={r['id']:r['inputSha256'] for r in sparse}
    report=dict(dense=summarize(dense),sparse=summarize(sparse),
                commonFrames=dict(count=len(matched),denseVisible=sum(bool(r['visibleIDs']) for r in matched),
                                  sparseVisible=sum(bool(r['visibleIDs']) for r in sparse)),
                denseContinuity=continuity(dense),sparseContinuity=continuity(sparse),
                denseAtCommonContinuity=continuity(matched),
                provenance='Sparse replay uses every fifth input of each dense sequence, identical luma bytes and compiled production pipeline; all runs reset per sequence.',
                binarySha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                sourceMetadata=str((a.dense_replay/'metadata.json').resolve()),
                qualification='Three selected jump intervals; exploratory, no accuracy annotations, camera calibration/GPS or phone performance. More visible output can include more false boundaries.')
    (a.output_dir/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
