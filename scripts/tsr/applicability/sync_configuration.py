#!/usr/bin/env python3
"""Generate pinned native policy constants from the single shared, versioned config."""
import argparse
import hashlib
import json
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[3]
CONFIG=ROOT/'shared/tsr/applicability/policy-v1.json'

def generated(language):
    config=json.loads(CONFIG.read_text()); digest=hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    values={'policyVersion':config['policyVersion'],'configHash':digest,'defaultMode':config['mode']}
    values.update({k:v for k,v in config.items() if k not in ('schemaVersion','policyVersion','mode')})
    ints={'maxCandidates','maxTracks','maxHistory','minObservations','maxBranches','maxHypotheses'}
    declaration='struct TSRApplicabilityConfiguration: Sendable' if language=='swift' else 'object TSRApplicabilityConfiguration'
    lines=[declaration+' {']
    for k,v in values.items():
        literal=json.dumps(v) if isinstance(v,str) else str(v if k in ints else float(v))
        lines.append(('    static let ' if language=='swift' else '    const val ')+k+' = '+literal)
    return '\n'.join(lines+['}'])

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for language,relative in [('swift','iphone/SpeedConsumerApp/TrafficSignApplicability.swift'),('kotlin','android/app/src/main/java/de/youspeed/android/alpha/TrafficSignApplicability.kt')]:
        path=ROOT/relative;text=path.read_text();pattern=r'(?:struct TSRApplicabilityConfiguration: Sendable|object TSRApplicabilityConfiguration) \{.*?\n\}'
        desired=re.sub(pattern,lambda _:generated(language),text,flags=re.S)
        if args.check and desired!=text:raise SystemExit(f'Native config drift: {relative}')
        if not args.check:path.write_text(desired)
if __name__=='__main__':main()
