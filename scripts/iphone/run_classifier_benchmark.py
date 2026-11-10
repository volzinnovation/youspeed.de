#!/usr/bin/env python3
"""Stage and run the isolated GPU classifier benchmark on a connected iPhone.

The production YouSpeed app, models and data are not touched. Build/sign the
separate iphone/ClassifierBenchmark target first. This runner never changes
device trust or lock state and never substitutes simulator timings.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

BUNDLE = 'de.youspeed.ClassifierBenchmark'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--app', type=Path, help='Optional signed isolated app to install')
    parser.add_argument('--timeout', type=float, default=900)
    parser.add_argument('--reverse-model-order', action='store_true')
    parser.add_argument('--stage-only', action='store_true', help='Prepare inputs without launching a locked phone')
    parser.add_argument('--already-staged', action='store_true')
    parser.add_argument('--wait-unlock', type=float, default=0, help='Seconds to wait for the user to unlock; never unlocks the device itself')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run_id):
        raise SystemExit('Run identifier must be alphanumeric, underscore or hyphen')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = args.input_dir / 'manifest.json'
    value = json.loads(manifest.read_text())
    assert value['schemaVersion'] == 1 and value['images'] and value['models']
    mode = value.get('computeUnits', 'cpuAndGPU')
    assert mode in ('cpuAndGPU', 'all')
    package = 'BenchmarkInputs-' + args.run_id
    receipts = []

    def call(name, arguments, timeout=60, tolerate=False):
        target = args.output_dir / (name + '.json')
        command = ['xcrun', 'devicectl', '--timeout', str(timeout), '--json-output', str(target), *arguments]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout + 10)
        (args.output_dir / (name + '.log')).write_text(result.stdout)
        receipts.append({'name': name, 'arguments': arguments, 'exit_code': result.returncode})
        if result.returncode and not tolerate:
            raise RuntimeError(f'{name} failed; inspect {name}.log. ' + result.stdout[-1800:])
        return result.returncode == 0

    if args.app:
        if args.app.name != 'ClassifierBenchmark.app':
            raise SystemExit('Only the isolated ClassifierBenchmark.app may be installed by this runner')
        call('install', ['device', 'install', 'app', '--device', args.device, str(args.app)], 120)
    call('device', ['device', 'info', 'details', '--device', args.device], 30)
    if not args.already_staged:
        call('stage', ['device', 'copy', 'to', '--device', args.device, '--source', str(args.input_dir),
                       '--destination', 'Documents/' + package, '--domain-type', 'appDataContainer',
                       '--domain-identifier', BUNDLE], 180)
    if args.stage_only:
        (args.output_dir / 'staging-receipt.json').write_text(json.dumps({
            'status': 'staged_not_launched', 'package': package, 'manifest_sha256': sha(manifest),
            'commands': receipts, 'production_bundle_modified': False}, indent=2) + '\n')
        print(json.dumps({'status': 'staged_not_launched', 'package': package}))
        return
    if args.wait_unlock:
        unlock_deadline = time.monotonic() + args.wait_unlock
        while True:
            call('lock-state', ['device', 'info', 'lockState', '--device', args.device], 20)
            state = json.loads((args.output_dir / 'lock-state.json').read_text())['result']
            if state.get('passcodeRequired') is False:
                print(json.dumps({'status': 'device_unlocked_launching'}), flush=True)
                break
            if time.monotonic() >= unlock_deadline:
                raise TimeoutError('iPhone is still locked; benchmark has not been launched')
            time.sleep(5)
    launch = ['device', 'process', 'launch', '--device', args.device, '--terminate-existing', BUNDLE,
              '--package=' + package, '--run-id=' + args.run_id]
    if args.reverse_model_order:
        launch.append('--reverse-model-order')
    call('launch', launch, 35)
    deadline = time.monotonic() + args.timeout
    result_path = args.output_dir / 'result.json'
    error_path = args.output_dir / 'error.json'
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        if call(f'fetch-result-{attempt}', ['device', 'copy', 'from', '--device', args.device,
                '--source', f'Documents/benchmark-{args.run_id}.json', '--destination', str(result_path),
                '--domain-type', 'appDataContainer', '--domain-identifier', BUNDLE], 20, True):
            result = json.loads(result_path.read_text())
            assert result['status'] == 'complete' and result['manifest_sha256'] == sha(manifest)
            assert result['device']['simulator'] is False
            assert all(b['requested_compute_units'] == mode and b['neural_engine_allowed'] == (mode == 'all') for b in result['blocks'])
            receipt = {'status': 'complete', 'manifest_sha256': sha(manifest), 'result_sha256': sha(result_path),
                       'runner_sha256': sha(__file__), 'requested_compute_units': mode,
                       'neural_engine_allowed': mode == 'all', 'commands': receipts, 'production_bundle_modified': False}
            (args.output_dir / 'execution-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            print(json.dumps({'status': 'complete', 'result': str(result_path), 'blocks': len(result['blocks'])}))
            return
        if call(f'fetch-error-{attempt}', ['device', 'copy', 'from', '--device', args.device,
                '--source', f'Documents/benchmark-{args.run_id}-error.json', '--destination', str(error_path),
                '--domain-type', 'appDataContainer', '--domain-identifier', BUNDLE], 20, True):
            raise RuntimeError(error_path.read_text())
        if attempt % 3 == 0:
            progress = args.output_dir / 'progress.json'
            if call(f'fetch-progress-{attempt}', ['device', 'copy', 'from', '--device', args.device,
                    '--source', f'Documents/benchmark-{args.run_id}-progress.json', '--destination', str(progress),
                    '--domain-type', 'appDataContainer', '--domain-identifier', BUNDLE], 20, True):
                print(progress.read_text(), flush=True)
        time.sleep(5)
    raise TimeoutError('Device benchmark did not finish within the configured deadline; no timing result claimed')


if __name__ == '__main__':
    main()
