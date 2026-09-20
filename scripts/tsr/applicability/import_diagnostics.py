#!/usr/bin/env python3
"""Extract local metadata sidecars into deterministic replay input; never create truth or copy images."""
import argparse
import hashlib
import json
from pathlib import Path
import jsonschema

ROOT=Path(__file__).resolve().parents[3]

def records(text):
    try:
        payload=json.loads(text)
        values=payload if isinstance(payload,list) else [payload]
    except json.JSONDecodeError:
        values=[]
        for number,line in enumerate(text.splitlines(),1):
            if 'tsr_applicability_v1=' in line:
                values.append(json.loads(line.split('tsr_applicability_v1=',1)[1]))
            else:
                try:values.append(json.loads(line))
                except json.JSONDecodeError:continue
    for value in values:
        if value.get('event')=='tsr_applicability_v1':
            value=value.get('evidence',value.get('details',{}).get('evidence'))
            if isinstance(value,str):value=json.loads(value)
        if isinstance(value,dict) and 'batch' in value:yield value

def extract(text):
    schema=json.loads((ROOT/'shared/tsr/applicability/evidence-v1.schema.json').read_text())
    validator=jsonschema.Draft202012Validator(dict(schema,oneOf=[{'$ref':'#/$defs/diagnostic'}]))
    unique={}
    for value in records(text):
        validator.validate(value);batch=value['batch'];scope=batch['scope']
        tracks={t['trackId']:t for t in value['tracks']};candidates={c['candidateId']:c for c in batch['candidates']}
        if len(tracks)!=len(value['tracks']) or len(candidates)!=len(batch['candidates']):raise ValueError('Duplicate physical/candidate identity')
        for t in tracks.values():
            if t['scope']!=scope:raise ValueError('Track scope mismatch')
            for sample in t['samples']:
                if sample['frameId']==batch['frameId'] and sample['candidate']['candidateId'] not in candidates:raise ValueError('Unmatched candidate link')
        for d in value['decisions']:
            if d['trackId'] not in tracks or d['frameId']!=batch['frameId'] or d['scope']!=scope:raise ValueError('Unmatched decision link')
            if d.get('roadSnapshotId')!=(batch.get('road') or {}).get('snapshotId'):raise ValueError('Unmatched road snapshot')
            if d['classification']!='LIKELY_EGO_CORRIDOR' and any(d[k] for k in ['displayEligible','immediateEligible','passageEligible']):raise ValueError('Non-ego authority')
        key=(json.dumps(scope,sort_keys=True),batch['frameId'])
        if key in unique and unique[key]!=value:raise ValueError('Conflicting evidence for immutable frame')
        unique[key]=value
    return sorted(unique.values(),key=lambda r:(r['batch']['scope']['sessionId'],r['batch']['capturedAtMs'],r['batch']['frameId']))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('input',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    raw=args.input.read_bytes();evidence=extract(raw.decode('utf-8'))
    if not evidence:raise SystemExit('No applicability sidecars; legacy evidence is not evaluated.')
    sessions={}
    for r in evidence:sessions.setdefault(r['batch']['scope']['sessionId'],[]).append(r['batch'])
    output=dict(schemaVersion=1,sourceSha256=hashlib.sha256(raw).hexdigest(),reviewStatus='unreviewed',
        scenarios=[dict(id=f'capture-{i}',origin='unreviewed_real',expectedFinalClass=None,batches=bs) for i,bs in enumerate(sessions.values())])
    args.output.write_text(json.dumps(output,sort_keys=True,indent=2)+'\n')
    print(f'Imported {len(evidence)} metadata frames; reviewed applicability truth must be supplied separately.')
if __name__=='__main__':main()
