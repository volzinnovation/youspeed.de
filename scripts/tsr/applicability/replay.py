#!/usr/bin/env python3
"""Compile the actual Swift/Kotlin policy, replay identical immutable proposals, compare outputs.

This is the recorded-candidate engineering lane. It does not run either detector,
score human truth, or claim full-image/device qualification.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
import jsonschema

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / 'shared/tsr/applicability'
ANDROID = ROOT / 'android/app/src/main/java/de/youspeed/android/alpha'

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(value):
    if isinstance(value,dict): return {k:canonical(v) for k,v in value.items() if v is not None}
    if isinstance(value,list): return [canonical(v) for v in value]
    return value

def compare(left,right,path='root'):
    if isinstance(left,float) or isinstance(right,float):
        if not isinstance(left,(int,float)) or not isinstance(right,(int,float)) or not math.isclose(left,right,abs_tol=1e-9,rel_tol=1e-9): raise ValueError(f'Numeric parity mismatch at {path}: {left} != {right}')
    elif isinstance(left,dict) and isinstance(right,dict):
        if left.keys()!=right.keys(): raise ValueError(f'Key parity mismatch at {path}')
        for key in left: compare(left[key],right[key],f'{path}.{key}')
    elif isinstance(left,list) and isinstance(right,list):
        if len(left)!=len(right):raise ValueError(f'Length parity mismatch at {path}')
        for i,(a,b) in enumerate(zip(left,right)): compare(a,b,f'{path}[{i}]')
    elif left!=right: raise ValueError(f'Semantic parity mismatch at {path}: {left} != {right}')

def validate_vectors(vectors):
    schema=json.loads((CONTRACT/'evidence-v1.schema.json').read_text())
    validator=jsonschema.Draft202012Validator(dict(schema,oneOf=[{'$ref':'#/$defs/batch'}]))
    names=set()
    for scenario in vectors['scenarios']:
        if scenario['id'] in names: raise ValueError('Duplicate scenario identity')
        names.add(scenario['id'])
        for batch in scenario['batches']:
            validator.validate(batch)
            ids=[c['candidateId'] for c in batch['candidates']]
            if len(ids)!=len(set(ids)):raise ValueError('Duplicate candidate identity')
            for c in batch['candidates']:
                b=c['box']
                if b['x']+b['width']>1.000001 or b['y']+b['height']>1.000001:raise ValueError('Box outside normalized frame')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--vectors',type=Path,default=CONTRACT/'golden-vectors-v1.json')
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--kotlin-classpath',default=None)
    args=ap.parse_args();vectors=json.loads(args.vectors.read_text());validate_vectors(vectors)
    cp=args.kotlin_classpath
    if cp is None:
        cache=Path(os.environ.get('GRADLE_USER_HOME',Path.home()/'.gradle'))/'caches/modules-2/files-2.1/org.jetbrains.kotlinx'
        jars=[]
        for artifact in ('kotlinx-serialization-core-jvm','kotlinx-serialization-json-jvm'):
            found=[p for p in (cache/artifact/'1.7.3').glob('*/*.jar') if not p.name.endswith(('-sources.jar','-javadoc.jar'))]
            if len(found)!=1:raise SystemExit('Resolve Android Gradle dependencies first or provide --kotlin-classpath.')
            jars.extend(found)
        cp=os.pathsep.join(map(str,jars))
    sources=[ROOT/'iphone/SpeedConsumerApp/TrafficSignApplicability.swift',ANDROID/'TrafficSignApplicability.kt',ANDROID/'TrafficSignApplicabilityJson.kt']
    with tempfile.TemporaryDirectory(prefix='tsr-applicability-') as temp:
        temp=Path(temp)
        subprocess.run(['swiftc',str(sources[0]),str(Path(__file__).with_name('Replay.swift')),'-o',str(temp/'swift')],check=True)
        subprocess.run(['kotlinc',*map(str,sources[1:]),str(Path(__file__).with_name('Replay.kt')),'-cp',cp,'-include-runtime','-d',str(temp/'kotlin.jar')],check=True)
        outputs={};costs={}
        for platform,cmd in [('swift',[str(temp/'swift')]),('kotlin',['java','-cp',str(temp/'kotlin.jar')+os.pathsep+cp,'de.youspeed.android.alpha.ReplayKt'])]:
            start=time.perf_counter()
            outputs[platform]=json.loads(subprocess.check_output(cmd+[str(args.vectors)]))
            costs[platform]=(time.perf_counter()-start)*1000
        compare(canonical(outputs['swift']),canonical(outputs['kotlin']))
        rows=[]
        for scenario,result in zip(vectors['scenarios'],outputs['swift']):
            final=result['frames'][-1]['decisions']; expected=scenario.get('expectedFinalClass')
            if expected is not None and expected not in [d['classification'] for d in final]:raise ValueError(f"Golden decision failed: {scenario['id']}")
            rows.append(dict(scenario=scenario['id'],frames=len(result['frames']),finalDecisions=[dict(trackId=d['trackId'],classification=d['classification'],reasons=d['reasons']) for d in final]))
        origins=sorted({s.get('origin','unspecified') for s in vectors['scenarios']})
        report=dict(schemaVersion=1,lane='recorded_candidate',origins=origins,fieldQualified=False,parity='passed',numericTolerance=1e-9,
            corpusSha256=digest(args.vectors),configSha256=digest(CONTRACT/'policy-v1.json'),sourceHashes={str(p.relative_to(ROOT)):digest(p) for p in sources},
            scenarios=rows,processWallTimeIncludingStartupMs=costs,
            pending=['Reviewed real sequence corpus and baseline','Full-image inference replay','Independent holdout and frozen empirical gates','Minimum-device sustained performance, battery and thermal evidence','Explicit paired-platform rollout approval'])
        args.output.mkdir(parents=True,exist_ok=True)
        (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        (args.output/'predictions.json').write_text(json.dumps(outputs['swift'],indent=2)+'\n')
        print(f"Exact semantic/state parity passed for {len(rows)} recorded-candidate scenarios; field qualification pending. Report: {args.output/'report.json'}")
if __name__=='__main__':main()
