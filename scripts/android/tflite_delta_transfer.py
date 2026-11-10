#!/usr/bin/env python3
"""Lossless hash-bound TFLite transport, including unequal artifact lengths."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def sha(value):
    return hashlib.sha256(value).hexdigest()


def xor(value, base):
    # Only target-length bytes are reconstructed. Missing base bytes are zero;
    # unused trailing base bytes are discarded when the target is shorter.
    return bytes(v ^ (base[i] if i < len(base) else 0) for i, v in enumerate(value))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['create', 'restore'])
    for name in ['base', 'target', 'report', 'archive']:
        p.add_argument('--'+name, type=Path, required=True)
    for name in ['base-sha256', 'target-sha256', 'checkpoint-sha256']:
        p.add_argument('--'+name, required=True)
    a = p.parse_args()
    base = a.base.read_bytes()
    assert sha(base) == a.base_sha256, 'Base artifact differs'
    if a.mode == 'create':
        assert not a.archive.exists(), 'Keep transport archives immutable'
        target = a.target.read_bytes()
        report_bytes = a.report.read_bytes()
        report = json.loads(report_bytes)
        assert report['format'] == 'tflite'
        assert report['checkpoint_sha256'] == a.checkpoint_sha256
        assert sha(target) == report['artifact_sha256'] == a.target_sha256
        assert len(target) == report['artifact_bytes']
        contract = {'schema':'tflite-lossless-xor-transport-v1', 'base_sha256':sha(base),
                    'base_bytes':len(base), 'target_sha256':sha(target), 'target_bytes':len(target),
                    'checkpoint_sha256':a.checkpoint_sha256, 'report_sha256':sha(report_bytes),
                    'length_policy':'XOR target bytes against base prefix; zero-pad missing base and truncate unused base suffix.'}
        a.archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(a.archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.writestr('transport.json', json.dumps(contract, indent=2)+'\n')
            z.writestr('export-report.json', report_bytes)
            z.writestr('artifact.xor', xor(target, base))
        print(json.dumps({'archive':str(a.archive), 'bytes':a.archive.stat().st_size,
                          'sha256':sha(a.archive.read_bytes()), **contract}))
    else:
        assert not a.target.exists() and not a.report.exists(), 'Require fresh restored artifact and receipt'
        with zipfile.ZipFile(a.archive) as z:
            contract = json.loads(z.read('transport.json'))
            assert contract['schema'] == 'tflite-lossless-xor-transport-v1'
            assert contract['base_sha256'] == a.base_sha256 and contract['base_bytes'] == len(base)
            assert contract['target_sha256'] == a.target_sha256 and contract['checkpoint_sha256'] == a.checkpoint_sha256
            report_bytes = z.read('export-report.json')
            assert sha(report_bytes) == contract['report_sha256']
            report = json.loads(report_bytes)
            assert report['format'] == 'tflite' and report['checkpoint_sha256'] == a.checkpoint_sha256
            delta = z.read('artifact.xor')
            assert len(delta) == contract['target_bytes'] == report['artifact_bytes']
            target = xor(delta, base)
            assert len(target) == contract['target_bytes']
            assert sha(target) == contract['target_sha256'] == report['artifact_sha256']
        a.target.parent.mkdir(parents=True, exist_ok=True)
        a.target.write_bytes(target)
        a.report.write_bytes(report_bytes)
        print(json.dumps({'status':'restored_exact_export','artifact_sha256':sha(target),
                          'artifact_bytes':len(target),'base_bytes':len(base),
                          'archive_sha256':sha(a.archive.read_bytes())}))


if __name__ == '__main__': main()
