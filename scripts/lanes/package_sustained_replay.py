#!/usr/bin/env python3
"""Package existing reduced luma manifests for opt-in device component replay.

Never contacts a device or installs an app. Copies exactly the supplied pixels and
calibration metadata; does not fabricate GNSS, calibration, labels, or exposures.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

VARIANTS = ['baseline', 'bands', 'fragments', 'bands_fragments', 'fragments_tracking', 'bands_fragments_tracking']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', action='append', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--seconds-per-arm', type=float, default=180)
    parser.add_argument('--variants', nargs='+', choices=VARIANTS, default=VARIANTS)
    args = parser.parse_args()
    if not args.run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.run_id):
        parser.error('run-id must use ASCII letters, digits, underscore or hyphen')
    if not 1 <= args.seconds_per_arm <= 300:
        parser.error('seconds-per-arm must be in [1, 300]; values below 180 are smoke tests only')
    if args.output.exists():
        parser.error('output must be new; existing evidence is never overwritten')
    frames = []
    sources = []
    args.output.mkdir(parents=True)
    for manifest_index, path in enumerate(args.manifest):
        payload = path.read_bytes()
        sources.append({'path': str(path.resolve()), 'sha256': hashlib.sha256(payload).hexdigest()})
        for index, frame in enumerate(json.loads(payload)['frames']):
            source = Path(frame.get('grayPath', frame.get('file', '')))
            if not source.is_absolute():
                source = path.parent / source
            pixels = source.read_bytes()
            width, height = int(frame['width']), int(frame['height'])
            if not (64 <= width <= 384 and 64 <= height <= 216 and len(pixels) == width * height):
                raise ValueError(f'invalid reduced luma: {source}')
            digest = hashlib.sha256(pixels).hexdigest()
            expected = frame.get('graySha256', frame.get('rawSha256'))
            if expected and expected != digest:
                raise ValueError(f'luma SHA mismatch: {source}')
            filename = f'{manifest_index:02d}-{index:05d}.gray'
            shutil.copyfile(source, args.output / filename)
            row = {key: value for key, value in frame.items() if key not in ('grayPath', 'file')}
            time = frame.get('time', frame.get('actualVideoSeconds'))
            if time is None:
                time = frame['actualPtsValue'] / frame['actualPtsTimescale']
            row.update(file=filename, rawSha256=digest, time=time, width=width, height=height,
                       sequenceId=f"{manifest_index}:{frame['sequenceId']}",
                       decodedWidth=frame.get('decodedWidth', width), decodedHeight=frame.get('decodedHeight', height))
            frames.append(row)
    if not 1 <= len(frames) <= 5000:
        raise ValueError('device metadata cap is 5000 frames')
    manifest = {'schemaVersion': 1, 'sourceManifests': sources, 'frames': frames}
    (args.output / 'input.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (args.output / 'config.json').write_text(json.dumps({
        'runId': args.run_id, 'secondsPerArm': args.seconds_per_arm, 'variants': args.variants, 'fps': 10,
        'scope': 'Paced lane component replay only; no camera, TSR, recorder, renderer or GNSS injection.'
    }, indent=2) + '\n')
    print(json.dumps({'directory': str(args.output.resolve()), 'frames': len(frames),
                      'secondsPerArm': args.seconds_per_arm, 'variants': args.variants}))


if __name__ == '__main__':
    main()
