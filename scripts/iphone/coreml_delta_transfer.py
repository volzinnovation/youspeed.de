#!/usr/bin/env python3
"""Losslessly transfer related CoreML weights using a verified XOR delta.

Transport only: neither model bytes nor inference semantics are changed.
The reconstructed package must match the complete exporter file/tree receipt.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


WEIGHTS = 'Data/com.apple.CoreML/weights/weight.bin'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['create', 'restore'])
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--base-sha256', required=True)
    p.add_argument('--package', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--checkpoint-sha256', required=True)
    a = p.parse_args()
    base = a.base.read_bytes()
    assert sha(base) == a.base_sha256, 'Base weights differ'
    if a.mode == 'create':
        assert not a.archive.exists(), 'Refusing to replace transport archive'
        report_bytes = a.report.read_bytes()
        report = json.loads(report_bytes)
        assert report['checkpoint_sha256'] == a.checkpoint_sha256
        new = (a.package / WEIGHTS).read_bytes()
        for row in report['files']:
            value = (a.package / row['path']).read_bytes()
            assert len(value) == row['bytes'] and sha(value) == row['sha256']
        delta = bytes(v ^ (base[i] if i < len(base) else 0) for i, v in enumerate(new))
        manifest = {'schema': 'coreml-lossless-xor-transport-v1',
                    'base_sha256': sha(base), 'base_bytes': len(base),
                    'target_sha256': sha(new), 'target_bytes': len(new),
                    'checkpoint_sha256': a.checkpoint_sha256,
                    'report_sha256': sha(report_bytes), 'tree_sha256': report['tree_sha256']}
        with zipfile.ZipFile(a.archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.writestr('transport.json', json.dumps(manifest, indent=2) + '\n')
            z.writestr('export-report.json', report_bytes)
            z.writestr('weights.xor', delta)
            for row in report['files']:
                if row['path'] != WEIGHTS:
                    z.writestr('package/' + row['path'], (a.package / row['path']).read_bytes())
        print(json.dumps({'archive': str(a.archive), 'bytes': a.archive.stat().st_size,
                          'sha256': sha(a.archive.read_bytes()), **manifest}))
    else:
        assert not a.package.exists(), 'Require a fresh reconstructed package'
        with zipfile.ZipFile(a.archive) as z:
            manifest = json.loads(z.read('transport.json'))
            assert manifest['schema'] == 'coreml-lossless-xor-transport-v1'
            assert manifest['checkpoint_sha256'] == a.checkpoint_sha256
            assert manifest['base_sha256'] == sha(base)
            report_bytes = z.read('export-report.json')
            assert sha(report_bytes) == manifest['report_sha256']
            report = json.loads(report_bytes)
            assert report['checkpoint_sha256'] == a.checkpoint_sha256
            assert report['tree_sha256'] == manifest['tree_sha256']
            delta = z.read('weights.xor')
            assert len(delta) == manifest['target_bytes']
            new = bytes(v ^ (base[i] if i < len(base) else 0) for i, v in enumerate(delta))
            assert sha(new) == manifest['target_sha256']
            files = {}
            for row in report['files']:
                path = Path(row['path'])
                assert not path.is_absolute() and '..' not in path.parts
                value = new if row['path'] == WEIGHTS else z.read('package/' + row['path'])
                assert len(value) == row['bytes'] and sha(value) == row['sha256']
                files[row['path']] = value
        tree = ''.join(name + '\0' + sha(value) + '\n' for name, value in sorted(files.items()))
        assert sha(tree.encode()) == report['tree_sha256']
        for name, value in files.items():
            path = a.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        a.report.write_bytes(report_bytes)
        print(json.dumps({'status': 'restored_exact_export', 'tree_sha256': report['tree_sha256'],
                          'archive_sha256': sha(a.archive.read_bytes()), 'package': str(a.package)}))


if __name__ == '__main__':
    main()
