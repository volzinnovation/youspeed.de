#!/usr/bin/env python3
"""Explicit, headless Moto replay of an existing recording; preserves user data."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--serial', required=True)
p.add_argument('--input', required=True, type=Path, help='Private locally prepared replay manifest')
p.add_argument('--run-id', required=True, help='Unique letters/digits/underscores/hyphens')
p.add_argument('--start', type=float, default=0)
p.add_argument('--end', type=float, default=646.6)
p.add_argument('--interval', type=float, default=.5)
p.add_argument('--install', action='store_true', help='Update already-built app/test APKs with install -r')
a = p.parse_args()
if not re.fullmatch(r'[A-Za-z0-9_-]+', a.run_id):
    p.error('run-id must contain only letters, digits, underscores, or hyphens')
if not (0 <= a.start < a.end and a.interval >= .1):
    p.error('Require 0 <= start < end and interval >= .1')
android = Path(__file__).resolve().parents[1]
out = android / 'app/build/reports/road-path/recorded-replay' / a.run_id
if out.exists():
    p.error('Output run already exists; use a new run-id')
manifest = json.loads(a.input.read_text())
if Path(manifest['videoFile']).name != manifest['videoFile']:
    p.error('Manifest videoFile must be an existing dashcam basename')
adb = ['adb', '-s', a.serial]
app = 'de.youspeed.android.debug'
test = app + '.test'

def command(*parts, **kwargs):
    return subprocess.run(adb + list(parts), check=True, **kwargs)

def read(*parts):
    return command(*parts, stdout=subprocess.PIPE).stdout

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024*1024):
            h.update(chunk)
    return h.hexdigest()

model = read('shell', 'getprop', 'ro.product.model').decode().strip()
if 'g86' not in model.lower():
    raise SystemExit('Selected device must be the authorized Moto g86')
out.mkdir(parents=True)
# Do not replace an app while its selected recording/photo consumer is active.
before = read('exec-out', 'run-as', app, 'cat', 'files/bundle/logs/runtime_diagnostics.ndjson')
(out / 'before-runtime-diagnostics.ndjson').write_bytes(before)
recording = None
configuration = None
for line in before.splitlines():
    try:
        row = json.loads(line)
        if row.get('event') == 'capture_configuration':
            configuration = row
        if row.get('event') == 'tsr_path_recording_v1':
            payload = row.get('evidenceJSON', row.get('evidence'))
            recording = json.loads(payload) if isinstance(payload, str) else payload
    except (ValueError, TypeError):
        continue
if not configuration:
    raise SystemExit('Cannot verify capture state from the existing log; inspect device before replay')
if (recording and recording.get('event') in ('start', 'progress')) or (
        configuration.get('driving') and configuration.get('applicationActive') and
        (configuration.get('dashcamEnabled') or configuration.get('photosEnabled'))):
    raise SystemExit('A capture consumer may be active; replay did not install or start')

apks = [(app, android/'app/build/outputs/apk/debug/app-debug.apk'),
        (test, android/'app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk')]
if a.install:
    for package, apk in apks:
        with (out / (package + '-install.txt')).open('wb') as log:
            command('install', '-r', str(apk), stdout=log, stderr=subprocess.STDOUT)
verification = {}
for package, apk in apks:
    remote = read('shell', 'pm', 'path', package).decode().strip().removeprefix('package:')
    installed_hash = read('shell', 'sha256sum', remote).decode().split()[0]
    local_hash = sha(apk)
    if local_hash != installed_hash:
        raise SystemExit('Installed APK differs from local build; rebuild and explicitly use --install')
    verification[package] = {'localSha256':local_hash, 'installedSha256':installed_hash, 'matches':True}
(out/'installed-apk-verification.json').write_text(json.dumps(verification, indent=2)+'\n')
command('shell', 'run-as', app, 'mkdir', '-p', 'cache/recorded-road-path-replay')
with a.input.open('rb') as stream:
    command('shell', 'run-as', app, 'tee', 'cache/recorded-road-path-replay/input.json',
            stdin=stream, stdout=subprocess.DEVNULL)
(out/'thermal-before.txt').write_bytes(read('shell', 'dumpsys', 'thermalservice'))
(out/'memory-before.txt').write_bytes(read('shell', 'dumpsys', 'meminfo', app))
print(f'{model}: replay {a.start:g}–{a.end:g}s every {a.interval:g}s; output {out}', flush=True)
try:
    with (out/'instrumentation.txt').open('wb') as log:
        command('shell', 'am', 'instrument', '-w', '-r',
                '-e', 'class', 'de.youspeed.android.alpha.RecordedRoadPathReplayInstrumentedTest',
                '-e', 'replay_run_id', a.run_id, '-e', 'replay_start_seconds', str(a.start),
                '-e', 'replay_end_seconds', str(a.end), '-e', 'replay_interval_seconds', str(a.interval),
                test+'/androidx.test.runner.AndroidJUnitRunner', stdout=log, stderr=subprocess.STDOUT)
finally:
    remote_dir = 'cache/recorded-road-path-replay/'+a.run_id
    files = read('shell', 'run-as', app, 'ls', remote_dir).decode().splitlines()
    for name in files:
        if name in ('summary.json', 'frames.ndjson') or re.fullmatch(r'first-frame-\d+\.png', name):
            (out/name).write_bytes(read('exec-out', 'run-as', app, 'cat', remote_dir+'/'+name))
    (out/'thermal-after.txt').write_bytes(read('shell', 'dumpsys', 'thermalservice'))
    (out/'memory-after.txt').write_bytes(read('shell', 'dumpsys', 'meminfo', app))
report = json.loads((out/'summary.json').read_text())
transcript = (out/'instrumentation.txt').read_text()
if report.get('runId') != a.run_id or not report.get('completed') or 'OK (1 test)' not in transcript:
    raise SystemExit('Replay did not complete successfully; retain partial artifacts for inspection')
print(json.dumps({key:report.get(key) for key in ['completed','selectedFrames','elapsedWallSeconds',
    'gpuFrames','addedPathDeadlineMisses','framesWithSigns','framesWithBoundaries']}, indent=2))
