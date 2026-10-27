import copy
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/map'))
import refresh_packed_alias as alias_tool


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class FakeGitHub:
    def __init__(self):
        self.data = {}
        self.assets = {}
        self.downloads = []
        self.draft = True

    def add(self, name, raw):
        asset = {'name': name, 'id': len(self.assets) + 1, 'size': len(raw), 'digest': 'sha256:' + sha(raw)}
        self.assets[name] = asset
        self.data[asset['id']] = raw
        return asset

    def release(self, repo, tag):
        return {'id': 42, 'tag_name': tag, 'target_commitish': 'c' * 40, 'draft': self.draft,
                'assets': [a for n, a in self.assets.items() if n not in ('legacy.sqlite', 'old-manifest.json')]}

    def download(self, repo, asset, output):
        self.downloads.append(asset['name'])
        Path(output).write_bytes(self.data[asset['id']])


class AliasRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.client = FakeGitHub()
        self.repo = 'owner/repo'
        self.target = 'legacy-region'
        self.canonical_tag = 'region-packed-v1'
        self.alias_tag = 'legacy-region-packed-v1'
        self.prefix = f'https://github.com/{self.repo}/releases/download/{self.canonical_tag}/'
        legacy = self.root / 'legacy.sqlite'
        db = sqlite3.connect(legacy)
        db.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);'
                         'INSERT INTO metadata VALUES("schema_version","1");'
                         'CREATE TABLE ways(row_id INTEGER PRIMARY KEY,way_id INTEGER UNIQUE);'
                         'CREATE TABLE way_geom(row_id INTEGER PRIMARY KEY,points_json TEXT);'
                         'CREATE VIRTUAL TABLE ways_rtree USING rtree(row_id,min_lon,max_lon,min_lat,max_lat);'
                         'INSERT INTO ways VALUES(1,9007199254740993);'
                         'INSERT INTO way_geom VALUES(1,"[[49,8],[49.1,8.1]]");'
                         'INSERT INTO ways_rtree VALUES(1,8,8.1,49,49.1);')
        db.close()
        legacy_raw = legacy.read_bytes()
        old_asset = self.client.add('legacy.sqlite', legacy_raw)
        old = {'format': 'youspeed.v3.bundle.manifest', 'region': 'region', 'bundle_version': 'old',
               'db': {'file': 'legacy.sqlite', 'bytes': len(legacy_raw), 'sha256': sha(legacy_raw),
                      'url': 'https://old.example/legacy.sqlite'}}
        old_manifest = self.client.add('old-manifest.json', alias_tool.json_bytes(old))
        self.source_sha = sha(b'canonical complete original SQLite')
        actual = {'bundle_version': 'new', 'db': {'bytes': 1000, 'uncompressed_bytes': 4000,
                                                 'sha256': sha(b'canonical transport'),
                                                 'uncompressed_sha256': self.source_sha, 'compression': 'gzip'}}
        self.plan = {'format': 'youspeed.v4.pinned-release-plan', 'schema_version': 1, 'failures': [],
                     'repo': self.repo, 'bundles': [
                         {'source_release_tag': self.target, 'region': 'region', 'release_tag': self.alias_tag,
                          'bundle_version': 'packed-v1', 'manifest_file': 'region_manifest.json',
                          'source_manifest_document': old, 'database_assets': [old_asset],
                          'source_manifest_asset': old_manifest,
                          'source_release_url': 'https://github.com/owner/repo/releases/tag/' + self.target},
                         {'source_release_tag': 'region', 'region': 'region', 'release_tag': self.canonical_tag,
                          'bundle_version': 'packed-v1', 'manifest_file': 'region_manifest.json',
                          'source_manifest_document': actual,
                          'source_release_url': 'https://github.com/owner/repo/releases/tag/region'}]}
        self.context = self.header(b'YSPCTX1\0')
        self.geometry = self.header(b'YSPGEO1\0', 1)
        self.nodes = bytearray(128)
        struct.pack_into('<8sIIQ', self.nodes, 0, b'YSPNODE1', 1, 0x01020304, 0)
        struct.pack_into('<Q', self.nodes, 48, 128)
        struct.pack_into('<I', self.nodes, 64, zlib.crc32(self.nodes[:64]))
        self.nodes = bytes(self.nodes)

        def item(file, raw, compress=False):
            transport = gzip.compress(raw, mtime=0) if compress else raw
            name = file + ('.gz' if compress else '')
            self.client.add(name, transport)
            result = {'file': file, 'bytes': len(transport), 'sha256': sha(transport), 'url': self.prefix + name}
            if compress:
                result.update(compression='gzip', uncompressed_bytes=len(raw), uncompressed_sha256=sha(raw))
            return result

        self.manifest = {'format': 'youspeed.v4.bundle.manifest', 'min_app_version': '1.6',
                         'region': 'region', 'bundle_version': 'packed-v1', 'delta_index': None,
                         'db': item('region.context.yspc', self.context),
                         'packed_base': {'version': 1, 'roads': item('region.ways.yspg', self.geometry, True),
                                         'nodes': item('region.nodes.yspn', self.nodes, True)},
                         'coverage': {'poly': item('region.poly', b'coverage')},
                         'penalty_rules': item('region-rules.json', b'{}'),
                         'self': {'file': 'region_manifest.json', 'url': self.prefix + 'region_manifest.json'},
                         'source': {'packed_storage': {
                             'original_sqlite_sha256': self.source_sha, 'original_bundle_version': 'new',
                             'context_codec': 'zstd-15-independent-256KiB-frames', 'local_full_bw_upgrade': False,
                             'builder_files_sha256': {'scripts/map/' + n: alias_tool.digest(Path(alias_tool.__file__).parent / n)
                                                      for n in alias_tool.BUILDER_NAMES},
                             'build_cache_identity': 'canonical-build-identity',
                             'generic_sign_nodes': {'node_count': 0, 'source_sqlite_sha256': self.source_sha}}}}
        self.validation = {flag: True for flag in alias_tool.PROOF_FLAGS}
        self.validation.update(geometry_rows=1, tables=[{'name': 'ways', 'rows': 1}])
        self.client.add('region_packed-v1_validation.json', alias_tool.json_bytes(self.validation))
        self.client.add('region_manifest.json', alias_tool.json_bytes(self.manifest))

    def header(self, magic, geometry_rows=0):
        result = bytearray(128)
        struct.pack_into('<8sIIII', result, 0, magic, 1, 0x01020304, 128, 262144)
        struct.pack_into('<Q', result, 56, 128)
        struct.pack_into('<Q', result, 64, geometry_rows)
        struct.pack_into('<I', result, 88, zlib.crc32(result[:88]))
        struct.pack_into('<I', result, 92, 2)
        result[96:128] = bytes.fromhex(self.source_sha)
        return bytes(result)

    def replace(self, name, raw):
        asset = self.client.assets[name]
        self.client.data[asset['id']] = raw
        asset.update(size=len(raw), digest='sha256:' + sha(raw))

    def run_refresh(self):
        return alias_tool.refresh(self.plan, self.root / 'output', self.target, self.client)

    def test_payloads_and_canonical_proof_are_byte_identical_and_only_manifest_changes(self):
        result = self.run_refresh()
        bundle = self.root / 'output' / self.target / 'bundle'
        for file in result['release_files']:
            if file['file'] != 'region_manifest.json':
                self.assertEqual((bundle / file['file']).read_bytes(),
                                 self.client.data[self.client.assets[file['file']]['id']])
        refreshed = json.loads((bundle / 'region_manifest.json').read_text())
        provenance = refreshed['source'].pop('alias_refresh')
        expected = copy.deepcopy(self.manifest)
        alias_prefix = f'https://github.com/{self.repo}/releases/download/{self.alias_tag}/'
        for item in alias_tool.referenced(expected):
            item['url'] = alias_prefix + item['url'].removeprefix(self.prefix)
        expected['self']['url'] = alias_prefix + 'region_manifest.json'
        self.assertEqual(refreshed, expected)
        self.assertTrue(provenance['data_bytes_reused_identically'])
        self.assertFalse(provenance['legacy']['schema_audit']['current_way_id_queries_compatible'])
        self.assertEqual(result['source_release_tag'], self.target)
        self.assertEqual(result['converted_source_release_tag'], 'region')
        self.assertEqual(result['source_upgrade_kind'], 'canonical-region-alias')
        self.assertEqual(result['source_installed_bytes'], 4000)
        self.assertEqual(result['source_download_bytes'], 1000)
        self.assertEqual(result['source_bundle_version'], 'new')
        self.assertEqual(result['source_sqlite_sha256'], self.source_sha)
        self.assertEqual(result['verification'], self.validation)
        self.assertEqual(result['builder_files_sha256'], self.manifest['source']['packed_storage']['builder_files_sha256'])
        self.assertFalse(result['local_source_upgrade'])
        self.assertEqual(result['previous_published_download_bytes'], self.plan['bundles'][0]['database_assets'][0]['size'])
        self.assertEqual(result['packed_installed_bytes'], len(self.context) + len(self.geometry) + len(self.nodes))
        self.assertFalse((self.root / 'output' / self.target / 'work').exists())
        with self.assertRaisesRegex(ValueError, 'fresh workspace'):
            self.run_refresh()

    def test_wrong_server_body_and_absent_digest_fail_closed(self):
        asset = self.client.assets['region.context.yspc']
        self.client.data[asset['id']] = b'x' * asset['size']
        with self.assertRaisesRegex(ValueError, 'server SHA-256'):
            self.run_refresh()
        self.assertFalse((self.root / 'output' / self.target / 'result.json').exists())
        asset['digest'] = None
        with self.assertRaisesRegex(ValueError, 'server asset SHA-256'):
            self.run_refresh()

    def test_canonical_target_or_published_replacement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'noncanonical alias'):
            alias_tool.refresh(self.plan, self.root / 'other', 'region', self.client)
        self.client.draft = False
        with self.assertRaisesRegex(ValueError, 'draft identity'):
            self.run_refresh()

    def test_failed_canonical_semantic_proof_is_not_inherited(self):
        self.validation[alias_tool.PROOF_FLAGS[0]] = False
        self.replace('region_packed-v1_validation.json', alias_tool.json_bytes(self.validation))
        with self.assertRaisesRegex(ValueError, 'semantic proof incomplete'):
            self.run_refresh()

    def test_external_dependency_and_installed_identity_mismatch_are_rejected(self):
        self.manifest['db']['url'] = 'https://other.example/region.context.yspc'
        self.replace('region_manifest.json', alias_tool.json_bytes(self.manifest))
        with self.assertRaisesRegex(ValueError, 'outside its release'):
            self.run_refresh()

    def test_gzip_is_verified_as_installed_bytes_not_only_transport(self):
        self.manifest['packed_base']['roads']['uncompressed_sha256'] = 'a' * 64
        self.replace('region_manifest.json', alias_tool.json_bytes(self.manifest))
        with self.assertRaisesRegex(ValueError, 'Installed artifact SHA-256 differs'):
            self.run_refresh()

    def test_draft_resolution_uses_release_id(self):
        with patch.object(alias_tool.subprocess, 'check_output', side_effect=[
                json.dumps({'databaseId': 42}), json.dumps({'draft': True})]) as calls:
            self.assertTrue(alias_tool.GitHub().release('owner/repo', 'draft')['draft'])
            self.assertEqual(calls.call_args_list[1].args[0], ['gh', 'api', 'repos/owner/repo/releases/42'])


if __name__ == '__main__':
    unittest.main()
