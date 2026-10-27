import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/map'))
import publish_packed_release as publisher


class PackedPublicationTests(unittest.TestCase):
    def test_unbound_qa_cannot_publish(self):
        with self.assertRaisesRegex(ValueError, 'Unknown QA report'):
            publisher.validate_qa({'ready_for_rollout': True, 'physical_devices_passed': ['iphone', 'android']}, {}, {}, 'a'*40)

    def test_qa_cannot_authorize_another_commit(self):
        qa = {'format': 'youspeed.packed-runtime.rollout-qa', 'schema_version': 1,
              'ready_for_rollout': True, 'physical_devices_passed': ['iphone', 'android'], 'source_commit': 'b'*40}
        with self.assertRaisesRegex(ValueError, 'another source commit'):
            publisher.validate_qa(qa, {}, {}, 'a'*40)

    def test_missing_draft_tag_is_distinct_from_network_failure(self):
        class Response:
            returncode = 1
            stderr = 'gh: Not Found (HTTP 404)'
        with patch.object(publisher.subprocess, 'run', return_value=Response()):
            self.assertIsNone(publisher.tag_commit('owner/repo', 'draft'))
            self.assertIn('/git/ref/tags/draft', publisher.subprocess.run.call_args.args[0][2])
        Response.stderr = 'network connection failed'
        with patch.object(publisher.subprocess, 'run', return_value=Response()):
            with self.assertRaisesRegex(ValueError, 'Could not verify'):
                publisher.tag_commit('owner/repo', 'draft')

    def test_lightweight_and_annotated_tags_resolve_exact_commit(self):
        class Response:
            returncode = 0
            stdout = json.dumps({'object': {'type': 'commit', 'sha': 'a'*40}})
        with patch.object(publisher.subprocess, 'run', return_value=Response()):
            self.assertEqual(publisher.tag_commit('owner/repo', 'tag'), 'a'*40)
        Response.stdout = json.dumps({'object': {'type': 'tag', 'sha': 'b'*40}})
        with patch.object(publisher.subprocess, 'run', return_value=Response()), patch.object(
            publisher.subprocess, 'check_output', return_value=json.dumps({'object': {'type': 'commit', 'sha': 'a'*40}})):
            self.assertEqual(publisher.tag_commit('owner/repo', 'tag'), 'a'*40)

    def test_v3_delta_dependency_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'bundle').mkdir()
            (root/'bundle'/'region_manifest.json').write_text(json.dumps({
                'format': 'youspeed.v4.bundle.manifest', 'min_app_version': '1.6', 'delta_index': {'url': 'old'}}))
            result = root/'result.json'
            result.write_text(json.dumps({'release_tag': 'region-packed-v1', 'region': 'region'}))
            with patch.object(sys, 'argv', ['publisher', '--result', str(result), '--source-commit', 'a'*40]):
                with patch.object(publisher.subprocess, 'run') as network:
                    with self.assertRaisesRegex(ValueError, 'SQL deltas'):
                        publisher.main()
                    network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
