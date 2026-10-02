"""Verify the release metadata reflects published transfer bytes, without fetching DBs."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('bundle_metadata', ROOT / 'scripts/map/build_v3_bundle_metadata.py')
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)


class BundleMetadataTests(unittest.TestCase):
    config = {'format': 'youspeed.v3.bundle.targets', 'countries': [
        {'country_id': 'germany', 'mode': 'regional_shards', 'regions': [{'region_id': 'germany/berlin'}]},
        {'country_id': 'switzerland', 'mode': 'single_country', 'regions': [{'region_id': 'switzerland'}]},
    ]}

    def manifest(self, region='berlin', **overrides):
        result = {'format': 'youspeed.v3.bundle.manifest', 'variant': 'v3', 'region': region,
                  'bundle_version': 'v1', 'created_at_utc': '2026-10-01T10:00:00Z',
                  'db': {'bytes': 120, 'uncompressed_bytes': 1000}}
        result.update(overrides)
        return result

    def test_configured_urls_match_clients_and_cover_all_51_regions(self):
        config = json.loads((ROOT / 'iphone/SpeedConsumerApp/BundleTargets.top10.json').read_text())
        rows = metadata.targets(config, 'volzinnovation/youspeed.de')
        self.assertEqual(51, len(rows))
        self.assertEqual(51, len({row[0] for row in rows}))
        self.assertIn(('germany|berlin', 'berlin', 'https://github.com/volzinnovation/youspeed.de/releases/download/berlin/berlin_manifest.json'), rows)

    def test_compressed_and_multipart_transfer_sizes_come_from_manifest(self):
        calls = []
        def fetch(url):
            calls.append(url)
            region = url.split('/')[-2]
            return self.manifest(region, db_parts=[{'bytes': 100}, {'bytes': 200}]) if region == 'berlin' else self.manifest(region)
        index = metadata.build(self.config, 'owner/repo', fetch)
        self.assertEqual([300, 120], [entry['download_bytes'] for entry in index['bundles']])
        self.assertEqual(['germany|berlin', 'switzerland|switzerland'], [entry['id'] for entry in index['bundles']])
        self.assertTrue(all(url.endswith('_manifest.json') for url in calls))
        self.assertTrue(all(entry['created_at_utc'] == '2026-10-01T10:00:00Z' for entry in index['bundles']))

    def test_missing_release_does_not_remove_other_entries_or_claim_unavailability(self):
        index = metadata.build(self.config, 'owner/repo', lambda url: None if '/berlin/' in url else self.manifest('switzerland'))
        self.assertEqual(['switzerland|switzerland'], [entry['id'] for entry in index['bundles']])

    def test_errors_abort_refresh_instead_of_writing_partial_metadata(self):
        for overrides in [{'db': {'bytes': 0}}, {'db_parts': [{'bytes': 2**63-1}, {'bytes': 1}]},
                          {'created_at_utc': 'invalid'}, {'created_at_utc': '2026-10-01T10:00:00'},
                          {'bundle_version': ''}, {'region': 'bayern'}]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                metadata.build(self.config, 'owner/repo', lambda url: self.manifest(**overrides))
        with self.assertRaises(TimeoutError):
            metadata.build(self.config, 'owner/repo', lambda url: (_ for _ in ()).throw(TimeoutError()))


if __name__ == '__main__':
    unittest.main()
