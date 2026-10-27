import copy
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/map'))
import packed_catalog as catalog


class PackedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = {'format': 'youspeed.v4.pinned-release-plan', 'schema_version': 1,
                     'repo': 'owner/maps', 'failures': [], 'bundles': []}

    def add(self, region, source=None, upgraded=False):
        source = source or region
        entry = {'region': region, 'country_code': 'DEU', 'source_release_tag': source,
                 'release_tag': source + '-packed-v1-test', 'bundle_version': '2026-test',
                 'source_bundle_version': 'source-v1', 'manifest_file': region + '_manifest.json',
                 'database_assets': [{'size': 400}],
                 'source_manifest_document': {'db': {'bytes': 400, 'compression': 'gzip',
                     'sha256': 'd' * 64, 'uncompressed_bytes': 1000, 'uncompressed_sha256': 'a' * 64}}}
        self.plan['bundles'].append(entry)
        result = {'format': 'youspeed.v4.release-comparison', 'schema_version': 1,
                  'region': region, 'source_release_tag': source, 'release_tag': entry['release_tag'],
                  'bundle_version': entry['bundle_version'], 'source_bundle_version': 'source-v1',
                  'local_source_upgrade': upgraded, 'source_sqlite_sha256': ('b' if upgraded else 'a') * 64,
                  'source_installed_bytes': 2000 if upgraded else 1000,
                  'source_download_bytes': 800 if upgraded else 400,
                  'packed_installed_bytes': 500, 'packed_download_bytes': 300,
                  'previous_published_download_bytes': 400, 'node_count': 3,
                  'verification': {'all_original_logical_table_counts_preserved': True,
                                   'original_metadata_values_preserved': True, 'every_original_geometry_text_exact': True},
                  'release_files': [{'file': region + '_manifest.json', 'bytes': 123, 'sha256': 'c' * 64}]}
        receipt = {'release_tag': entry['release_tag'], 'url': 'https://github.com/owner/maps/releases/tag/' + entry['release_tag'],
                   'source_commit': 'e' * 40, 'all_asset_hashes_verified': True, 'asset_count': 1, 'published': True}
        directory = self.root / source
        directory.mkdir()
        path = directory / 'result.json'
        self.write(path, result)
        self.write(directory / 'github-verified.json', receipt)
        return path

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value))

    def edit(self, path, key, value):
        data = json.loads(path.read_text()); data[key] = value; self.write(path, data)

    def test_catalog_schema_manifest_digest_and_canonical_alias_selection(self):
        alias = self.add('karlsruhe-regbez', 'deu-v3-data-karlsruhe-latest')
        canonical = self.add('karlsruhe-regbez')
        other = self.add('alsace')
        result, comparison = catalog.documents(self.plan, [alias, canonical, other], require_complete=True)
        self.assertEqual(result['format'], 'youspeed.v4.bundle.catalog')
        self.assertEqual(result['schema_version'], 1)
        self.assertEqual(result['variant'], 'v4')
        self.assertEqual([item['region'] for item in result['bundles']], ['alsace', 'karlsruhe-regbez'])
        selected = result['bundles'][1]
        self.assertEqual(selected['release_tag'], 'karlsruhe-regbez-packed-v1-test')
        self.assertEqual(selected['manifest'], {'file': 'karlsruhe-regbez_manifest.json', 'bytes': 123, 'sha256': 'c' * 64,
            'url': 'https://github.com/owner/maps/releases/download/karlsruhe-regbez-packed-v1-test/karlsruhe-regbez_manifest.json'})
        self.assertEqual(comparison['release_count'], 3)
        self.assertEqual(comparison['catalog_region_count'], 2)
        self.assertEqual(comparison['catalog_region_totals']['source_installed_bytes'], 2000)
        self.assertEqual(sum(row['catalog_selected'] for row in comparison['bundles']), 2)

    def test_upgraded_bw_has_separate_source_and_previous_published_comparisons(self):
        path = self.add('baden-wuerttemberg', upgraded=True)
        _, comparison = catalog.documents(self.plan, [path])
        row = comparison['bundles'][0]
        self.assertEqual(row['installed_change_percent'], -75)
        self.assertEqual(row['download_change_percent'], -62.5)
        self.assertEqual(row['previous_published_installed_change_percent'], -50)
        self.assertEqual(row['previous_published_download_change_percent'], -25)
        self.assertEqual(comparison['catalog_region_totals']['previous_published_download_change_percent'], -25)
        csv_rows = list(csv.DictReader(io.StringIO(catalog.csv_document(comparison))))
        self.assertEqual(csv_rows[0]['local_source_upgrade'], 'true')
        self.assertEqual(csv_rows[0]['source_installed_bytes'], '2000')
        self.assertEqual(csv_rows[0]['previous_published_installed_bytes'], '1000')

    def test_only_planned_same_region_alias_can_use_canonical_source(self):
        canonical = self.add('karlsruhe-regbez')
        alias = self.add('karlsruhe-regbez', 'deu-v3-data-karlsruhe-latest')
        # The obsolete alias has a smaller and different original source.
        old = self.plan['bundles'][1]
        old['database_assets'][0]['size'] = 100
        old['source_manifest_document']['db'].update(bytes=100, uncompressed_bytes=200, uncompressed_sha256='f' * 64)
        result = json.loads(alias.read_text())
        result.update(converted_source_release_tag='karlsruhe-regbez', source_upgrade_kind='canonical-region-alias',
                      previous_published_download_bytes=100)
        self.write(alias, result)
        document, comparison = catalog.documents(self.plan, [canonical, alias], require_complete=True)
        self.assertEqual(len(document['bundles']), 1)
        row = next(row for row in comparison['bundles'] if not row['catalog_selected'])
        self.assertEqual(row['source_installed_bytes'], 1000)
        self.assertEqual(row['previous_published_installed_bytes'], 200)
        self.assertEqual(row['previous_published_download_change_percent'], 200)
        self.assertEqual(row['source_upgrade_kind'], 'canonical-region-alias')
        for value in ['monaco', 'deu-v3-data-karlsruhe-latest']:
            changed = dict(result, converted_source_release_tag=value); self.write(alias, changed)
            with self.assertRaisesRegex(ValueError, 'Unplanned canonical alias'): catalog.documents(self.plan, [canonical, alias])

    def test_drafts_and_unverified_or_mismatched_server_receipts_fail_closed(self):
        path = self.add('monaco')
        receipt_path = path.with_name('github-verified.json')
        original = json.loads(receipt_path.read_text())
        for key, value in [('published', False), ('published', 'true'), ('all_asset_hashes_verified', False),
                           ('asset_count', 2), ('asset_count', True), ('release_tag', 'other-tag'),
                           ('source_commit', 'not-a-commit'), ('url', 'https://github.com/other/maps/releases/tag/monaco-packed-v1-test')]:
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(original); changed[key] = value; self.write(receipt_path, changed)
                with self.assertRaises(ValueError): catalog.documents(self.plan, [path])
        receipt_path.unlink()
        with self.assertRaises(FileNotFoundError): catalog.documents(self.plan, [path])

    def test_changed_plan_identity_semantic_proof_or_source_bytes_are_rejected(self):
        path = self.add('monaco')
        original = json.loads(path.read_text())
        for key, value in [('release_tag', 'another-generation'), ('region', 'other-region'), ('source_sqlite_sha256', 'f' * 64),
                           ('source_bundle_version', 'changed'), ('source_installed_bytes', 1001),
                           ('source_download_bytes', 401), ('previous_published_download_bytes', 401),
                           ('packed_installed_bytes', True), ('packed_download_bytes', -1), ('verification', {})]:
            with self.subTest(key=key):
                changed = copy.deepcopy(original); changed[key] = value; self.write(path, changed)
                with self.assertRaises(ValueError): catalog.documents(self.plan, [path])

    def test_unsafe_duplicate_or_missing_manifest_assets_are_rejected(self):
        path = self.add('monaco')
        original = json.loads(path.read_text())
        for files in [[{'file': '../manifest.json', 'bytes': 1, 'sha256': 'c' * 64}],
                      [{'file': 'monaco_manifest.json', 'bytes': 1, 'sha256': 'bad'}],
                      [{'file': 'other.json', 'bytes': 1, 'sha256': 'c' * 64}],
                      original['release_files'] * 2,
                      [{'file': 'monaco_manifest.json', 'bytes': 1024 * 1024 + 1, 'sha256': 'c' * 64}]]:
            changed = copy.deepcopy(original); changed['release_files'] = files; self.write(path, changed)
            with self.assertRaises(ValueError): catalog.documents(self.plan, [path])

    def test_completeness_duplicate_results_and_alias_without_canonical_are_rejected(self):
        one = self.add('monaco'); self.add('alsace')
        with self.assertRaises(ValueError): catalog.documents(self.plan, [one], require_complete=True)
        with self.assertRaises(ValueError): catalog.documents(self.plan, [one, one])
        alias = self.add('karlsruhe-regbez', 'deu-v3-data-karlsruhe-latest')
        with self.assertRaises(ValueError): catalog.documents(self.plan, [alias])

    def test_previous_installed_bytes_unknown_remain_empty_instead_of_invented(self):
        path = self.add('monaco')
        self.plan['bundles'][0]['source_manifest_document']['db'].pop('uncompressed_bytes')
        _, comparison = catalog.documents(self.plan, [path])
        row = comparison['bundles'][0]
        self.assertIsNone(row['previous_published_installed_bytes'])
        self.assertIsNone(row['previous_published_installed_change_percent'])
        self.assertIsNone(comparison['catalog_region_totals']['previous_published_installed_bytes'])
        self.assertEqual(list(csv.DictReader(io.StringIO(catalog.csv_document(comparison))))[0]['previous_published_installed_bytes'], '')

    def test_cli_writes_three_local_artifacts_and_refuses_draft_before_overwrite(self):
        path = self.add('monaco'); plan = self.root / 'plan.json'; self.write(plan, self.plan)
        output = self.root / 'output'
        command = [sys.executable, str(Path(catalog.__file__)), '--plan', str(plan), '--results', str(path),
                   '--output-dir', str(output), '--require-complete']
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p.name for p in output.iterdir()), ['catalog.json', 'size-comparison.csv', 'size-comparison.json'])
        before = (output / 'catalog.json').read_bytes()
        self.edit(path.with_name('github-verified.json'), 'published', False)
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((output / 'catalog.json').read_bytes(), before)

    def test_actual_pinned_plan_has_55_release_rows_and_54_canonical_regions(self):
        # Synthetic receipt values exercise the committed plan's identities;
        # they do not claim that its real releases have been published.
        template_path = self.add('template')
        template = json.loads(template_path.read_text())
        plan = catalog.read_json(catalog.DEFAULT_PLAN)
        paths = []
        for entry in plan['bundles']:
            source = entry['source_manifest_document']['db']
            result = copy.deepcopy(template)
            for key in ['region', 'source_release_tag', 'release_tag', 'bundle_version', 'source_bundle_version']:
                result[key] = entry[key]
            result['source_sqlite_sha256'] = source.get('uncompressed_sha256') or ('a' * 64)
            if source.get('compression') in [None, '', 'none', 'identity']:
                result['source_sqlite_sha256'] = source['sha256']
            result['source_installed_bytes'] = source.get('uncompressed_bytes') or source['bytes'] * 2
            if source.get('compression') in [None, '', 'none', 'identity']:
                result['source_installed_bytes'] = source['bytes']
            result['source_download_bytes'] = source['bytes']
            result['previous_published_download_bytes'] = sum(asset['size'] for asset in entry['database_assets'])
            result['release_files'][0]['file'] = entry['manifest_file']
            directory = self.root / entry['source_release_tag']; directory.mkdir()
            path = directory / 'result.json'; self.write(path, result); paths.append(path)
            self.write(directory / 'github-verified.json', {
                'release_tag': entry['release_tag'], 'url': 'https://github.com/' + plan['repo'] + '/releases/tag/' + entry['release_tag'],
                'source_commit': 'e' * 40, 'all_asset_hashes_verified': True, 'asset_count': 1, 'published': True})
        document, comparison = catalog.documents(plan, paths, require_complete=True)
        self.assertEqual(len(document['bundles']), 54)
        self.assertEqual(comparison['release_count'], 55)
        self.assertEqual(sum(row['catalog_selected'] for row in comparison['bundles']), 54)

    def test_draft_comparison_requires_verified_status_and_never_returns_catalog(self):
        path = self.add('monaco')
        receipt = path.with_name('github-verified.json')
        self.edit(receipt, 'published', False)
        self.edit(receipt, 'url', 'https://github.com/owner/maps/releases/tag/untagged-abc123')
        document, comparison = catalog.documents(self.plan, [path], require_complete=True, draft_comparison_only=True)
        self.assertIsNone(document)
        self.assertFalse(comparison['catalog_generated'])
        self.assertEqual(comparison['bundles'][0]['release_status'], 'draft')
        self.assertEqual(list(csv.DictReader(io.StringIO(catalog.csv_document(comparison))))[0]['release_status'], 'draft')
        with self.assertRaises(ValueError): catalog.documents(self.plan, [path])
        self.add('alsace')
        with self.assertRaises(ValueError): catalog.documents(self.plan, [path], require_complete=True, draft_comparison_only=True)
        self.edit(receipt, 'all_asset_hashes_verified', False)
        with self.assertRaises(ValueError): catalog.documents(self.plan, [path], draft_comparison_only=True)

    def test_draft_comparison_cli_writes_no_catalog_and_preserves_existing_catalog(self):
        path = self.add('monaco'); self.edit(path.with_name('github-verified.json'), 'published', False)
        plan = self.root / 'plan.json'; self.write(plan, self.plan)
        output = self.root / 'draft-output'
        command = [sys.executable, str(Path(catalog.__file__)), '--plan', str(plan), '--results', str(path),
                   '--output-dir', str(output), '--require-complete', '--draft-comparison-only']
        process = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(sorted(p.name for p in output.iterdir()), ['size-comparison.csv', 'size-comparison.json'])
        existing = output / 'catalog.json'; existing.write_text('published-catalog-must-stay')
        previous = (output / 'size-comparison.json').read_bytes()
        process = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(existing.read_text(), 'published-catalog-must-stay')
        self.assertEqual((output / 'size-comparison.json').read_bytes(), previous)


if __name__ == '__main__':
    unittest.main()
