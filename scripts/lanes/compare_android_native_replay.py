#!/usr/bin/env python3
"""Compare physical Android first-cycle semantics with macOS native Swift replay.

This is NOT physical iPhone validation. Verifies per-frame pixel SHA, encoded PTS,
variant flags, order and metadata provenance before comparing shared semantics.
"""
import argparse
import json
from pathlib import Path
from compare_sustained_platforms import compare_values, load_records, normalized, sha

BOUNDARY_KEYS = ['points','observedSegments','confidence','cue','supportRows','provenance',
                 'evidenceAgeSeconds','geometryConfidence','paintOccupancy']


def offline_semantics(row):
    def boundaries(values):
        return [{key:value.get(key) for key in BOUNDARY_KEYS} for value in values]
    presentation=row['lanePresentation']
    record={
        'index':0, 'id':row['id'], 'sequenceId':row['sequenceId'],
        'sourcePtsSeconds':row['sourcePtsSeconds'],
        'operationBudgetExceeded':row['geometryBudgetExceeded'],
        'operationCount':row['road']['operationCount'],
        'temporalOperationCount':row['temporalOperationCount'],
        'boundaries':boundaries(row['rawBoundaries']),
        'selectedBoundaries':boundaries(row['confirmedBoundaries']),
        'selectedIndices':row['visibleBoundaryIndices'],
        'visibleIds':row['visibleIDs'],
        'selectionDecisions':presentation['selectionDecisions'],
        'lanePreparationDiagnostics':row['calibrationDiagnostics'],
    }
    result=normalized(record)
    # Sequence labels are independently assigned by packaging. Their one-to-one
    # partition and row order are checked against the source manifests below.
    del result['sequenceId']
    del result['index']
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--offline',action='append',required=True,help='ARM=/absolute/replay/directory')
    parser.add_argument('--source-manifest',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tolerance',type=float,default=1e-9)
    args=parser.parse_args()
    if args.output.exists(): parser.error('output must be new')
    if not 0<=args.tolerance<=1e-6: parser.error('tolerance must be in [0,1e-6]')
    offline={}
    for option in args.offline:
        arm,directory=option.split('=',1)
        if arm in offline: parser.error('duplicate arm')
        offline[arm]=Path(directory)
    manifest=json.loads(args.manifest.read_text()); frames=manifest['frames']; count=len(frames)
    if len({row['id'] for row in frames})!=count: raise ValueError('unique source IDs required')
    summary_path=args.android.with_suffix('.json'); device_summary=json.loads(summary_path.read_text())
    records,paused,duplicates,counts=load_records(args.android,count)
    provenance_errors=[]
    if device_summary.get('manifestSha256')!=sha(args.manifest): provenance_errors.append('Device report manifest SHA mismatch')
    if not device_summary.get('completed'): provenance_errors.append('Device summary is not completed')
    source_records={}; coverage={}; mismatch_frames=[]; deltas=[]; sequence_mappings={}; provenance={}
    for arm,directory in offline.items():
        metadata_path=directory/'metadata.json'; input_path=directory/'input.normalized.json'; rows_path=directory/'frames.ndjson'
        metadata=json.loads(metadata_path.read_text()); input_manifest=json.loads(input_path.read_text())
        inputs=input_manifest['frames']; rows=[json.loads(line) for line in rows_path.read_text().splitlines()]
        flags={'previewMode':True,'useSearchBands':'bands' in arm,'groupFragments':'fragments' in arm,'fragmentTracking':arm.endswith('tracking')}
        for key,value in flags.items():
            if metadata.get(key)!=value or input_manifest.get(key)!=value:
                provenance_errors.append(f'{arm}: incorrect {key} metadata/input flag')
        if metadata.get('normalizedManifestSha256')!=sha(input_path): provenance_errors.append(f'{arm}: normalized manifest SHA mismatch')
        if len(inputs)!=count or len(rows)!=count:
            provenance_errors.append(f'{arm}: source frame count differs'); continue
        sequence_map={}; reverse_sequence_map={}
        for index,(pack,original,row) in enumerate(zip(frames,inputs,rows)):
            fields=['id','width','height','decodedWidth','decodedHeight','time']
            for field in fields:
                if pack[field]!=original[field]: provenance_errors.append(f'{arm}/{index}: source {field} differs')
            for field in ['calibration','visualCalibration','orientationKey','locationFixes']:
                if pack.get(field)!=original.get(field): provenance_errors.append(f'{arm}/{index}: source {field} differs')
            if pack['rawSha256']!=original['graySha256'] or pack['rawSha256']!=row.get('rawSha256') or pack['rawSha256']!=row.get('inputSha256'):
                provenance_errors.append(f'{arm}/{index}: recorded luma SHA mismatch')
            if sha(Path(original['grayPath']))!=pack['rawSha256']:
                provenance_errors.append(f'{arm}/{index}: source pixel file changed')
            if row['id']!=pack['id'] or abs(row['sourcePtsSeconds']-pack['time'])>args.tolerance:
                provenance_errors.append(f'{arm}/{index}: output source ID/PTS mismatch')
            source_sequence=original['sequenceId']; packaged_sequence=pack['sequenceId']
            if sequence_map.setdefault(source_sequence,packaged_sequence)!=packaged_sequence or reverse_sequence_map.setdefault(packaged_sequence,source_sequence)!=source_sequence:
                provenance_errors.append(f'{arm}/{index}: packaging changed the sequence partition')
            if row['sequenceId']!=source_sequence: provenance_errors.append(f'{arm}/{index}: output sequence mismatch')
            source_records[(arm,pack['id'])]=(index,row)
        sequence_mappings[arm]=sequence_map
        provenance[arm]={'metadata':metadata,'metadataSha256':sha(metadata_path),'inputManifestSha256':sha(input_path),'framesSha256':sha(rows_path)}
    for arm in offline:
        paired=0; matched=0; paused_count=0; missing=[]
        for pack in frames:
            key=(arm,pack['id']); device=records.get(key); native=source_records.get(key)
            if device is None or native is None:
                missing.append(pack['id']); continue
            index,row=native
            if device['index']!=index or device['sequenceId']!=pack['sequenceId'] or abs(device['sourcePtsSeconds']-pack['time'])>args.tolerance:
                provenance_errors.append(f'{arm}/{pack["id"]}: device source order/PTS/sequence differs')
            if device.get('thermalPaused'):
                paused_count+=1; continue
            left=normalized(device); del left['sequenceId']; del left['index']
            right=offline_semantics(row); differences=[]
            compare_values(left,right,'frame',differences,args.tolerance,deltas,right_label='nativeSwift')
            paired+=1
            if differences: mismatch_frames.append({'arm':arm,'id':pack['id'],'differences':differences})
            else: matched+=1
        coverage[arm]={'expectedFrames':count,'comparedPairs':paired,'matchingPairs':matched,'androidPausedFirstCycle':paused_count,'missingFrameIds':missing}
    report={
        'schemaVersion':1,'comparison':'physical Android versus macOS native Swift; NOT physical iPhone validation',
        'matchingComparedPairs':not mismatch_frames and not provenance_errors and not duplicates and bool(deltas),
        'completeFirstCycleCoverage':all(row['comparedPairs']==count for row in coverage.values()),
        'comparedPairs':sum(row['comparedPairs'] for row in coverage.values()),'mismatchedPairs':len(mismatch_frames),
        'maximumNumericDelta':max(deltas,default=0),'numericTolerance':args.tolerance,'coverage':coverage,
        'provenanceErrors':provenance_errors,'duplicateDeviceKeys':duplicates,'sequenceLabelMappings':sequence_mappings,
        'nativeReplayProvenance':provenance,'mismatchFrames':mismatch_frames,
        'sourceSha256':{str(path.resolve()):sha(path) for path in [args.android,summary_path,args.manifest]},
        'scope':'Shared geometry/model points, painted fragments, confidence, evidence age, selected indices/IDs/sides, calibration diagnostics and operation counts. First physical Android replay cycle compared with accelerated macOS Swift source replay. Byte SHA/PTS/order/variant controls verified. Timing and memory are deliberately not compared; this provides no physical iPhone latency, memory, thermal or live camera acceptance.',
        'unavailableCommonFields':['lastFreshTimestampSeconds','trackedAnchorCount','full presentation item state','corridor hypotheses'],
    }
    if args.source_manifest:
        build_sources=json.loads(args.source_manifest.read_text())
        report['deviceBuildSources']={'path':str(args.source_manifest.resolve()),'sha256':sha(args.source_manifest),'content':build_sources}
        swift_sources={Path(path).name:digest for path,digest in build_sources.get('sources',{}).items() if path.startswith('iphone/SpeedConsumerApp/')}
        report['nativeVersusDeviceSwiftSourceDifferences']={
            arm:[{'file':name,'nativeSha256':details['metadata']['sourceHashes'].get(name),'deviceBuildSha256':digest}
                 for name,digest in swift_sources.items() if details['metadata']['sourceHashes'].get(name)!=digest]
            for arm,details in provenance.items()}
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ['comparison','matchingComparedPairs','completeFirstCycleCoverage','comparedPairs','mismatchedPairs','maximumNumericDelta','coverage','provenanceErrors']}))
    if not report['matchingComparedPairs']: raise SystemExit(1)
    if not report['completeFirstCycleCoverage']: raise SystemExit(2)


if __name__=='__main__': main()
