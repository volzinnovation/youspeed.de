#!/usr/bin/env python3
"""Refresh an obsolete noncanonical region alias from a verified packed draft.

The four immutable data-builder files and every packed data byte are reused.
Only artifact/self URLs and explicit alias-refresh provenance change in the
manifest. The historical V3 source remains available at its original release.
"""
import argparse
import copy
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct
import subprocess
import tempfile
import time
from urllib.parse import unquote, urlparse
import zlib

from packed_runtime import digest, require

SHA = re.compile(r'[0-9a-f]{64}')
TAG = re.compile(r'[a-z0-9][a-z0-9._-]*')
BUILDER_NAMES = ['build_packed_release.py', 'packed_runtime.py',
                 'extract_packed_sign_nodes.py', 'pack_sign_nodes.py']
PROOF_FLAGS = ['all_original_logical_table_counts_preserved',
               'original_metadata_values_preserved', 'every_original_geometry_text_exact']


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def safe_name(name):
    require(isinstance(name, str) and name not in ('', '.', '..') and
            Path(name).name == name and '\\' not in name and '\0' not in name,
            'Unsafe release asset filename')
    return name


def sha256_asset(asset):
    value = asset.get('digest', '')
    require(isinstance(value, str) and value.startswith('sha256:') and
            SHA.fullmatch(value[7:]), 'Missing GitHub server asset SHA-256')
    require(type(asset.get('size')) is int and asset['size'] > 0 and
            type(asset.get('id')) is int and asset['id'] > 0, 'Invalid GitHub asset metadata')
    safe_name(asset['name'])
    return value[7:]


class GitHub:
    def release(self, repo, tag):
        # REST releases/tags hides drafts; resolving the numeric ID works.
        view = json.loads(subprocess.check_output(
            ['gh', 'release', 'view', tag, '--repo', repo, '--json', 'databaseId'], text=True))
        return json.loads(subprocess.check_output(
            ['gh', 'api', f'repos/{repo}/releases/{view["databaseId"]}'], text=True))

    def download(self, repo, asset, output):
        with Path(output).open('xb') as stream:
            subprocess.run(['gh', 'api', f'repos/{repo}/releases/assets/{asset["id"]}',
                            '-H', 'Accept: application/octet-stream'], stdout=stream, check=True)


def download_verified(client, repo, asset, output, expected=None):
    server_sha = sha256_asset(asset)
    if expected:
        require(asset['size'] == expected['bytes'] and server_sha == expected['sha256'],
                'Manifest differs from GitHub server asset digest')
    output = Path(output)
    if output.exists():
        require(output.is_file() and output.stat().st_size == asset['size'] and
                digest(output) == server_sha, 'Existing cached asset differs')
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + '.partial')
    require(not partial.exists(), 'Incomplete prior download exists: ' + str(partial))
    try:
        client.download(repo, asset, partial)
        require(partial.stat().st_size == asset['size'] and digest(partial) == server_sha,
                'Downloaded asset differs from server SHA-256')
        partial.rename(output)
    finally:
        partial.unlink(missing_ok=True)
    return output


def referenced(manifest):
    result = [manifest['db'], manifest['packed_base']['roads'], manifest['packed_base']['nodes']]
    if manifest.get('coverage', {}).get('poly'):
        result.append(manifest['coverage']['poly'])
    if manifest.get('penalty_rules'):
        result.append(manifest['penalty_rules'])
    return result


def transport_name(item, prefix):
    name = safe_name(unquote(urlparse(item['url']).path.rsplit('/', 1)[-1]))
    require(item['url'] == prefix + name, 'Canonical dependency points outside its release')
    safe_name(item['file'])
    require(type(item.get('bytes')) is int and item['bytes'] > 0 and
            isinstance(item.get('sha256'), str) and SHA.fullmatch(item['sha256']),
            'Invalid manifest artifact identity')
    return name


