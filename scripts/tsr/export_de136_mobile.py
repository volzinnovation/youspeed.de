#!/usr/bin/env python3
"""Convert a hash-pinned DE136 classifier for isolated native benchmarking."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--classes', type=Path, required=True)
    parser.add_argument('--format', choices=['coreml', 'tflite'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or sha(args.model) != args.sha256:
        raise ValueError('Require new output directory and exact verified checkpoint')
    from ultralytics import YOLO
    import torch
    import ultralytics
    classes = json.loads(args.classes.read_text())['classes']
    if len(classes) != 136 or classes[-2:] != ['city:start', 'city:end']:
        raise ValueError('Unexpected class contract')
    if ultralytics.__version__ != '8.4.56':
        raise ValueError('Use the established Ultralytics8.4.56 export recipe')
    args.output.mkdir(parents=True)
    local_model = args.output / args.model.name
    shutil.copy2(args.model, local_model)
    model = YOLO(str(local_model), task='classify')
    if [model.names[i] for i in range(len(model.names))] != classes:
        raise ValueError('Checkpoint class order differs from manifest')
    torch.set_num_threads(4)
    exported = Path(model.export(format=args.format, imgsz=224, batch=1, half=True,
                                 nms=False, device='cpu', dynamic=False))
    if not exported.exists():
        raise ValueError('Native export was not produced')
    paths = sorted(p for p in exported.rglob('*') if p.is_file()) if exported.is_dir() else [exported]
    files = [{'path': p.relative_to(exported).as_posix() if exported.is_dir() else p.name,
              'sha256': sha(p), 'bytes': p.stat().st_size} for p in paths]
    tree_digest = hashlib.sha256(''.join(r['path'] + '\0' + r['sha256'] + '\n' for r in files).encode()).hexdigest()
    versions = {}
    for package in ['torch', 'ultralytics', 'coremltools', 'onnx', 'onnx2tf', 'tensorflow', 'ai-edge-litert', 'numpy']:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'format': args.format,
              'script_sha256': sha(__file__), 'checkpoint_sha256': sha(args.model),
              'class_index_sha256': sha(args.classes), 'classes': classes,
              'configuration': {'imgsz': 224, 'batch': 1, 'half': True, 'nms': False, 'dynamic': False},
              'export_path': str(exported), 'files': files, 'tree_sha256': tree_digest,
              'artifact_sha256': sha(exported) if exported.is_file() else tree_digest,
              'artifact_bytes': sum(f['bytes'] for f in files), 'versions': versions,
              'conversion_host_execution': 'CPU conversion tooling; not an inference benchmark',
              'target_execution': 'CoreML cpuAndGPU' if args.format == 'coreml' else 'LiteRT GPU delegate',
              'native_parity_pending': True, 'device_measurement_pending': True, 'deployed': False}
    (args.output / 'export-report.json').write_text(json.dumps(report, indent=2) + '\n')
    (args.output / 'executed-export.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({k: report[k] for k in ['format', 'export_path', 'artifact_sha256', 'artifact_bytes']}), flush=True)


if __name__ == '__main__':
    main()
