#!/usr/bin/env python3
"""Compare production Swift/Kotlin image front ends on identical recorded luma."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--ids', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output must be new')
    repo = Path(__file__).resolve().parents[2]
    rows = [row for row in json.loads(args.manifest.read_text())['frames'] if row['id'] in args.ids]
    if {row['id'] for row in rows} != set(args.ids):
        parser.error('missing frame IDs')
    args.output.mkdir(parents=True)
    inputs = []
    for row in rows:
        path = Path(row['grayPath'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['graySha256']:
            raise ValueError(f'integrity mismatch: {path}')
        fields = [row['id'], str(path.resolve()), str(row['width']), str(row['height']), str(row['time'])]
        if any('\t' in value or '\n' in value for value in fields):
            raise ValueError('TSV field contains control character')
        inputs.append('\t'.join(fields))
    tsv = args.output / 'input.tsv'
    tsv.write_text('\n'.join(inputs)+'\n')
    swift = [repo/'iphone/SpeedConsumerApp'/f'{name}.swift' for name in ['LaneDetection','RoadBoundaryDetector']]
    kotlin = [repo/'android/app/src/main/java/de/youspeed/android/alpha'/f'{name}.kt' for name in ['LaneDetection','RoadBoundaryDetector','RoadPathLaneFilter']]
    swift.append(repo/'scripts/lanes/DetectorParity.swift')
    kotlin.append(repo/'scripts/lanes/DetectorParity.kt')
    hashes = {str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest() for path in swift+kotlin}
    with tempfile.TemporaryDirectory(prefix='lane-detector-parity-') as temporary:
        temp = Path(temporary)
        subprocess.run(['swiftc','-O','-module-cache-path',str(temp/'cache'),*[str(p) for p in swift],'-o',str(temp/'swift')],check=True)
        subprocess.run(['kotlinc',*[str(p) for p in kotlin],'-include-runtime','-d',str(temp/'kotlin.jar')],check=True)
        for name, command in [('swift',[str(temp/'swift')]),('kotlin',['java','-jar',str(temp/'kotlin.jar')])]:
            with (args.output/f'{name}.ndjson').open('w') as output:
                subprocess.run(command+[str(tsv.resolve())],check=True,stdout=output)
    observed = [[json.loads(line) for line in (args.output/f'{name}.ndjson').read_text().splitlines()] for name in ['swift','kotlin']]
    differences = []
    maximum_delta = 0.0
    def compare(a,b,path):
        nonlocal maximum_delta
        if isinstance(a,(int,float)) and not isinstance(a,bool) and isinstance(b,(int,float)) and not isinstance(b,bool):
            maximum_delta = max(maximum_delta, abs(a-b))
            if abs(a-b)>1e-10:
                differences.append({'path':path,'swift':a,'kotlin':b})
        elif isinstance(a,dict) and isinstance(b,dict) and a.keys()==b.keys():
            for key in a:
                compare(a[key],b[key],path+'.'+key)
        elif isinstance(a,list) and isinstance(b,list) and len(a)==len(b):
            for index,(left,right) in enumerate(zip(a,b)):
                compare(left,right,f'{path}[{index}]')
        elif a != b:
            differences.append({'path':path,'swift':a,'kotlin':b})
    compare(*observed,'frames')
    summary = {'schemaVersion':1,'frames':len(rows),'comparisons':len(observed[0]),'variants':4,
               'matching':not differences,'maximumNumericDelta':maximum_delta,'tolerance':1e-10,
               'sourceSha256':hashes,'differences':differences}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('sourceSha256','differences')}))
    if differences:
        raise SystemExit(1)


if __name__=='__main__':
    main()
