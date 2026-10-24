import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/map'))
import package_mobidata_v1_5_artwork as packager


class ArtworkPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.assets = self.root / 'shared'
        for subdir in ['originals', 'png']:
            (self.assets / subdir).mkdir(parents=True, exist_ok=True)
        self.artworks = []
        for code in ['DE:310', 'DE:311']:
            stem = code.lower().replace(':', '-')
            artwork = {'sign_code': code, 'license': 'Public domain'}
            for field, hash_field, subdir, extension in [
                ('original_path', 'original_sha256', 'originals', '.svg'),
                ('png_path', 'png_sha256', 'png', '.png'),
            ]:
                relative = f'{subdir}/{stem}{extension}'
                data = f'pinned fixture {code} {extension}'.encode()
                (self.assets / relative).write_bytes(data)
                artwork[field] = relative
                artwork[hash_field] = hashlib.sha256(data).hexdigest()
            self.artworks.append(artwork)
        self.manifest_path = self.assets / 'manifest.json'
        self.manifest = {'schema_version': 1, 'artworks': self.artworks, 'provenance': 'retained'}
        self.manifest_path.write_text(json.dumps(self.manifest))
        (self.assets / 'THIRD_PARTY_NOTICES.txt').write_text('Pinned notices\n')
        first = self.artworks[0]
        self.audit = {
            'schema_version': 1, 'source': {'record_count': 6, 'sha256': 'snapshot-hash'},
            'entries': [
                {'source_code': 'DE:310', 'count': 4, 'pictogram_key': 'DE:310',
                 'pictogram_original_path': 'shared/tsr/sign-pictograms/' + first['original_path'],
                 'pictogram_png_path': 'shared/tsr/sign-pictograms/' + first['png_path'],
                 'pictogram_status': 'existing_exact', 'display_eligible': True,
                 'classifier_capability': 'reference_only', 'notes': ['No classifier town class.']},
                {'source_code': 'DE:325.1', 'count': 2, 'pictogram_key': None,
                 'pictogram_original_path': None, 'pictogram_png_path': None,
                 'pictogram_status': 'missing_official_artwork', 'display_eligible': False,
                 'classifier_capability': 'absent', 'notes': []},
            ],
        }
        self.audit_path = self.root / 'audit.json'
        self.audit_path.write_text(json.dumps(self.audit))
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        (self.bundle / 'outer_manifest.json').write_text('leave unchanged')
        (self.bundle / 'speeds.sqlite').write_bytes(b'database fixture')

    def tearDown(self):
        self.temporary.cleanup()

    def package(self):
        return packager.package_artwork(self.bundle, self.audit_path, self.manifest_path)

    def test_subset_provenance_missing_coverage_and_repeat_without_stale_assets(self):
        coverage = self.package()
        self.assertEqual(coverage['packaged_pair_count'], 1)
        self.assertEqual(coverage['status_record_counts']['missing_official_artwork'], 2)
        self.assertFalse(coverage['missing_or_blocked_entries'][0]['display_eligible'])
        self.assertEqual((self.bundle / 'pictogram-audit.json').read_bytes(), self.audit_path.read_bytes())
        output = self.bundle / 'sign-pictograms'
        self.assertEqual(json.loads((output / 'manifest.json').read_text())['artworks'], self.artworks[:1])
        self.assertEqual(json.loads((output / 'manifest.json').read_text())['provenance'], 'retained')
        self.assertFalse((output / 'png/de-311.png').exists())
        first_bytes = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob('*') if p.is_file()}
        (output / 'png/stale.png').write_bytes(b'stale')
        self.package()
        self.assertEqual(first_bytes, {str(p.relative_to(output)): p.read_bytes() for p in output.rglob('*') if p.is_file()})
        self.assertEqual((self.bundle / 'outer_manifest.json').read_text(), 'leave unchanged')
        self.assertEqual((self.bundle / 'speeds.sqlite').read_bytes(), b'database fixture')

    def test_hash_failure_preserves_previous_output(self):
        self.package()
        manifest_before = (self.bundle / 'sign-pictograms/manifest.json').read_bytes()
        (self.assets / 'png/de-310.png').write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.package()
        self.assertEqual((self.bundle / 'sign-pictograms/manifest.json').read_bytes(), manifest_before)

    def test_path_traversal_rejected_before_copy(self):
        self.manifest['artworks'][0]['original_path'] = '../outside.svg'
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.audit['entries'][0]['pictogram_original_path'] = 'shared/tsr/sign-pictograms/../outside.svg'
        self.audit_path.write_text(json.dumps(self.audit))
        with self.assertRaisesRegex(ValueError, 'Unsafe artwork path'):
            self.package()
        self.assertFalse((self.bundle / 'sign-pictograms').exists())

    def test_audit_cannot_change_shared_path_or_count(self):
        self.audit['entries'][0]['pictogram_png_path'] = 'shared/tsr/sign-pictograms/png/different.png'
        self.audit_path.write_text(json.dumps(self.audit))
        with self.assertRaisesRegex(ValueError, 'disagrees with shared manifest'):
            self.package()
        self.audit['source']['record_count'] = 7
        self.audit_path.write_text(json.dumps(self.audit))
        with self.assertRaisesRegex(ValueError, 'do not reconcile'):
            self.package()


if __name__ == '__main__':
    unittest.main()
