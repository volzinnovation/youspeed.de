"""Exercise release publication against a stateful fake gh CLI, without networking."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


PUBLISHER = Path(__file__).resolve().parents[1] / "publish_v3_release_assets.sh"


class PublishV3ReleaseAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle with spaces"
        self.bundle.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.state_path = self.root / "github.json"
        self.calls_path = self.root / "calls.jsonl"
        self.env = {
            **os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "MOCK_GH_STATE": str(self.state_path),
            "MOCK_GH_CALLS": str(self.calls_path),
        }
        fake = self.bin / "gh"
        fake.write_text("#!" + sys.executable + "\n" + textwrap.dedent('''\
            import json
            import os
            from pathlib import Path
            import sys

            args = sys.argv[1:]
            with open(os.environ["MOCK_GH_CALLS"], "a") as out:
                out.write(json.dumps(args) + "\\n")
            state_path = Path(os.environ["MOCK_GH_STATE"])
            state = json.loads(state_path.read_text())
            assert args[0] == "release", args
            operation = args[1]
            if operation == "view":
                sys.exit(0 if state["exists"] else 1)
            if operation == "create":
                assert not state["exists"], "Release already exists"
                state.update(exists=True, draft="--draft" in args)
            elif operation == "upload":
                assert state["exists"]
                asset = Path(args[3].split("#", 1)[0])
                if asset.name == os.environ.get("MOCK_FAIL_ASSET"):
                    sys.exit(23)
                state["assets"][asset.name] = asset.read_text()
            elif operation == "edit":
                assert state["exists"]
                if "--draft=false" in args:
                    state["draft"] = False
            else:
                raise AssertionError("Unexpected release operation: " + operation)
            state_path.write_text(json.dumps(state))
        '''))
        fake.chmod(0o755)
        self.set_state(exists=True)
        self.write("A_manifest.json", json.dumps({
            "format": "youspeed.v3.bundle.manifest", "bundle_version": "new",
            "db": {"file": "speeds.sqlite.gz"},
            "penalty_rules": {"file": "CHE-rules.json"},
        }))
        self.write("CHE-rules.json", '{"rules": "new"}')
        self.write("speeds.sqlite.gz", "new database")
        self.write("Z-build-proof.json", '{"commit": "new"}')

    def write(self, name, content):
        path = self.bundle / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def set_state(self, *, exists, draft=False):
        self.state_path.write_text(json.dumps({
            "exists": exists, "draft": draft, "tag": "unchanged-tag-commit",
            "assets": {"A_manifest.json": "old manifest", "old-delta.sqlite": "preserve me"}
            if exists else {},
        }))

    def run_publisher(self, *extra, fail_asset=None):
        env = dict(self.env)
        if fail_asset:
            env["MOCK_FAIL_ASSET"] = fail_asset
        return subprocess.run([
            "bash", str(PUBLISHER), "--repo", "example/repo", "--tag", "bundle-latest",
            "--bundle-dir", str(self.bundle), "--title", "Bundle title", *extra,
        ], env=env, text=True, capture_output=True)

    def state(self):
        return json.loads(self.state_path.read_text())

    def calls(self):
        return [json.loads(line) for line in self.calls_path.read_text().splitlines()] \
            if self.calls_path.exists() else []

    def uploads(self):
        return [Path(call[3].split("#", 1)[0]).name for call in self.calls() if call[1] == "upload"]

    def test_existing_release_keeps_tag_and_unrelated_assets_and_uploads_manifest_last(self):
        result = self.run_publisher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.uploads(), ["CHE-rules.json", "Z-build-proof.json", "speeds.sqlite.gz", "A_manifest.json"])
        self.assertEqual(self.state()["assets"]["old-delta.sqlite"], "preserve me")
        self.assertEqual(self.state()["tag"], "unchanged-tag-commit")
        self.assertFalse(self.state()["draft"])
        self.assertNotIn("create", [call[1] for call in self.calls()])
        self.assertEqual(self.calls()[-1][1], "edit")

    def test_dependency_upload_failure_preserves_release_and_old_manifest(self):
        result = self.run_publisher(fail_asset="speeds.sqlite.gz")
        self.assertEqual(result.returncode, 23)
        self.assertTrue(self.state()["exists"])
        self.assertEqual(self.state()["assets"]["A_manifest.json"], "old manifest")
        self.assertEqual(self.state()["assets"]["old-delta.sqlite"], "preserve me")
        self.assertEqual(self.state()["tag"], "unchanged-tag-commit")
        self.assertNotIn("A_manifest.json", self.uploads())
        self.assertNotIn("edit", [call[1] for call in self.calls()])

    def test_new_release_is_created_as_draft_and_published_after_uploads(self):
        self.set_state(exists=False)
        result = self.run_publisher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--draft", self.calls()[1])
        self.assertEqual(self.calls()[-2][1], "upload")
        self.assertEqual(self.calls()[-1][1], "edit")
        self.assertIn("--draft=false", self.calls()[-1])
        self.assertFalse(self.state()["draft"])

    def test_failed_new_release_stays_draft_and_can_be_resumed(self):
        self.set_state(exists=False)
        result = self.run_publisher(fail_asset="speeds.sqlite.gz")
        self.assertEqual(result.returncode, 23)
        self.assertTrue(self.state()["draft"])
        self.assertNotIn("A_manifest.json", self.state()["assets"])
        result = self.run_publisher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.state()["draft"])
        self.assertEqual(sum(call[1] == "create" for call in self.calls()), 1)

    def test_explicit_draft_stays_hidden(self):
        self.set_state(exists=False)
        result = self.run_publisher("--draft")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.state()["draft"])
        self.assertNotIn("--draft=false", self.calls()[-1])

    def test_multiple_manifests_are_all_uploaded_after_dependencies(self):
        self.write("B_manifest.json", json.dumps({"format": "youspeed.v3.bundle.manifest"}))
        result = self.run_publisher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.uploads()[-2:], ["A_manifest.json", "B_manifest.json"])

    def test_duplicate_basename_fails_before_any_github_call(self):
        self.write("nested/CHE-rules.json", "{}")
        result = self.run_publisher()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate release asset basename", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_invalid_json_fails_before_any_github_call(self):
        self.write("A_manifest.json", "invalid json")
        result = self.run_publisher()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid JSON release asset", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_missing_manifest_fails_before_any_github_call(self):
        (self.bundle / "A_manifest.json").unlink()
        result = self.run_publisher()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No youspeed.v3.bundle.manifest", result.stderr)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
