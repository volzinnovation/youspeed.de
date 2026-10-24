#!/usr/bin/env python3
"""Package existing, hash-pinned shared artwork for the local MobiData v1.5 pilot.

This adds review assets only. It never edits the bundle database, outer manifest,
the shared artwork registry, or any recognition/display eligibility decisions.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / 'docs/MOBIDATA_BW_PICTOGRAM_AUDIT_V1_5.json'
MANIFEST = ROOT / 'shared/tsr/sign-pictograms/manifest.json'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def pinned_file(base, relative, expected_hash, required_directory, suffix):
    """Accept only ordinary relative manifest paths inside the expected asset set."""
    path = PurePosixPath(relative)
    if (path.is_absolute() or '..' in path.parts or len(path.parts) != 2
            or path.parts[0] != required_directory or path.suffix != suffix
            or '\\' in relative):
        raise ValueError(f'Unsafe artwork path: {relative!r}')
    source = base.joinpath(*path.parts)
    if not source.resolve().is_relative_to(base.resolve()):
        raise ValueError(f'Artwork path escapes shared directory: {relative!r}')
    data = source.read_bytes()
    if sha256(data) != expected_hash:
        raise ValueError(f'Artwork hash mismatch: {relative}')
    return path, data


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def package_artwork(bundle_dir, audit_path=AUDIT, manifest_path=MANIFEST):
    bundle_dir, audit_path, manifest_path = map(Path, (bundle_dir, audit_path, manifest_path))
    if not bundle_dir.is_dir():
        raise ValueError('Bundle directory must already exist')
    audit_bytes, manifest_bytes = audit_path.read_bytes(), manifest_path.read_bytes()
    audit, manifest = json.loads(audit_bytes), json.loads(manifest_bytes)
    if audit.get('schema_version') != 1 or not isinstance(audit.get('entries'), list):
        raise ValueError('Expected v1 pictogram audit entries')
    artworks = {}
    for artwork in manifest['artworks']:
        key = artwork['sign_code']
        if key in artworks:
            raise ValueError(f'Duplicate shared artwork key: {key}')
        artworks[key] = artwork
    entries = audit['entries']
    if len({entry['source_code'] for entry in entries}) != len(entries):
        raise ValueError('Duplicate source code in pictogram audit')
    if any(type(entry['count']) is not int or entry['count'] <= 0 for entry in entries):
        raise ValueError('Audit counts must be positive integers')
    if sum(entry['count'] for entry in entries) != audit['source']['record_count']:
        raise ValueError('Audit record counts do not reconcile')

    selected, payloads = {}, {}
    for entry in entries:
        key = entry['pictogram_key']
        if key is None:
            if entry['pictogram_original_path'] is not None or entry['pictogram_png_path'] is not None:
                raise ValueError('Unmapped artwork cannot carry asset paths')
            continue
        if key not in artworks:
            raise ValueError(f'Unknown shared artwork key: {key}')
        artwork = artworks[key]
        for field, hash_field, subdir, extension, audit_field in [
            ('original_path', 'original_sha256', 'originals', '.svg', 'pictogram_original_path'),
            ('png_path', 'png_sha256', 'png', '.png', 'pictogram_png_path'),
        ]:
            if entry[audit_field] != 'shared/tsr/sign-pictograms/' + artwork[field]:
                raise ValueError(f'Audit asset path disagrees with shared manifest: {entry["source_code"]}')
            path, data = pinned_file(manifest_path.parent, artwork[field], artwork[hash_field], subdir, extension)
            if str(path) in payloads and payloads[str(path)] != data:
                raise ValueError(f'Conflicting asset bytes: {path}')
            payloads[str(path)] = data
        selected[key] = artwork

    status_codes = Counter(entry['pictogram_status'] for entry in entries)
    status_records = Counter()
    classifier_codes = Counter(entry['classifier_capability'] for entry in entries)
    classifier_records = Counter()
    for entry in entries:
        status_records[entry['pictogram_status']] += entry['count']
        classifier_records[entry['classifier_capability']] += entry['count']
    coverage = {
        'schema_version': 1,
        'purpose': 'Existing review artwork only; packaging does not enable display, recognition or runtime actions.',
        'source_snapshot_sha256': audit['source']['sha256'],
        'audit_sha256': sha256(audit_bytes),
        'shared_manifest_sha256': sha256(manifest_bytes),
        'source_code_count': len(entries),
        'source_record_count': sum(entry['count'] for entry in entries),
        'packaged_pair_count': len(selected),
        'packaged_sign_codes': sorted(selected),
        'status_source_code_counts': dict(sorted(status_codes.items())),
        'status_record_counts': dict(sorted(status_records.items())),
        'classifier_source_code_counts': dict(sorted(classifier_codes.items())),
        'classifier_record_counts': dict(sorted(classifier_records.items())),
        'visual_confirmation_limitations': [
            {field: entry[field] for field in ['source_code', 'count', 'classifier_capability', 'notes']}
            for entry in entries if entry['classifier_capability'] != 'exact_label'
        ],
        'missing_or_blocked_entries': [
            {field: entry[field] for field in ['source_code', 'count', 'pictogram_status', 'display_eligible',
                                               'classifier_capability', 'notes']}
            for entry in entries if not entry['display_eligible']
        ],
    }
    subset = {**manifest, 'artworks': [selected[key] for key in sorted(selected)]}
    notices = (manifest_path.parent / 'THIRD_PARTY_NOTICES.txt').read_bytes()
    destination = bundle_dir / 'sign-pictograms'
    audit_destination = bundle_dir / 'pictogram-audit.json'
    if destination.is_symlink() or audit_destination.is_symlink():
        raise ValueError('Refusing to replace symlink package output')

    # Prepare and verify every input before replacing this script's own outputs.
    # A repeat run replaces its asset tree, removing stale files deterministically.
    with tempfile.TemporaryDirectory(prefix='.pictogram-package-', dir=bundle_dir) as temporary:
        staging = Path(temporary) / 'sign-pictograms'
        staging.mkdir()
        for relative, data in payloads.items():
            target = staging / relative
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(data)
        (staging / 'manifest.json').write_bytes(json_bytes(subset))
        (staging / 'coverage.json').write_bytes(json_bytes(coverage))
        (staging / 'THIRD_PARTY_NOTICES.txt').write_bytes(notices)
        staged_audit = Path(temporary) / 'pictogram-audit.json'
        staged_audit.write_bytes(audit_bytes)
        previous = Path(temporary) / 'previous'
        if destination.exists():
            os.replace(destination, previous)
        try:
            os.replace(staging, destination)
        except BaseException:
            if previous.exists():
                os.replace(previous, destination)
            raise
        os.replace(staged_audit, audit_destination)
    return coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-dir', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(package_artwork(args.bundle_dir), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
