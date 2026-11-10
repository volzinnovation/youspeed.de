#!/usr/bin/env python3
"""Prepare an immutable paired CoreML benchmark without reading truth labels.

With no candidate artifact, stage verified common inputs and write only a
manifest.pending.json recipe. A runnable manifest.json is created only after
the compiled candidate, exact class order, RGB input and output contract pass.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil

from PIL import Image


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_sha(path):
    path = Path(path)
    entries = []
    for file in sorted(path.rglob('*')):
        assert not file.is_symlink(), 'Symbolic links are not model artifacts'
        if file.is_file():
            entries.append(file.relative_to(path).as_posix() + '\0' + sha(file) + '\n')
    assert entries, 'Empty model artifact'
    return hashlib.sha256(''.join(entries).encode()).hexdigest()


def contained(root, relative):
    relative = Path(relative)
    assert not relative.is_absolute() and '..' not in relative.parts
    resolved = (root / relative).resolve()
    assert resolved.is_relative_to(root.resolve())
    return resolved


def copy_verified(source, destination, expected, directory=False):
    digest = tree_sha if directory else sha
    assert digest(source) == expected, str(source)
    if destination.exists():
        assert digest(destination) == expected, 'Refusing to replace different staged content'
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if directory else shutil.copy2)(source, destination)
    assert digest(destination) == expected


def validate_coreml(path, classes):
    assert path.suffix == '.mlmodelc' and path.is_dir(), 'Precompile both models for equal load scope'
    metadata = json.loads((path / 'metadata.json').read_text())
    assert len(metadata) == 1
    metadata = metadata[0]
    assert metadata['classLabels'] == classes, 'Compiled CoreML class order differs'
    inputs = metadata['inputSchema']
    assert len(inputs) == 1
    image = inputs[0]
    assert image['type'] == 'Image' and image['name'] == 'image'
    assert image['width'] == image['height'] == '224' and image['colorspace'] == 'RGB'
    outputs = {row['name']: row for row in metadata['outputSchema']}
    assert outputs['classLabel']['type'] == 'String'
    assert outputs['classLabel_probs']['type'] == 'Dictionary'
    assert outputs['classLabel_probs']['keyType'] == 'String'
    return {'metadata_sha256': sha(path / 'metadata.json'),
            'class_count': len(classes), 'storage_precision': metadata['storagePrecision'],
            'input_schema': inputs, 'output_schema': metadata['outputSchema']}


def write(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture-manifest', type=Path, required=True)
    parser.add_argument('--predecessor-id', required=True)
    parser.add_argument('--candidate-id', required=True)
    parser.add_argument('--candidate-class-index', type=Path, required=True)
    parser.add_argument('--candidate-compiled', type=Path)
    parser.add_argument('--candidate-expected-tree-sha256')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    original = json.loads(args.fixture_manifest.read_text())
    classes = json.loads(args.candidate_class_index.read_text())['classes']
    assert classes and len(classes) == len(set(classes))
    assert original['schemaVersion'] == 1 and original['computeUnits'] == 'all'
    assert original['warmupCount'] == 20 and original['rounds'] == 3 and original['repeatsPerImage'] == 1
    predecessors = [m for m in original['models'] if m['id'] == args.predecessor_id]
    assert len(predecessors) == 1 and args.candidate_id != args.predecessor_id
    predecessor = copy.deepcopy(predecessors[0])
    assert classes[:predecessor['classCount']] == predecessor['classLabels'], 'Expanded head must preserve old order'
    source_root = args.fixture_manifest.parent
    predecessor_source = contained(source_root, predecessor['path'])
    predecessor_contract = validate_coreml(predecessor_source, predecessor['classLabels'])
    args.output.mkdir(parents=True, exist_ok=True)
    for row in original['images']:
        for field, hash_field in [('path', 'sha256'), ('canonicalPath', 'canonicalSha256')]:
            source = contained(source_root, row[field])
            destination = contained(args.output, row[field])
            copy_verified(source, destination, row[hash_field])
        with Image.open(contained(args.output, row['canonicalPath'])) as image:
            assert image.size == (224, 224) and image.format == 'PNG'
            assert hashlib.sha256(image.convert('RGB').tobytes()).hexdigest() == row['canonicalRGBSha256']
    predecessor['path'] = 'models/' + predecessor['id'] + '.mlmodelc'
    copy_verified(predecessor_source, contained(args.output, predecessor['path']), predecessor['sha256'], True)
    candidate = {'id': args.candidate_id, 'path': 'models/' + args.candidate_id + '.mlmodelc',
                 'classCount': len(classes), 'classLabels': classes}
    manifest = copy.deepcopy(original)
    manifest['models'] = [predecessor, candidate]
    receipt = {'status': 'awaiting_compiled_candidate', 'truth_labels_read': False,
               'source_fixture_manifest_sha256': sha(args.fixture_manifest),
               'candidate_class_index_sha256': sha(args.candidate_class_index),
               'script_sha256': sha(__file__), 'images': len(manifest['images']),
               'image_rows_identical_to_source': manifest['images'] == original['images'],
               'predecessor_contract': predecessor_contract, 'compute_units': 'all',
               'neural_engine_allowed': True, 'device_execution_performed': False}
    if args.candidate_compiled:
        contract = validate_coreml(args.candidate_compiled, classes)
        digest = tree_sha(args.candidate_compiled)
        if args.candidate_expected_tree_sha256:
            assert digest == args.candidate_expected_tree_sha256
        copy_verified(args.candidate_compiled, contained(args.output, candidate['path']), digest, True)
        candidate['sha256'] = digest
        manifest_path = args.output / 'manifest.json'
        if manifest_path.exists():
            assert json.loads(manifest_path.read_text()) == manifest, 'Refusing to replace frozen manifest'
        else:
            write(manifest_path, manifest)
        receipt.update({'status': 'ready_for_device_staging', 'candidate_contract': contract,
                        'candidate_compiled_tree_sha256': digest, 'manifest_sha256': sha(manifest_path)})
    else:
        assert not (args.output / 'manifest.json').exists(), 'Already finalized; do not downgrade to pending'
        write(args.output / 'manifest.pending.json', {
            'status': 'not_runnable_candidate_artifact_pending', 'recipe': manifest,
            'missing_fields': ['candidate model bytes', 'candidate model sha256'],
            'no_placeholder_hashes': True})
    write(args.output.parent / 'preparation-receipt.json', receipt)
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
