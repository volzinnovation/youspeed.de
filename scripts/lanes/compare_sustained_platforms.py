#!/usr/bin/env python3
"""Compare Swift/Kotlin first-cycle component replay semantics on identical pixels.

Timing, operating-system thermal enums and process memory are not expected to be
identical. Paused or missing rows are reported as coverage gaps, never replaced
with a matching row from a later replay cycle.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary_path(ndjson):
    return ndjson.with_suffix('.json')


def load_records(path, frame_count):
    records = {}
    paused = []
    duplicate = []
    counts = {}
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        arm = row['arm']
        counts[arm] = counts.get(arm, 0) + 1
        if row['index'] >= frame_count:
            continue
        key = (arm, row['id'])
        if key in records:
            duplicate.append({'arm':arm, 'id':row['id'], 'line':line_number})
        records[key] = row
        if row.get('thermalPaused'):
            paused.append({'arm':arm, 'id':row['id'], 'index':row['index']})
    return records, paused, duplicate, counts


def normalized(row):
    diagnostics = row.get('lanePreparationDiagnostics', {})
    presentation = row.get('lanePresentation', {})
    return {
        'index': row['index'],
        'id': row['id'],
        'sequenceId': row['sequenceId'],
        'sourcePtsSeconds': row['sourcePtsSeconds'],
        'operationBudgetExceeded': row.get('operationBudgetExceeded'),
        'operationCount': row.get('operationCount'),
        'temporalOperationCount': row.get('temporalOperationCount'),
        'boundaries': row.get('boundaries'),
        'selectedBoundaries': row.get('selectedBoundaries'),
        'selectedIndices': row.get('selectedIndices'),
        'visibleIds': row.get('visibleIds'),
        'selectionDecisions': row.get('selectionDecisions', presentation.get('selectionDecisions')),
        'diagnostics': {key: diagnostics.get(key) for key in (
            'calibrationGeneration', 'resetComponents', 'currentIntrinsics', 'guideTrust',
            'guidePriorUsed', 'detectorRejections', 'detectionVariant')},
    }


def compare_values(left, right, path, mismatches, tolerance, deltas, left_label="android", right_label="iphone"):
    numeric = lambda value: isinstance(value, (int,float)) and not isinstance(value, bool)
    if numeric(left) and numeric(right):
        if not (math.isfinite(left) and math.isfinite(right)):
            mismatches.append({'path':path, left_label:left, right_label:right})
            return
        delta = abs(left-right)
        deltas.append(delta)
        if delta > tolerance:
            mismatches.append({'path':path, left_label:left, right_label:right})
    elif isinstance(left,dict) and isinstance(right,dict):
        if left.keys() != right.keys():
            mismatches.append({'path':path+'.keys', left_label:sorted(left), right_label:sorted(right)})
        for key in sorted(left.keys() & right.keys()):
            compare_values(left[key],right[key],path+'.'+key,mismatches,tolerance,deltas,left_label,right_label)
    elif isinstance(left,list) and isinstance(right,list):
        if len(left) != len(right):
            mismatches.append({'path':path+'.length', left_label:len(left), right_label:len(right)})
        for index,(a,b) in enumerate(zip(left,right)):
            compare_values(a,b,f'{path}[{index}]',mismatches,tolerance,deltas,left_label,right_label)
    elif type(left) is not type(right) or left != right:
        mismatches.append({'path':path, left_label:left, right_label:right})


def compare_runs(android_path, iphone_path, manifest_path, tolerance=1e-9):
    manifest = json.loads(manifest_path.read_text())
    frames = manifest['frames']
    if len({frame['id'] for frame in frames}) != len(frames):
        raise ValueError('Manifest IDs must be unique within the first cycle')
    expected = {row['id']: (index,row) for index,row in enumerate(frames)}
    android, android_paused, android_duplicates, android_counts = load_records(android_path,len(frames))
    iphone, iphone_paused, iphone_duplicates, iphone_counts = load_records(iphone_path,len(frames))
    android_summary = json.loads(summary_path(android_path).read_text())
    iphone_summary = json.loads(summary_path(iphone_path).read_text())
    manifest_sha = sha(manifest_path)
    manifest_matches = android_summary.get('manifestSha256') == manifest_sha == iphone_summary.get('manifestSha256')
    source_errors = []
    for platform, rows in [('android',android),('iphone',iphone)]:
        for (arm, identifier), row in rows.items():
            match = expected.get(identifier)
            if match is None or row['index'] != match[0] or abs(row['sourcePtsSeconds']-match[1]['time'])>tolerance:
                source_errors.append({'platform':platform,'arm':arm,'id':identifier,'index':row['index']})
    shared_keys = sorted(android.keys() & iphone.keys())
    compared = []
    mismatch_frames = []
    deltas = []
    for key in shared_keys:
        a,b = android[key],iphone[key]
        if a.get('thermalPaused') or b.get('thermalPaused'):
            continue
        mismatches = []
        compare_values(normalized(a),normalized(b),'frame',mismatches,tolerance,deltas)
        compared.append({'arm':key[0],'id':key[1],'matching':not mismatches})
        if mismatches:
            mismatch_frames.append({'arm':key[0],'id':key[1],'differences':mismatches})
    android_arms, iphone_arms = set(android_counts), set(iphone_counts)
    arms = sorted(android_arms | iphone_arms)
    coverage = {}
    for arm in arms:
        paired = [row for row in compared if row['arm']==arm]
        coverage[arm] = {
            'expectedFirstCycleFrames': len(frames),
            'androidFirstCycleRows': sum(key[0]==arm for key in android),
            'iphoneFirstCycleRows': sum(key[0]==arm for key in iphone),
            'comparedProcessedPairs': len(paired),
            'matchingPairs': sum(row['matching'] for row in paired),
            'androidPausedFirstCycle': sum(row['arm']==arm for row in android_paused),
            'iphonePausedFirstCycle': sum(row['arm']==arm for row in iphone_paused),
        }
    missing_android = [{'arm':arm,'id':identifier} for arm,identifier in sorted(iphone.keys()-android.keys())]
    missing_iphone = [{'arm':arm,'id':identifier} for arm,identifier in sorted(android.keys()-iphone.keys())]
    complete_coverage = all(row['comparedProcessedPairs']==len(frames) for row in coverage.values()) and bool(coverage)
    return {
        'schemaVersion':1,
        'matchingComparedPairs': not mismatch_frames and bool(compared) and manifest_matches and not source_errors and not android_duplicates and not iphone_duplicates,
        'completeFirstCycleCoverage': complete_coverage,
        'manifestMatchesBothReports': manifest_matches,
        'comparedPairs': len(compared),
        'mismatchedPairs': len(mismatch_frames),
        'maximumNumericDelta': max(deltas,default=0),
        'numericTolerance':tolerance,
        'coverage':coverage,
        'missingAndroid':missing_android,
        'missingIphone':missing_iphone,
        'androidDuplicateFirstCycleKeys':android_duplicates,
        'iphoneDuplicateFirstCycleKeys':iphone_duplicates,
        'manifestSourceErrors':source_errors,
        'mismatchFrames':mismatch_frames,
        'sourceSha256':{str(path.resolve()):sha(path) for path in [android_path,iphone_path,manifest_path,summary_path(android_path),summary_path(iphone_path)]},
        'scope':'First encoded cycle only; compares production model/paint/selection/calibration diagnostics and operation counts. Wall and stage times, platform thermal enums and process RSS intentionally excluded. Paused/missing exposures remain coverage gaps. This verifies implementation agreement, not border correctness or sustained camera/TSR/recording behavior.',
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android',type=Path,required=True)
    parser.add_argument('--iphone',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-manifest',type=Path)
    parser.add_argument('--tolerance',type=float,default=1e-9)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('output must be new')
    if not 0<=args.tolerance<=1e-6:
        parser.error('tolerance must be in [0,1e-6]')
    report=compare_runs(args.android,args.iphone,args.manifest,args.tolerance)
    if args.source_manifest:
        report['productionSourceManifest']={'path':str(args.source_manifest.resolve()),'sha256':sha(args.source_manifest),'content':json.loads(args.source_manifest.read_text())}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ['matchingComparedPairs','completeFirstCycleCoverage','comparedPairs','mismatchedPairs','maximumNumericDelta','coverage']}))
    if not report['matchingComparedPairs']:
        raise SystemExit(1)
    if not report['completeFirstCycleCoverage']:
        raise SystemExit(2)


if __name__=='__main__':
    main()
