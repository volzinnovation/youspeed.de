"""Synthetic offline regression tests for the repository credential checker."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import check_repository_secrets as check


def provider_sample():
    # Construct synthetic token shapes so this test source is itself scannable.
    return b"gh" + b"p_" + b"A1" * 18


def literal_sample(value=b"four-W0rds-and-unique-digits-729"):
    return b'"pass' + b'word": "' + value + b'"'


def zip_bytes(members):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return stream.getvalue()


class ContentChecks(unittest.TestCase):
    def scan(self, data, name="sample.txt", **kwargs):
        scanner = check.Scanner()
        scanner.scan_stream(io.BytesIO(data), name, len(data), **kwargs)
        return scanner

    def rules(self, scanner):
        return {item.rule for item in scanner.diagnostics}

    def test_common_provider_formats(self):
        samples = {
            "github-token": provider_sample(),
            "huggingface-token": b"hf" + b"_" + b"A1" * 16,
            "openai-token": b"sk" + b"-proj-" + b"A1" * 20,
            "aws-access-key": b"AK" + b"IA" + b"A1" * 8,
            "google-api-key": b"AI" + b"za" + b"A1" * 17 + b"B",
            "google-oauth-secret": b"GOC" + b"SPX-" + b"A1" * 12,
            "gitlab-token": b"gl" + b"pat-" + b"A1" * 12,
            "slack-token": b"xo" + b"xb-" + b"12-" * 8 + b"AB",
            "stripe-secret-key": b"sk" + b"_test_" + b"A1" * 12,
            "npm-token": b"np" + b"m_" + b"A1" * 18,
            "mapillary-token": b"ML" + b"Y|" + b"12345" * 3 + b"|" + b"A1" * 18,
        }
        for rule, sample in samples.items():
            with self.subTest(rule=rule):
                self.assertIn(rule, self.rules(self.scan(sample)))

    def test_private_key_requires_body_material(self):
        marker = b"-----BEGIN " + b"PRIVATE KEY-----\n"
        self.assertNotIn("private-key-body", self.rules(self.scan(marker + b"...\n")))
        self.assertIn("private-key-body", self.rules(self.scan(marker + b"MIIE" + b"A" * 64 + b"\n")))
        self.assertIn("private-key-body", self.rules(self.scan(marker.replace(b"\n", b"\\n") + b"MIIE" + b"A" * 64)))

    def test_literals_and_credential_urls(self):
        value = b"four-W0rds-and-unique-digits-729"
        self.assertIn("literal-credential", self.rules(self.scan(literal_sample(value))))
        uri = b"postgresql" + b"://reader:" + value + b"@127.0.0.1/report"
        self.assertIn("credential-url", self.rules(self.scan(uri)))
        self.assertIn("literal-credential", self.rules(self.scan(b"PASSWORD=" + value)))
        self.assertIn("literal-credential", self.rules(self.scan(literal_sample(b"password"))))

    def test_explicit_examples_and_references_are_not_literals(self):
        for value in (b"test-password", b"dummy", b"<password>", b"${DB_PASSWORD}",
                      b"$DB_PASSWORD", b"YOUR_API_TOKEN", b"{{ secrets.VALUE }}", b"x" * 40):
            with self.subTest(placeholder=True):
                self.assertNotIn("literal-credential", self.rules(self.scan(literal_sample(value))))
        self.assertNotIn("credential-url", self.rules(self.scan(b"postgresql" + b"://reader:${DB_PASSWORD}@localhost/db")))

    def test_test_directories_do_not_exempt_realistic_literals(self):
        scanner = self.scan(literal_sample(), "tests/fixtures/example.json")
        self.assertIn("literal-credential", self.rules(scanner))

    def test_literal_secret_prefix_is_not_hidden_by_later_interpolation(self):
        for suffix in (b"${DYNAMIC}", b"\\(dynamic)", b"{{ dynamic }}"):
            scanner = self.scan(literal_sample(b"unique-prefix-723" + suffix))
            self.assertIn("literal-credential", self.rules(scanner))

    def test_parser_token_words_and_xml_boolean_are_not_credentials(self):
        for data in (b'<node password="false" text="street"/>', '<node text="Straße" password="false"/>'.encode(), b'<node password="true"/>',
                     b'token = "SELECT"', b'token = "Words in Natural Speech"'):
            self.assertNotIn("literal-credential", self.rules(self.scan(data)))
        self.assertIn("literal-credential", self.rules(self.scan(literal_sample(b"false"))))
        self.assertIn("literal-credential", self.rules(self.scan(b'"to' + b'ken": "' + b'A1b2C3d4E5f6g7H8' + b'"')))

    def test_only_reserved_url_destinations_are_demonstration_context(self):
        value = b"four-W0rds-and-unique-digits-729"
        for host in (b"test.invalid", b"example.com", b"service.example.org", b"host.test", b"host.example"):
            self.assertNotIn("credential-url", self.rules(self.scan(b"postgresql" + b"://reader:" + value + b"@" + host)))
        for host in (b"localhost", b"127.0.0.1", b"10.0.0.1", b"example.com.real-service.net"):
            self.assertIn("credential-url", self.rules(self.scan(b"postgresql" + b"://reader:" + value + b"@" + host)))

    def test_streaming_binary_and_boundary_matches(self):
        prefix = b"\x00\xff\x00\n" * (check.CHUNK_BYTES // 4 - 3)
        data = prefix + provider_sample() + b"\x00\xff" * 8000
        scanner = self.scan(data, "model.bin")
        hits = [item for item in scanner.diagnostics if item.rule == "github-token"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].byte_offset, len(prefix))
        self.assertEqual(scanner.raw_bytes, len(data))

    def test_no_last_chunk_or_final_line_is_skipped(self):
        data = b"\x00" * (check.CHUNK_BYTES * 2 + 7) + provider_sample()
        self.assertIn("github-token", self.rules(self.scan(data, "large.bin")))

    def test_contextual_match_crosses_printable_run_cap(self):
        data = b" " * 65531 + literal_sample() + b" " * 9000
        self.assertIn("literal-credential", self.rules(self.scan(data)))

    def test_zip_document_scans_joined_xml_runs(self):
        sample = provider_sample()
        data = zip_bytes({"word/document.xml": b"<w:p><w:t>" + sample[:14] + b"</w:t><w:t>" + sample[14:] + b"</w:t></w:p>"})
        scanner = self.scan(data, "report.docx", archive_hint=True)
        self.assertTrue(any(item.rule == "github-token" and "#xml-text" in item.location for item in scanner.diagnostics))
        self.assertEqual(scanner.archive_members, 1)

    def test_archive_member_errors_fail_explicitly(self):
        data = zip_bytes({"document.xml": b"x" * 100})
        with patch.object(check, "MAX_MEMBER_BYTES", 50):
            self.assertIn("archive-member-size-limit", self.rules(self.scan(data, "report.docx")))
        with patch.object(zipfile.ZipFile, "open", side_effect=RuntimeError("synthetic-private-error")):
            scanner = self.scan(data, "report.docx")
        self.assertIn("archive-member-unreadable", self.rules(scanner))
        self.assertNotIn("synthetic-private-error", repr(scanner.diagnostics))

    def test_archive_total_and_compressed_size_limits_are_reported(self):
        data = zip_bytes({"a.xml": b"a" * 30, "b.xml": b"b" * 30})
        with patch.object(check, "MAX_EXPANDED_BYTES", 40):
            self.assertIn("archive-expanded-size-limit", self.rules(self.scan(data)))
        with patch.object(check, "MAX_ARCHIVE_BYTES", 30):
            self.assertIn("archive-size-limit", self.rules(self.scan(data)))

    def test_corrupt_and_nested_archives_are_incomplete(self):
        self.assertIn("archive-unreadable", self.rules(self.scan(b"broken", "report.docx", archive_hint=True)))
        nested = zip_bytes({"nested.zip": zip_bytes({"a.txt": b"hello"})})
        self.assertIn("nested-archive-not-decoded", self.rules(self.scan(nested)))

    def test_paths_have_no_directory_wide_allowlist(self):
        for name in ("config/.env", "config/.env.prod", "secrets/value.txt", "nested/credentials/a.json",
                     "release/upload.keystore", "nested/id_ed25519", ".aws/credentials"):
            with self.subTest(name=name):
                self.assertTrue(check.path_rules(name))
        for name in (".env.example", ".env.template", "docs/secrets.md", "keychain.swift"):
            self.assertFalse(check.path_rules(name))
        self.assertIn("literal-credential", self.rules(self.scan(literal_sample(), ".env.example")))

    def test_locations_cannot_echo_secret_material_or_control_characters(self):
        secret = provider_sample()
        safe = check.safe_location("archive!" + secret.decode() + "\nmember")
        self.assertNotIn(secret.decode(), safe)
        # The output format is JSON, so even newlines in malicious names are escaped.
        rendered = json.dumps({"location": safe})
        self.assertNotIn("\n", rendered)


class GitChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run_git("init", "-q", "--initial-branch=fixture")

    def run_git(self, *arguments):
        return subprocess.check_output(["git", "-C", str(self.root), *arguments], stderr=subprocess.DEVNULL)

    def commit(self):
        # Commits are confined to disposable synthetic fixture repositories.
        self.run_git("-c", "user.name=Credential Scanner Test", "-c", "user.email=scanner@example.invalid",
                     "commit", "-q", "-m", "synthetic scanner fixture")

    def add(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.run_git("add", "--", name)

    def test_ignored_untracked_file_is_never_read(self):
        self.add(".gitignore", b"private-local.txt\n")
        (self.root / "private-local.txt").write_bytes(provider_sample())
        scanner = check.Scanner()
        check.scan_tree(self.root, scanner)
        self.assertFalse(scanner.diagnostics)
        self.assertEqual(scanner.files, 1)

    def test_missing_tracked_file_is_incomplete(self):
        self.add("tracked.txt", b"hello")
        (self.root / "tracked.txt").unlink()
        scanner = check.Scanner()
        check.scan_tree(self.root, scanner)
        self.assertTrue(any(item.rule == "tracked-file-unreadable" for item in scanner.diagnostics))

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires POSIX symlink controls")
    def test_tracked_symlink_is_not_followed_and_history_scans_its_blob(self):
        target = provider_sample().decode()
        (self.root / target).write_bytes(literal_sample())
        (self.root / "link").symlink_to(target)
        self.run_git("add", "--", "link")
        self.commit()
        tree = check.Scanner()
        check.scan_tree(self.root, tree)
        self.assertEqual({item.rule for item in tree.diagnostics}, {"tracked-symlink-not-followed"})
        history = check.Scanner()
        check.scan_history(self.root, history)
        self.assertTrue(any(item.rule == "github-token" for item in history.diagnostics))
        self.assertFalse(any(item.rule == "literal-credential" for item in history.diagnostics))

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires POSIX symlink controls")
    def test_changed_ancestor_symlink_is_not_followed(self):
        self.add("directory/tracked.txt", b"hello")
        (self.root / "directory/tracked.txt").unlink()
        (self.root / "directory").rmdir()
        (self.root / "other").mkdir()
        (self.root / "other/tracked.txt").write_bytes(provider_sample())
        (self.root / "directory").symlink_to("other", target_is_directory=True)
        scanner = check.Scanner()
        check.scan_tree(self.root, scanner)
        self.assertEqual({item.rule for item in scanner.diagnostics}, {"tracked-file-unreadable"})

    def test_history_finds_deleted_blob_and_outputs_only_redacted_locations(self):
        self.add("old.txt", provider_sample())
        self.commit()
        self.run_git("rm", "-q", "old.txt")
        self.add("clean.txt", b"nothing sensitive\n")
        self.commit()
        tree = check.Scanner()
        check.scan_tree(self.root, tree)
        self.assertFalse(tree.diagnostics)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = check.main(["--repo", str(self.root), "--history"])
        self.assertEqual(result, 1)
        self.assertNotIn(provider_sample().decode(), output.getvalue())
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(any(record.get("rule") == "github-token" and record["location"].startswith("blob:") for record in records))
        self.assertEqual(records[-1]["summary"]["history_blobs"], 2)

    def test_exit_two_for_incomplete_checks(self):
        self.add("report.docx", b"corrupt document")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = check.main(["--repo", str(self.root)])
        self.assertEqual(result, 2)
        self.assertTrue(json.loads(output.getvalue().splitlines()[-1])["summary"]["incomplete_checks"])

    def test_missing_history_blob_terminates_without_pipe_deadlock(self):
        self.add("tracked.txt", b"synthetic fixture\n")
        self.commit()
        oid = self.run_git("rev-parse", "HEAD:tracked.txt").decode().strip()
        (self.root / ".git/objects" / oid[:2] / oid[2:]).unlink()
        script = Path(check.__file__).resolve()
        result = subprocess.run([os.sys.executable, str(script), "--repo", str(self.root), "--history"],
                                capture_output=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"incomplete", result.stdout)
        self.assertNotIn(b"Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
