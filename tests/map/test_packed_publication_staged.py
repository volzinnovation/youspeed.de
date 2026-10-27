import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/map'))
import publish_packed_release as publisher


class PackedStagedPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.commit = 'a' * 40
        self.tag = 'monaco-packed-v1-test'
        self.repo = 'owner/maps'
        self.prefix = 'https://github.com/' + self.repo + '/releases/download/' + self.tag + '/'
        self.recipe = {'scripts/map/packed_runtime.py': 'b' * 64}
        self.manifest = {'format': 'youspeed.v4.bundle.manifest', 'schema_version': 1, 'variant': 'v4',
            'min_app_version': '1.6', 'region': 'monaco', 'bundle_version': 'test',
            'self': {'file': 'monaco_manifest.json', 'url': self.prefix + 'monaco_manifest.json'},
            'source': {'packed_storage': {'builder_files_sha256': self.recipe, 'original_sqlite_sha256': 'c' * 64,
                'context_codec': 'zstd-15-independent-256KiB-frames'}}}
        self.files = []
        def artifact(name):
            raw = name.encode()
            item = {'file': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            self.files.append(item)
            return dict(item, url=self.prefix + name)
        self.manifest['db'] = artifact('context.yspc')
        self.manifest['packed_base'] = {'version': 1, 'roads': artifact('roads.yspg.gz'), 'nodes': artifact('nodes.yspn.gz')}
        self.raw_manifest = json.dumps(self.manifest, sort_keys=True).encode()
        self.files.append({'file': 'monaco_manifest.json', 'bytes': len(self.raw_manifest),
            'sha256': hashlib.sha256(self.raw_manifest).hexdigest()})
        self.result = {'region': 'monaco', 'bundle_version': 'test', 'release_tag': self.tag,
            'builder_files_sha256': self.recipe, 'source_sqlite_sha256': 'c' * 64,
            'verification': dict.fromkeys(['all_original_logical_table_counts_preserved',
                'original_metadata_values_preserved', 'every_original_geometry_text_exact'], True),
            'packed_installed_bytes': 1000, 'source_installed_bytes': 2000,
            'packed_download_bytes': 500, 'source_download_bytes': 1000, 'release_files': self.files}
        self.result_path = self.root / 'result.json'; self.result_path.write_text(json.dumps(self.result))
        self.qa_path = self.root / 'qa.json'; self.qa_path.write_text('{}')
        self.remote = {'draft': True, 'target_commitish': self.commit, 'tag_name': self.tag,
            'html_url': 'https://github.com/' + self.repo + '/releases/tag/untagged-draft',
            'assets': [{'name': item['file'], 'id': index + 1, 'size': item['bytes'], 'digest': 'sha256:' + item['sha256']}
                       for index, item in enumerate(self.files)]}
        self.view = SimpleNamespace(returncode=0, stdout=json.dumps({'isDraft': True, 'targetCommitish': self.commit}), stderr='')

    def argv(self, publish=True):
        args = ['publisher', '--result', str(self.result_path), '--repo', self.repo,
                '--source-commit', self.commit, '--publish-staged', '--qa-report', str(self.qa_path)]
        return args + (['--publish'] if publish else [])

    def output(self, args, **options):
        if args[:3] == ['gh', 'release', 'view']: return json.dumps({'databaseId': 42})
        if args[2].endswith('/releases/42'): return json.dumps(self.remote)
        if '/releases/assets/' in args[2]: return self.raw_manifest
        raise AssertionError('Unexpected network command: ' + repr(args))

    def run_staged(self, *, expected_error=None, tag_commit=None):
        with patch.object(sys, 'argv', self.argv()), \
             patch.object(publisher.subprocess, 'check_output', side_effect=self.output), \
             patch.object(publisher.subprocess, 'run', return_value=self.view), \
             patch.object(publisher, 'validate_qa') as qa, \
             patch.object(publisher, 'tag_commit', return_value=tag_commit or self.commit), \
             patch.object(publisher, 'run') as mutations:
            def publish(args):
                if '--draft=false' in args:
                    self.remote['draft'] = False
                    self.remote['html_url'] = 'https://github.com/' + self.repo + '/releases/tag/' + self.tag
            mutations.side_effect = publish
            if expected_error:
                with self.assertRaisesRegex(ValueError, expected_error): publisher.main()
                mutations.assert_not_called()
            else:
                publisher.main()
                qa.assert_called_once()
                self.assertEqual(mutations.call_count, 1)
                command = mutations.call_args.args[0]
                self.assertEqual(command[:3], ['release', 'edit', self.tag])
                self.assertIn('--draft=false', command)
                self.assertNotIn('upload', command)
                self.assertNotIn('create', command)

    def test_staged_success_verifies_server_hashes_and_publishes_without_payload_files(self):
        self.assertFalse((self.root / 'bundle').exists())
        self.run_staged()
        receipt = json.loads((self.root / 'github-verified.json').read_text())
        self.assertTrue(receipt['published'])
        self.assertTrue(receipt['all_asset_hashes_verified'])
        self.assertEqual(receipt['asset_count'], 4)
        self.assertEqual(receipt['url'], 'https://github.com/' + self.repo + '/releases/tag/' + self.tag)

    def test_staged_release_cannot_create_replacement_after_missing_or_failed_view(self):
        for error in ['HTTP 404', 'network connection failed']:
            with self.subTest(error=error):
                self.view.returncode = 1; self.view.stderr = error
                self.run_staged(expected_error='refusing to create')
                self.assertFalse((self.root / 'github-verified.json').exists())

    def test_wrong_draft_target_and_existing_tag_commit_cannot_publish(self):
        self.remote['target_commitish'] = 'd' * 40
        self.run_staged(expected_error='Staged release does not match')
        self.remote['target_commitish'] = self.commit
        self.run_staged(expected_error='tag belongs to another', tag_commit='d' * 40)

    def test_changed_server_payload_or_manifest_prevents_publication(self):
        self.remote['assets'][0]['digest'] = 'sha256:' + 'd' * 64
        self.run_staged(expected_error='GitHub asset differs')
        self.raw_manifest += b' '
        self.run_staged(expected_error='Staged manifest differs')

    def test_existing_public_generation_cannot_be_republished(self):
        self.remote['draft'] = False
        self.run_staged(expected_error='Staged release does not match')

    def test_publish_staged_requires_explicit_publish_before_network_access(self):
        with patch.object(sys, 'argv', self.argv(publish=False)), \
             patch.object(publisher.subprocess, 'check_output') as read, \
             patch.object(publisher.subprocess, 'run') as write:
            with self.assertRaisesRegex(ValueError, 'also requires --publish'): publisher.main()
            read.assert_not_called(); write.assert_not_called()

    def test_bound_qa_rejects_wrong_bw_bytes_recipe_and_runtime_hash(self):
        required = ['shared/runtime-storage-prototype/packed_runtime.cpp',
            'shared/runtime-storage-prototype/packed_runtime.h',
            'shared/runtime-storage-prototype/packed_sqlite_vfs.cpp',
            'shared/runtime-sign-nodes-prototype/runtime_sign_nodes.cpp',
            'android/app/src/main/cpp/packed_sqlite_jni.cpp',
            'android/app/src/main/java/de/youspeed/android/alpha/RuntimeSqlDatabase.kt',
            'android/app/src/main/java/de/youspeed/android/alpha/MapDataAmendmentStore.kt',
            'android/app/src/main/java/de/youspeed/android/alpha/RuntimeMapDatabase.kt',
            'android/app/src/main/java/de/youspeed/android/alpha/ConditionalSpeedRules.kt',
            'android/app/src/main/java/de/youspeed/android/alpha/V3SpeedLimitLookup.kt',
            'android/app/src/main/java/de/youspeed/android/alpha/InventorySignRuntime.kt',
            'iphone/SpeedConsumerApp/MapDataAmendmentStore.swift',
            'iphone/SpeedConsumerApp/ConditionalSpeedRules.swift',
            'iphone/SpeedConsumerApp/V3LookupResources.swift',
            'iphone/SpeedConsumerApp/V3SpeedLimitService.swift',
            'iphone/SpeedConsumerApp/PackedBundleRuntime.swift']
        content = {name: name.encode() for name in required + list(self.recipe)}
        hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in content.items()}
        recipe = {name: hashes[name] for name in self.recipe}
        manifest = copy.deepcopy(self.manifest); manifest['region'] = 'baden-wuerttemberg'
        manifest['source']['packed_storage']['builder_files_sha256'] = recipe
        for item in [manifest['packed_base']['roads'], manifest['packed_base']['nodes']]:
            item.update(compression='gzip', uncompressed_bytes=200, uncompressed_sha256='d' * 64)
        result = dict(self.result, region='baden-wuerttemberg', builder_files_sha256=recipe)
        evidence = {'lookup_results_identical': True, 'observed_incremental_rss_bytes': 20 * 1024 * 1024,
                    'mapped_payload_bytes': 0, 'report_sha256': 'e' * 64, 'retained_reader_count': 8,
                    'pool_lookup_results_identical': True, 'pool_observed_incremental_rss_bytes': 40 * 1024 * 1024,
                    'pool_report_sha256': 'f' * 64}
        qa = {'format': 'youspeed.packed-runtime.rollout-qa', 'schema_version': 1, 'ready_for_rollout': True,
            'physical_devices_passed': ['iphone', 'android'], 'source_commit': self.commit,
            'runtime_source_commit': self.commit,
            'mapped_payload_bytes': 0, 'observed_incremental_rss_gate_bytes': 64 * 1024 * 1024,
            'builder_files_sha256': recipe, 'runtime_source_sha256': {name: hashes[name] for name in required},
            'tested_bw_artifacts': {name: {'bytes': item.get('uncompressed_bytes', item['bytes']),
                                         'sha256': item.get('uncompressed_sha256', item['sha256'])} for name, item in
                zip(['context', 'roads', 'nodes'], [manifest['db'], manifest['packed_base']['roads'], manifest['packed_base']['nodes']])},
            'physical_device_evidence': {'iphone': dict(evidence), 'android': dict(evidence)}}
        def git(args):
            self.assertEqual(args[:2], ['git', 'show'])
            revision, name = args[2].split(':', 1); self.assertEqual(revision, self.commit)
            return content[name]
        with patch.object(publisher.subprocess, 'check_output', side_effect=git):
            publisher.validate_qa(qa, result, manifest, self.commit)
            changed = copy.deepcopy(qa); changed.pop('runtime_source_commit')
            with self.assertRaisesRegex(ValueError, 'Runtime QA commit must be pinned'): publisher.validate_qa(changed, result, manifest, self.commit)
            changed = copy.deepcopy(qa); changed['tested_bw_artifacts']['context']['bytes'] += 1
            with self.assertRaisesRegex(ValueError, 'differs from tested phone data'): publisher.validate_qa(changed, result, manifest, self.commit)
            changed = copy.deepcopy(qa); changed['builder_files_sha256'] = {}
            with self.assertRaisesRegex(ValueError, 'Untested builder recipe'): publisher.validate_qa(changed, result, manifest, self.commit)
            changed = copy.deepcopy(qa); changed['runtime_source_sha256'][required[0]] = 'f' * 64
            with self.assertRaisesRegex(ValueError, 'QA source hash differs'): publisher.validate_qa(changed, result, manifest, self.commit)
            changed = copy.deepcopy(qa); changed['physical_device_evidence']['android']['retained_reader_count'] = 1
            with self.assertRaisesRegex(ValueError, 'Invalid physical-device evidence'): publisher.validate_qa(changed, result, manifest, self.commit)
            changed = copy.deepcopy(qa); changed['physical_device_evidence']['iphone']['pool_observed_incremental_rss_bytes'] = 56 * 1024 * 1024
            with self.assertRaisesRegex(ValueError, 'Invalid physical-device evidence'): publisher.validate_qa(changed, result, manifest, self.commit)
        runtime_qa=copy.deepcopy(qa); runtime_qa['runtime_source_commit']='d'*40
        def independent_commits(args):
            revision,name=args[2].split(':',1)
            self.assertEqual(revision, runtime_qa['runtime_source_commit'] if name in required else self.commit)
            return content[name]
        with patch.object(publisher.subprocess,'check_output',side_effect=independent_commits):
            publisher.validate_qa(runtime_qa,result,manifest,self.commit)
        alias_qa=copy.deepcopy(runtime_qa);alias_commit='e'*40
        alias_qa['approved_data_source_commits']=[self.commit,alias_commit]
        def approved_alias_commits(args):
            revision,name=args[2].split(':',1)
            self.assertEqual(revision,alias_qa['runtime_source_commit'] if name in required else alias_commit)
            return content[name]
        with patch.object(publisher.subprocess,'check_output',side_effect=approved_alias_commits):
            publisher.validate_qa(alias_qa,result,manifest,alias_commit)


if __name__ == '__main__':
    unittest.main()
