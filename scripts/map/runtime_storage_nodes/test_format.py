#!/usr/bin/env python3
"""Executable corruption tests for the native reader; source data stays untouched."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import tempfile

def test(directory, executable):
    original = (directory / 'nodes.yspn').read_bytes()
    _, ro, oo, bo, _ = struct.unpack_from('<QQQQQ', original, 16)
    first_id = struct.unpack_from('<q', original, ro)[0]
    cases = {}
    with tempfile.TemporaryDirectory(prefix='ysp-node-format-') as scratch:
        path = Path(scratch) / 'corrupt.yspn'
        for name, offset in [('header', 24), ('directory', ro + 8), ('id_index', oo), ('metadata', bo + 2)]:
            data = bytearray(original)
            data[offset] ^= 0x55
            path.write_bytes(data)
            run = subprocess.run([str(executable), 'node', 'packed', str(path), str(first_id)], text=True, capture_output=True)
            result = json.loads(run.stdout)
            assert run.returncode != 0 and result.get('error'), (name, run.stdout)
            cases[name] = result['error']
        path.write_bytes(original[:80])
        run = subprocess.run([str(executable), 'roundtrip', 'packed', str(path)], text=True, capture_output=True)
        result = json.loads(run.stdout)
        assert run.returncode != 0 and result.get('error')
        cases['truncated'] = result['error']
    result = {'schema': 1, 'corrupt_formats_rejected': len(cases), 'cases': cases}
    (directory / 'format-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('directory', type=Path)
    p.add_argument('executable', type=Path)
    a = p.parse_args()
    test(a.directory, a.executable)
