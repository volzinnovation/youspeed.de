#!/usr/bin/env python3
"""Compare bounded sequence prefixes from frozen Swift replays with host Kotlin.

Validates pixel/source hashes, keeps causal consecutive prefixes, and compares all
boundary/paint/identity/selection semantics exactly. Not device performance or
road accuracy validation. Image-only adapter refuses calibration/motion metadata.
"""
import argparse
import hashlib
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from replay_path import classpath

ROOT = Path(__file__).resolve().parents[2]
CORE = ['LaneDetection', 'RoadBoundaryDetector', 'RoadBoundaryMotionHint',
        'RoadBoundaryTemporalTracker', 'RoadBoundaryPresentationGate', 'RoadPathEvidence',
        'TrafficSignApplicability', 'VisualRoadCalibration', 'RoadPathSession', 'RoadPathLaneFilter']
FIELDS = ['id', 'sequenceId', 'time', 'inputSha256', 'rawBoundaries', 'confirmedBoundaries',
          'visibleBoundaryIndices', 'visibleIDs', 'lanePresentation', 'calibrationDiagnostics',
          'geometryBudgetExceeded', 'operationCount', 'temporalOperationCount',
          'temporalResetReason', 'rejectionCounts']
FLAGS = ['previewMode', 'useSearchBands', 'groupFragments', 'fragmentTracking', 'retainTentativeIdentity', 'jointSelection']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(path):
    if not path.exists() and path.with_suffix(path.suffix+'.gz').exists():
        path = path.with_suffix(path.suffix+'.gz')
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay-root', required=True, type=Path)
    parser.add_argument('--arms', nargs='+', default=['p0', 'group', 'tentative', 'joint', 'combined', 'tracking'])
    parser.add_argument('--sequences', nargs='+', required=True)
    parser.add_argument('--frames-per-sequence', type=int, default=20)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output must be new')
    if not 1 <= args.frames_per_sequence * len(args.sequences) <= 100:
        parser.error('require 1..100 frames per arm')
    if len(set(args.arms)) != len(args.arms) or len(set(args.sequences)) != len(args.sequences):
        parser.error('duplicate arm or sequence')
    args.output.mkdir(parents=True)
    sources = args.output / 'kotlin-sources'
    sources.mkdir()
    for name in CORE:
        shutil.copyfile(ROOT/'android/app/src/main/java/de/youspeed/android/alpha'/f'{name}.kt', sources/f'{name}.kt')
    shutil.copyfile(Path(__file__).with_name('RecordedPipelineParity.kt'), sources/'RecordedPipelineParity.kt')
    shutil.copyfile(__file__, args.output/Path(__file__).name)
    cp = classpath()
    report = {'schemaVersion': 1, 'qualification': 'Native macOS Swift versus host JVM Kotlin semantics; not physical device performance or accuracy',
              'numericTolerance': 0, 'fields': FIELDS, 'sequences': args.sequences,
              'kotlinSourceHashes': {p.name: sha(p) for p in sources.glob('*.kt')},
              'serializationJars': {path: sha(Path(path)) for path in cp.split(os.pathsep)}, 'arms': {}}
    with tempfile.TemporaryDirectory(prefix='lane-pipeline-parity-') as temporary:
        jar = Path(temporary)/'pipeline.jar'
        subprocess.run(['kotlinc', *map(str, sorted(sources.glob('*.kt'))), '-cp', cp, '-include-runtime', '-d', str(jar)], check=True)
        report['kotlinJarSha256'] = sha(jar)
        for arm in args.arms:
            replay = args.replay_root/f'dev-{arm}'
            metadata = json.loads((replay/'metadata.json').read_text())
            manifest = json.loads((replay/'input.normalized.json').read_text())
            assert sha(replay/'input.normalized.json') == metadata['normalizedManifestSha256']
            for name, digest in metadata['sourceHashes'].items():
                assert sha(replay/'sources'/name) == digest, f'Swift frozen source changed: {name}'
            assert all(metadata[key] == manifest[key] for key in FLAGS)
            selected = []
            for seq in args.sequences:
                frames = [row for row in manifest['frames'] if row['sequenceId'] == seq]
                assert len(frames) >= args.frames_per_sequence
                selected.extend(frames[:args.frames_per_sequence])
            for row in selected:
                assert sha(Path(row['grayPath'])) == row['graySha256']
            manifest['frames'] = selected
            arm_path = args.output/arm
            arm_path.mkdir()
            input_path = arm_path/'input.json'
            input_path.write_text(json.dumps(manifest, indent=2)+'\n')
            output = arm_path/'kotlin.ndjson'
            subprocess.run(['java', '-cp', str(jar)+os.pathsep+cp, 'de.youspeed.android.alpha.RecordedPipelineParityKt',
                            str(input_path), str(output)], check=True)
            expected_by_id = {row['id']: row for row in records(replay/'frames.ndjson')}
            swift = []
            for row in selected:
                value = dict(expected_by_id[row['id']])
                assert value['inputSha256'] == row['graySha256'] and value['time'] == row['time'] and value['sequenceId'] == row['sequenceId']
                value['operationCount'] = value['road']['operationCount']
                value['calibrationDiagnostics'] = {key: val for key, val in value['calibrationDiagnostics'].items() if key != 'stageMs'}
                swift.append({key: value[key] for key in FIELDS})
            (arm_path/'swift.ndjson').write_text(''.join(json.dumps(row, sort_keys=True)+'\n' for row in swift))
            kotlin = records(output)
            assert len(kotlin) == len(swift)
            mismatches = []
            maximum_delta = 0.0
            def compare(a, b, path):
                nonlocal maximum_delta
                if type(a) in (int, float) and type(b) in (int, float):
                    maximum_delta = max(maximum_delta, abs(a-b))
                    if a != b:
                        mismatches.append({'path': path, 'swift': a, 'kotlin': b})
                elif isinstance(a, dict) and isinstance(b, dict) and a.keys() == b.keys():
                    for key in a:
                        compare(a[key], b[key], path+'.'+key)
                elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
                    for index, (left, right) in enumerate(zip(a, b)):
                        compare(left, right, f'{path}[{index}]')
                elif a != b:
                    mismatches.append({'path': path, 'swift': a, 'kotlin': b})
            compare(swift, kotlin, 'frames')
            result = {'frames': len(selected), 'matching': not mismatches, 'maximumNumericDelta': maximum_delta,
                      'mismatchCount': len(mismatches), 'mismatches': mismatches,
                      'framesWithVisibleIDs': sum(bool(row['visibleIDs']) for row in swift),
                      'framesWithExpiredIDs': sum(bool(row['lanePresentation']['expiredTrackIds']) for row in swift),
                      'inputSha256': sha(input_path), 'swiftRecordsSha256': sha(arm_path/'swift.ndjson'),
                      'kotlinRecordsSha256': sha(output), 'swiftSourceHashes': metadata['sourceHashes'],
                      'flags': {key: manifest[key] for key in FLAGS}}
            report['arms'][arm] = result
            print(json.dumps({key: value for key, value in result.items() if key in ['frames', 'matching', 'maximumNumericDelta', 'mismatchCount']}))
    report['matching'] = all(arm['matching'] for arm in report['arms'].values())
    report['comparedFrames'] = sum(arm['frames'] for arm in report['arms'].values())
    (args.output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    if not report['matching']:
        raise SystemExit('Semantic mismatch; see summary.json')


if __name__ == '__main__':
    main()
