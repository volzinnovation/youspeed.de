#!/usr/bin/env python3
"""Fetch one hash-pinned artifact via bounded resumable SSH range reads."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import time


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', required=True)
    p.add_argument('--identity', type=Path, required=True)
    p.add_argument('--remote-path', required=True)
    p.add_argument('--bytes', type=int, required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--chunk-bytes', type=int, default=256 * 1024)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    contract = {'remote_path': a.remote_path, 'bytes': a.bytes, 'sha256': a.sha256,
                'chunk_bytes': a.chunk_bytes, 'host': a.host}
    contract_path = a.output / 'contract.json'
    if contract_path.exists():
        assert json.loads(contract_path.read_text()) == contract
    else:
        contract_path.write_text(json.dumps(contract, indent=2) + '\n')
    jobs = [(i, offset, min(a.chunk_bytes, a.bytes - offset))
            for i, offset in enumerate(range(0, a.bytes, a.chunk_bytes))]
    def fetch(job):
        i, offset, size = job
        target = a.output / f'part-{i:03d}.bin'
        receipt_path = target.with_suffix('.json')
        if target.exists() and receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            data = target.read_bytes()
            assert len(data) == size and digest(data) == receipt['sha256']
            return receipt
        partial = target.with_suffix('.partial')
        data = partial.read_bytes() if partial.exists() else b''
        assert len(data) <= size
        started = time.monotonic()
        for attempt in range(1, 9):
            remaining = size - len(data)
            if remaining == 0:
                break
            script = ('import sys;f=open(' + repr(a.remote_path) + ',"rb");'
                      + f'f.seek({offset + len(data)});sys.stdout.buffer.write(f.read({remaining}))')
            command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                       '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
                       '-o', 'ControlPath=none', '-o', 'IPQoS=none', '-i', str(a.identity),
                       a.host, 'python3 -c ' + shlex.quote(script)]
            try:
                result = subprocess.run(command, capture_output=True, timeout=40, check=True)
                if len(result.stdout) != remaining:
                    raise ValueError('Truncated range')
                data += result.stdout
                break
            except (subprocess.SubprocessError, ValueError) as exc:
                received = getattr(exc, 'output', None) or b''
                assert len(received) <= remaining
                data += received
                partial.write_bytes(data)
                print(json.dumps({'status': 'retry', 'part': i, 'attempt': attempt,
                                  'error': type(exc).__name__, 'received_bytes': len(received),
                                  'resumable_prefix_bytes': len(data)}), flush=True)
                if attempt == 8 and len(data) != size:
                    raise
        assert len(data) == size
        receipt = {'part': i, 'offset': offset, 'bytes': size,
                   'sha256': digest(data), 'seconds': time.monotonic()-started,
                   'attempt': attempt}
        target.write_bytes(data)
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        partial.unlink(missing_ok=True)
        print(json.dumps({'status': 'chunk_complete', **receipt}), flush=True)
        return receipt
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = [future.result() for future in as_completed([pool.submit(fetch, job) for job in jobs])]
    full = b''.join((a.output / f'part-{i:03d}.bin').read_bytes() for i, _, _ in jobs)
    assert len(full) == a.bytes and digest(full) == a.sha256, 'Complete remote artifact digest differs'
    (a.output / 'verified-artifact.bin').write_bytes(full)
    report = {'status': 'complete_exact_hash', **contract,
              'chunks': sorted(receipts, key=lambda row: row['part'])}
    (a.output / 'complete.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'bytes': a.bytes, 'sha256': a.sha256}), flush=True)


if __name__ == '__main__':
    main()