def installed_header(path, item):
    """Verify gzip transports without keeping a second installed-file copy."""
    compressed = item.get('compression') == 'gzip'
    require(item.get('compression') in (None, '', 'none', 'identity', 'gzip'),
            'Unknown canonical transport compression')
    expected_bytes = item.get('uncompressed_bytes', item['bytes'])
    expected_sha = item.get('uncompressed_sha256', item['sha256'])
    if compressed:
        require('uncompressed_bytes' in item and 'uncompressed_sha256' in item,
                'Compressed artifact lacks installed identity')
    require(type(expected_bytes) is int and expected_bytes > 0 and
            isinstance(expected_sha, str) and SHA.fullmatch(expected_sha),
            'Invalid installed artifact identity')
    result = hashlib.sha256()
    count, header = 0, bytearray()
    with (gzip.open(path, 'rb') if compressed else Path(path).open('rb')) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            count += len(chunk)
            require(count <= expected_bytes, 'Installed artifact exceeds declared size')
            result.update(chunk)
            if len(header) < 128:
                header.extend(chunk[:128 - len(header)])
    require(count == expected_bytes and result.hexdigest() == expected_sha,
            'Installed artifact SHA-256 differs')
    return bytes(header), count


def legacy_schema(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        require(db.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'Legacy SQLite is corrupt')
        tables = []
        for name, sql in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"):
            escaped = '"' + name.replace('"', '""') + '"'
            tables.append({'name': name, 'sql': sql,
                           'columns': [list(row) for row in db.execute('PRAGMA table_info(' + escaped + ')')],
                           'rows': db.execute('SELECT COUNT(*) FROM ' + escaped).fetchone()[0]})
        columns = {table['name']: {row[1] for row in table['columns']} for table in tables}
        require({'row_id', 'way_id'} <= columns.get('ways', set()) and
                {'row_id', 'points_json'} <= columns.get('way_geom', set()) and
                'way_id' not in columns['way_geom'] and
                'row_id' in columns.get('ways_rtree', set()),
                'Alias source is not the audited obsolete row-ID schema')
        return {'schema': 'legacy-row-id-geometry-v1', 'quick_check': 'ok',
                'current_way_id_queries_compatible': False,
                'geometry_join': 'way_geom.row_id = ways.row_id',
                'road_rtree_join': 'ways_rtree.row_id = ways.row_id', 'tables': tables,
                'metadata': [list(row) for row in db.execute('SELECT key,value FROM metadata ORDER BY key')]}
    finally:
        db.close()


def source_manifest(entry):
    value = entry.get('source_manifest_document')
    require(isinstance(value, dict), 'Pinned plan requires embedded source manifests')
    return value


def refresh(plan, workspace, target, client=None):
    started = time.monotonic()
    require(plan.get('format') == 'youspeed.v4.pinned-release-plan' and
            plan.get('schema_version') == 1 and plan.get('failures') == [], 'Invalid pinned source plan')
    repo = plan.get('repo', '')
    require(isinstance(repo, str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo),
            'Invalid repository')
    entries = {entry['source_release_tag']: entry for entry in plan['bundles']}
    require(target in entries and TAG.fullmatch(target), 'Unknown alias target')
    alias = entries[target]
    require(alias['region'] != target and alias['region'] in entries, 'Target is not a noncanonical alias')
    canonical = entries[alias['region']]
    require(canonical['source_release_tag'] == canonical['region'] == alias['region'] and
            canonical['bundle_version'] == alias['bundle_version'] and
            canonical['manifest_file'] == alias['manifest_file'], 'Canonical alias identity differs')
    for entry in [alias, canonical]:
        require(TAG.fullmatch(entry['release_tag']) and TAG.fullmatch(entry['bundle_version']),
                'Unsafe packed generation identity')
        safe_name(entry['manifest_file'])
    old, actual = source_manifest(alias), source_manifest(canonical)
    client = client or GitHub()
    remote = client.release(repo, canonical['release_tag'])
    require(remote.get('draft') is True and remote.get('tag_name') == canonical['release_tag'] and
            re.fullmatch('[0-9a-f]{40}', remote.get('target_commitish', '')),
            'Canonical packed draft identity is not pinned')
    assets = {asset['name']: asset for asset in remote['assets']}
    require(len(assets) == len(remote['assets']), 'Duplicate canonical asset names')
    require(alias['manifest_file'] in assets, 'Canonical manifest asset missing')
    base = Path(workspace) / target
    output = base / 'bundle'
    output.mkdir(parents=True, exist_ok=True)
    require(not (base / 'result.json').exists(), 'Alias result already exists; use a fresh workspace')
    script_sha = digest(Path(__file__))
    with tempfile.TemporaryDirectory(prefix='alias-refresh-', dir=base) as temporary:
        temporary = Path(temporary)
        manifest_asset = assets[alias['manifest_file']]
        manifest_file = download_verified(client, repo, manifest_asset, temporary / 'canonical-manifest.json')
        manifest = json.loads(manifest_file.read_text())
        require(manifest.get('format') == 'youspeed.v4.bundle.manifest' and manifest.get('min_app_version') == '1.6' and
                manifest.get('region') == alias['region'] and manifest.get('bundle_version') == alias['bundle_version'] and
                manifest.get('delta_index') is None and not manifest.get('db_parts'), 'Canonical manifest is incompatible')
        source = manifest['source']['packed_storage']
        original = actual['db']
        source_sha = original.get('uncompressed_sha256', original['sha256'])
        require(source['original_sqlite_sha256'] == source_sha and
                source['original_bundle_version'] == actual['bundle_version'] and
                source['context_codec'] == 'zstd-15-independent-256KiB-frames' and
                source.get('local_full_bw_upgrade') is False, 'Canonical source provenance differs')
        builder_files = {'scripts/map/' + name: digest(Path(__file__).parent / name) for name in BUILDER_NAMES}
        require(source['builder_files_sha256'] == builder_files, 'Canonical builder recipe differs')
        prefix = f'https://github.com/{repo}/releases/download/{canonical["release_tag"]}/'
        require(manifest['self'] == {'file': canonical['manifest_file'], 'url': prefix + canonical['manifest_file']},
                'Canonical manifest self identity differs')
        validation_name = safe_name(canonical['region'] + '_' + canonical['bundle_version'] + '_validation.json')
        require(validation_name in assets, 'Canonical semantic validation asset missing')
        validation_file = download_verified(client, repo, assets[validation_name], output / validation_name)
        verification = json.loads(validation_file.read_text())
        require(all(verification.get(flag) is True for flag in PROOF_FLAGS), 'Canonical semantic proof incomplete')
        dependencies = referenced(manifest)
        names = set()
        installed = []
        headers = []
        for number, item in enumerate(dependencies):
            name = transport_name(item, prefix)
            require(name in assets and name not in names and name not in (validation_name, alias['manifest_file']),
                    'Canonical dependency missing or duplicated')
            names.add(name)
            path = download_verified(client, repo, assets[name], output / name, item)
            header, size = installed_header(path, item)
            if number < 3:
                installed.append(size)
                headers.append(header)
        for header, magic, size in zip(headers[:2], [b'YSPCTX1\0', b'YSPGEO1\0'], installed[:2]):
            require(len(header) == 128 and header[:8] == magic and header[96:128].hex() == source_sha and
                    struct.unpack_from('<IIII', header, 8) == (1, 0x01020304, 128, 262144) and
                    struct.unpack_from('<Q', header, 56)[0] == size and
                    struct.unpack_from('<I', header, 92)[0] == 2 and
                    zlib.crc32(header[:88]) == struct.unpack_from('<I', header, 88)[0],
                    'Canonical container header/source differs')
        require(struct.unpack_from('<Q', headers[1], 64)[0] == verification['geometry_rows'],
                'Canonical geometry count differs from semantic proof')
        node_source = source['generic_sign_nodes']
        require(headers[2][:8] == b'YSPNODE1' and len(headers[2]) == 128 and
                struct.unpack_from('<II', headers[2], 8) == (1, 0x01020304) and
                struct.unpack_from('<Q', headers[2], 48)[0] == installed[2] and
                struct.unpack_from('<Q', headers[2], 16)[0] == node_source['node_count'] and
                zlib.crc32(headers[2][:64]) == struct.unpack_from('<I', headers[2], 64)[0] and
                node_source['source_sqlite_sha256'] == source_sha, 'Canonical node source/count differs')
        require(len(alias['database_assets']) == 1 and old['db'].get('compression') in (None, '', 'none', 'identity'),
                'Legacy alias source transport is unsupported')
        old_asset = alias['database_assets'][0]
        old_file = download_verified(client, repo, old_asset, temporary / 'legacy.sqlite', old['db'])
        audit = legacy_schema(old_file)
        provenance = {'kind': 'canonical-region-alias', 'repackaged_at_utc': datetime.now(timezone.utc).isoformat(),
                      'repackager': {'file': 'scripts/map/refresh_packed_alias.py', 'sha256': script_sha},
                      'legacy': {'release_tag': target, 'release_url': alias['source_release_url'],
                                 'bundle_version': old['bundle_version'], 'manifest': old,
                                 'manifest_server_sha256': sha256_asset(alias['source_manifest_asset']),
                                 'sqlite_sha256': digest(old_file), 'installed_bytes': old_file.stat().st_size,
                                 'download_bytes': sum(asset['size'] for asset in alias['database_assets']),
                                 'schema_audit': audit},
                      'canonical': {'source_release_tag': canonical['source_release_tag'],
                                    'source_release_url': canonical['source_release_url'],
                                    'packed_release_tag': canonical['release_tag'], 'packed_release_id': remote['id'],
                                    'packed_source_commit': remote['target_commitish'],
                                    'manifest_server_sha256': sha256_asset(manifest_asset),
                                    'validation_server_sha256': sha256_asset(assets[validation_name]),
                                    'source_sqlite_sha256': source_sha},
                      'data_bytes_reused_identically': True,
                      'comparison_basis': 'Lossless data proof and source compression compare against canonical region input. Historical alias bytes are a separate previous-published baseline.'}
        refreshed = copy.deepcopy(manifest)
        refreshed['source']['alias_refresh'] = provenance
        alias_prefix = f'https://github.com/{repo}/releases/download/{alias["release_tag"]}/'
        for item in referenced(refreshed):
            item['url'] = alias_prefix + transport_name(item, prefix)
        refreshed['self'] = {'file': alias['manifest_file'], 'url': alias_prefix + alias['manifest_file']}
        (output / alias['manifest_file']).write_bytes(json_bytes(refreshed))
        installed_bytes = sum(installed)
        download_bytes = sum(item['bytes'] for item in dependencies[:3])
        source_bytes = original.get('uncompressed_bytes', original['bytes'])
        result = {'format': 'youspeed.v4.release-comparison', 'schema_version': 1,
                  'region': alias['region'], 'release_tag': alias['release_tag'], 'bundle_version': alias['bundle_version'],
                  'source_release_tag': target, 'converted_source_release_tag': canonical['source_release_tag'],
                  'source_upgrade_kind': 'canonical-region-alias', 'source_bundle_version': actual['bundle_version'],
                  'local_source_upgrade': False, 'source_sqlite_sha256': source_sha,
                  'source_installed_bytes': source_bytes, 'source_download_bytes': original['bytes'],
                  'previous_published_installed_bytes': old_file.stat().st_size,
                  'previous_published_download_bytes': sum(asset['size'] for asset in alias['database_assets']),
                  'builder_files_sha256': builder_files, 'build_cache_identity': source['build_cache_identity'],
                  'packed_installed_bytes': installed_bytes, 'packed_download_bytes': download_bytes,
                  'installed_change_percent': (installed_bytes / source_bytes - 1) * 100,
                  'download_change_percent': (download_bytes / original['bytes'] - 1) * 100,
                  'node_count': node_source['node_count'], 'source_nodes': node_source,
                  'verification': verification, 'verification_source_release_tag': canonical['source_release_tag'],
                  'alias_refresh': provenance, 'elapsed_seconds': time.monotonic() - started, 'release_files': []}
        for name in sorted(names | {alias['manifest_file'], validation_name}):
            path = output / name
            result['release_files'].append({'file': name, 'bytes': path.stat().st_size, 'sha256': digest(path)})
        temporary_result = base / 'result.json.partial'
        temporary_result.write_bytes(json_bytes(result))
        temporary_result.rename(base / 'result.json')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    result = refresh(json.loads(args.plan.read_text()), args.workspace, args.target)
    print(json.dumps({key: result[key] for key in ['source_release_tag', 'converted_source_release_tag',
                     'release_tag', 'source_upgrade_kind', 'packed_installed_bytes', 'packed_download_bytes']}))


if __name__ == '__main__':
    main()
