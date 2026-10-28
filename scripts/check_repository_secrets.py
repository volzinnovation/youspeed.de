#!/usr/bin/env python3
"""Offline, redacted credential checks for tracked files and reachable Git blobs.

Run ``python3 scripts/check_repository_secrets.py`` for the tracked working tree,
or add ``--history`` to also inspect every reachable blob once. No ignored files,
network requests, credential validation, or third-party packages are involved.

This is a prevention check, not proof that a repository contains no secrets.
All bytes are streamed through ASCII provider-token/private-key rules, including
binary files. Contextual literal/URL checks inspect printable text runs. ZIP
documents additionally receive bounded member and joined XML-text inspection.
Images are not OCRed; other compressed/encrypted formats are not decoded. Git
history supplies one representative path per object, not every historical alias
or historical Git LFS payload. Hydrated current LFS files are scanned normally.
An incomplete read/archive inspection fails explicitly instead of passing clean.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import html
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import zipfile
import zlib


CHUNK_BYTES = 1024 * 1024
OVERLAP_BYTES = 8192  # Longer than the maximum accepted credential match.
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 4096
ZIP_EXTENSIONS = {".zip", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub"}
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

# Deliberately case-sensitive ASCII rules; no entropy regex over large binaries.
PROVIDER_RULES = (
    ("github-token", rb"\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,255})\b"),
    ("huggingface-token", rb"\bhf_[A-Za-z0-9]{30,60}\b"),
    ("openai-token", rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,256}\b"),
    ("aws-access-key", rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ("google-api-key", rb"\bAIza[A-Za-z0-9_-]{35}\b"),
    ("google-oauth-secret", rb"\bGOCSPX-[A-Za-z0-9_-]{20,100}\b"),
    ("gitlab-token", rb"\bglpat-[A-Za-z0-9_-]{20,100}\b"),
    ("slack-token", rb"\bxox[baprs]-[A-Za-z0-9-]{16,200}\b"),
    ("stripe-secret-key", rb"\bsk_(?:live|test)_[A-Za-z0-9]{20,100}\b"),
    ("npm-token", rb"\bnpm_[A-Za-z0-9]{36}\b"),
    ("mapillary-token", rb"\bMLY\|[A-Za-z0-9_-]{8,256}\|[A-Za-z0-9_-]{16,256}"),
    ("private-key-body", rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[ \t]*(?:\r?\n|\\n)[A-Za-z0-9+/=]{16,2048}"),
)
PROVIDERS = tuple((name, re.compile(pattern)) for name, pattern in PROVIDER_RULES)
PROVIDER_PREFIX = re.compile(rb"gh[pousr]_|github_pat_|hf_|sk[-_]|AKIA|ASIA|AIza|GOCSPX-|glpat-|xox[baprs]-|npm_|MLY\||-----BEGIN ")
CONTEXT_PREFIX = re.compile(rb"://|(?:password|passwd|pwd|api[-_]?key|api[-_]?token|access[-_]?token|auth[-_]?token|secret[-_]?key|client[-_]?secret|token|secret)['\" \t:=]")
PRINTABLE = re.compile(rb"[\t\r\n\x20-\x7e]{4,65536}")
KEY = rb"(?:password|passwd|pwd|api[-_]?key|api[-_]?token|access[-_]?token|auth[-_]?token|secret[-_]?key|client[-_]?secret|token|secret)"
QUOTED_LITERAL = re.compile(
    rb"(?<![A-Za-z0-9_])['\"]?(?P<key>" + KEY + rb")[ '\"]{0,4}[:=][ \t]{0,32}(?P<quote>['\"])(?P<value>[^'\"\r\n]{1,2048})(?P=quote)", re.I)
BARE_LITERAL = re.compile(
    rb"(?m)^[ \t]{0,64}(?:export[ \t]+)?(?P<key>" + KEY + rb")[ \t]{0,16}[:=][ \t]{0,16}(?P<value>[A-Za-z0-9_+/=.!@%:-]{4,2048})[ \t]*(?:$|[#;])", re.I)
CREDENTIAL_URL = re.compile(
    rb"[A-Za-z][A-Za-z0-9+.-]{1,31}://(?P<user>[^\s/:@'\"<>]{1,256}):(?P<value>[^\s/@'\"<>]{1,2048})@[^\s/'\"<>]{1,256}")
XML_TAG = re.compile(rb"<[^>]{0,4096}>")
DUMMIES = frozenset({
    b"test", b"testing", b"dummy", b"example",
    b"changeme", b"change-me", b"replace-me", b"redacted", b"not-a-secret",
    b"test-password", b"dummy-password", b"example-password", b"test-token",
    b"dummy-token", b"example-token", b"test-secret", b"dummy-secret", b"wrong-test-password",
    b"example-secret", b"unused",
})


def placeholder(value: bytes) -> bool:
    """Only explicit demonstration values/references, never a file-wide allowlist."""
    lowered = value.lower()
    return (lowered in DUMMIES or
            (len(value) >= 8 and len(set(value)) == 1) or
            bool(re.fullmatch(rb"<[^<>\r\n]{1,128}>|\$[A-Za-z_][A-Za-z0-9_]*|\$\{[^}\r\n]{1,256}\}|\{\{[^\r\n]{1,256}\}\}|\\\([^\r\n]{1,256}\)", value)) or
            bool(re.fullmatch(rb"(?:YOUR|EXAMPLE|DUMMY|REPLACE_WITH)_[A-Z0-9_]{1,128}", value)))


def credential_literal(candidate, match, xml_context=None, context_offset=0):
    value, key = match["value"], match["key"].lower()
    if len(value) < 4 or placeholder(value):
        return False
    if key in {b"token", b"secret"}:
        # These words also name parser tokens, speech labels and schema data.
        # Keep their generic rule to credential-shaped literals; specific keys
        # such as access_token, api_key and password retain short-value checks.
        classes = (any(97 <= byte <= 122 for byte in value),
                   any(65 <= byte <= 90 for byte in value),
                   any(48 <= byte <= 57 for byte in value))
        return len(value) >= 16 and not any(byte in b" \t\r\n" for byte in value) and sum(classes) >= 2
    if key in {b"password", b"passwd", b"pwd"} and value in {b"false", b"true"}:
        # Android UI hierarchy XML has a boolean password-field attribute. This
        # does not exempt the same string used as an actual JSON/env password.
        context = candidate if xml_context is None else xml_context
        start = context_offset + match.start()
        if context.rfind(b"<", 0, start) > context.rfind(b">", 0, start):
            return False
    return True


def demonstration_url(match):
    """RFC-reserved example destinations cannot represent a service credential."""
    try:
        host = (urlsplit(match.group().decode("ascii")).hostname or "").lower().rstrip(".")
    except (UnicodeError, ValueError):
        return False
    return (host.endswith((".invalid", ".test", ".example")) or
            host in {"invalid", "test", "example"} or
            any(host == domain or host.endswith("." + domain) for domain in ("example.com", "example.org", "example.net")))


def safe_location(location: str) -> str:
    """Even malicious archive/member names cannot echo provider token material."""
    raw = location.encode("utf-8", "backslashreplace")
    for _, pattern in PROVIDERS:
        raw = pattern.sub(b"[redacted]", raw)
    raw = CREDENTIAL_URL.sub(b"[credential-url-redacted]", raw)
    for pattern in (QUOTED_LITERAL, BARE_LITERAL):
        raw = pattern.sub(b"[credential-assignment-redacted]", raw)
    return raw.decode("utf-8", "replace")


def path_rules(name: str) -> list[str]:
    path = PurePosixPath(name)
    parts = tuple(part.lower() for part in path.parts)
    base = path.name.lower()
    found = []
    if base == ".env" or (base.startswith(".env.") and base not in {".env.example", ".env.sample", ".env.template"}):
        found.append("credential-env-path")
    if any(part in {"secret", "secrets", ".secret", ".secrets", "credentials", ".credentials"} for part in parts[:-1]):
        found.append("credential-directory")
    if (path.suffix.lower() in {".pem", ".key", ".p8", ".p12", ".pfx", ".jks", ".keystore", ".mobileprovision", ".provisionprofile"}
            or base in {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", ".npmrc", ".pypirc"}
            or (base == "credentials" and ".aws" in parts[:-1])):
        found.append("credential-material-path")
    return found


@dataclass(frozen=True)
class Diagnostic:
    kind: str
    rule: str
    location: str
    line: int | None = None
    byte_offset: int | None = None


class Scanner:
    def __init__(self):
        self.diagnostics: set[Diagnostic] = set()
        self.files = 0
        self.blobs = 0
        self.raw_bytes = 0
        self.tree_bytes = 0
        self.history_bytes = 0
        self.archive_members = 0
        self.binary_members = 0

    def report(self, rule, location, *, kind="secret", line=None, byte_offset=None):
        self.diagnostics.add(Diagnostic(kind, rule, safe_location(location), line, byte_offset))

    def check_path(self, name, location=None):
        for rule in path_rules(name):
            self.report(rule, location or name)

    def inspect_window(self, data, location, base_offset, base_line):
        def report_match(rule, match, relative=0):
            start = relative + match.start()
            self.report(rule, location, line=base_line + data.count(b"\n", 0, start), byte_offset=base_offset + start)

        # Prefix dispatch avoids eleven complete regex passes over large binary
        # model/video objects. Full patterns run only at plausible token starts.
        for prefix in PROVIDER_PREFIX.finditer(data):
            for rule, pattern in PROVIDERS:
                match = pattern.match(data, prefix.start())
                if match:
                    report_match(rule, match)
        if not CONTEXT_PREFIX.search(data.lower()):
            return
        # Context-sensitive case-insensitive patterns operate only on bounded
        # printable runs, not multi-gigabyte model/video/blob contents.
        previous_end = -1
        for run in PRINTABLE.finditer(data):
            # Consecutive long text runs need overlap too: a key/value may cross
            # the printable-run cap independently of the stream chunk boundary.
            candidate_start = max(0, run.start() - OVERLAP_BYTES) if run.start() == previous_end else run.start()
            previous_end = run.end()
            candidate = data[candidate_start:run.end()]
            if not CONTEXT_PREFIX.search(candidate.lower()):
                continue
            for match in CREDENTIAL_URL.finditer(candidate):
                if not placeholder(match["value"]) and not demonstration_url(match):
                    report_match("credential-url", match, candidate_start)
            for pattern in (QUOTED_LITERAL, BARE_LITERAL):
                for match in pattern.finditer(candidate):
                    if credential_literal(candidate, match, data, candidate_start):
                        report_match("literal-credential", match, candidate_start)

    def scan_stream(self, stream, location, size, *, archive_hint=False):
        tail, consumed, newlines = b"", 0, 0
        archive = None
        try:
            while True:
                chunk = stream.read(CHUNK_BYTES)
                if not chunk:
                    break
                if consumed == 0 and (archive_hint or chunk.startswith(ZIP_SIGNATURES)):
                    if size > MAX_ARCHIVE_BYTES:
                        self.report("archive-size-limit", location, kind="incomplete")
                    else:
                        archive = tempfile.TemporaryFile()
                if archive is not None:
                    archive.write(chunk)
                window = tail + chunk
                self.inspect_window(window, location, consumed - len(tail), 1 + newlines - tail.count(b"\n"))
                consumed += len(chunk)
                newlines += chunk.count(b"\n")
                self.raw_bytes += len(chunk)
                tail = window[-OVERLAP_BYTES:]
            if consumed != size:
                self.report("file-size-changed-or-truncated", location, kind="incomplete")
            if archive is not None:
                archive.seek(0)
                self.scan_archive(archive, location)
            elif archive_hint and consumed == 0:
                self.report("archive-unreadable", location, kind="incomplete")
        except (OSError, ValueError):
            self.report("content-unreadable", location, kind="incomplete")
        finally:
            if archive is not None:
                archive.close()

    def scan_archive(self, stream, location):
        try:
            with zipfile.ZipFile(stream) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_ARCHIVE_MEMBERS:
                    self.report("archive-member-count-limit", location, kind="incomplete")
                    return
                expanded = 0
                for entry in entries:
                    if entry.is_dir():
                        continue
                    member_location = location + "!" + entry.filename
                    self.check_path(entry.filename, member_location)
                    if stat.S_ISLNK(entry.external_attr >> 16):
                        self.report("archive-symlink-not-decoded", member_location, kind="incomplete")
                        continue
                    if entry.file_size > MAX_MEMBER_BYTES:
                        self.report("archive-member-size-limit", member_location, kind="incomplete")
                        continue
                    expanded += entry.file_size
                    if expanded > MAX_EXPANDED_BYTES:
                        self.report("archive-expanded-size-limit", member_location, kind="incomplete")
                        break
                    if entry.flag_bits & 1:
                        self.report("archive-encrypted-member", member_location, kind="incomplete")
                        continue
                    try:
                        with archive.open(entry) as member:
                            data = member.read(MAX_MEMBER_BYTES + 1)
                        if len(data) != entry.file_size or len(data) > MAX_MEMBER_BYTES:
                            self.report("archive-member-size-mismatch", member_location, kind="incomplete")
                            continue
                    except (OSError, RuntimeError, ValueError, NotImplementedError, zipfile.BadZipFile, zlib.error):
                        self.report("archive-member-unreadable", member_location, kind="incomplete")
                        continue
                    self.archive_members += 1
                    self.inspect_window(data, member_location, 0, 1)
                    if data.startswith(ZIP_SIGNATURES) or PurePosixPath(entry.filename).suffix.lower() in ZIP_EXTENSIONS:
                        self.report("nested-archive-not-decoded", member_location, kind="incomplete")
                    if PurePosixPath(entry.filename).suffix.lower() in {".xml", ".rels"}:
                        joined = html.unescape(XML_TAG.sub(b"", data).decode("utf-8", "replace")).encode("utf-8")
                        self.inspect_window(joined, member_location + "#xml-text", 0, 1)
                    elif b"\x00" in data[:8192]:
                        self.binary_members += 1
        except (OSError, RuntimeError, ValueError, NotImplementedError, zipfile.BadZipFile):
            self.report("archive-unreadable", location, kind="incomplete")


def git(root, *arguments):
    """Never expose Git stderr: paths/configuration can themselves contain secrets."""
    return subprocess.check_output(["git", "-C", str(root), *arguments], stderr=subprocess.DEVNULL, env=git_environment())


def git_environment():
    # A partial clone must fail on absent objects, never fetch them implicitly.
    return dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="", GIT_TERMINAL_PROMPT="0")


def open_tracked(root, path):
    """No symlink component is followed, even if working-tree types have changed."""
    parts = PurePosixPath(path).parts
    if not parts or any(part in {".", ".."} for part in parts) or PurePosixPath(path).is_absolute():
        raise ValueError("invalid tracked path")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("not a regular tracked file")
            return os.fdopen(descriptor, "rb")
        except BaseException:
            os.close(descriptor)
            raise
    finally:
        os.close(directory)


def scan_tree(root, scanner):
    entries = git(root, "ls-files", "--stage", "-z").split(b"\0")
    seen = set()
    for entry in entries:
        if not entry:
            continue
        metadata, path_bytes = entry.split(b"\t", 1)
        path = os.fsdecode(path_bytes)
        mode, _, stage = metadata.split()
        if path in seen:
            continue
        seen.add(path)
        scanner.check_path(path)
        if stage != b"0":
            scanner.report("unmerged-index-entry", path, kind="incomplete")
            continue
        if mode == b"120000":
            scanner.report("tracked-symlink-not-followed", path, kind="incomplete")
            continue
        if mode == b"160000":
            scanner.report("submodule-not-scanned", path, kind="incomplete")
            continue
        try:
            with open_tracked(root, path) as stream:
                scanner.files += 1
                if scanner.files % 500 == 0:
                    print(f"Credential check progress: tracked_files={scanner.files} streamed_bytes={scanner.raw_bytes}", file=sys.stderr, flush=True)
                before = scanner.raw_bytes
                scanner.scan_stream(stream, path, os.fstat(stream.fileno()).st_size,
                                    archive_hint=PurePosixPath(path).suffix.lower() in ZIP_EXTENSIONS)
                scanner.tree_bytes += scanner.raw_bytes - before
        except (OSError, ValueError):
            scanner.report("tracked-file-unreadable", path, kind="incomplete")


class LimitedReader:
    def __init__(self, stream, size):
        self.stream, self.remaining = stream, size

    def read(self, size):
        if self.remaining <= 0:
            return b""
        data = self.stream.read(min(size, self.remaining))
        self.remaining -= len(data)
        return data


def scan_history(root, scanner):
    """One rev-list and one persistent cat-file process; each blob read once."""
    with subprocess.Popen(["git", "-C", str(root), "rev-list", "--objects", "--all"],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=git_environment()) as objects, \
         subprocess.Popen(["git", "-C", str(root), "cat-file", "--batch"],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=git_environment()) as batch:
        aborted = False
        try:
            for item in objects.stdout:
                oid, _, path_bytes = item.rstrip(b"\n").partition(b" ")
                if not re.fullmatch(rb"[0-9a-f]{40,64}", oid):
                    scanner.report("history-object-list-invalid", "git-history", kind="incomplete")
                    aborted = True
                    break
                batch.stdin.write(oid + b"\n")
                batch.stdin.flush()
                header = batch.stdout.readline().split()
                if len(header) != 3 or not header[2].isdigit():
                    scanner.report("history-object-unreadable", "blob:" + oid.decode(), kind="incomplete")
                    aborted = True
                    break
                size = int(header[2])
                limited = LimitedReader(batch.stdout, size)
                if header[1] == b"blob":
                    scanner.blobs += 1
                    if scanner.blobs % 500 == 0:
                        print(f"Credential check progress: history_blobs={scanner.blobs} streamed_bytes={scanner.raw_bytes}", file=sys.stderr, flush=True)
                    path = os.fsdecode(path_bytes)
                    location = "blob:" + oid.decode() + (":" + path if path else "")
                    if path:
                        scanner.check_path(path, location)
                    before = scanner.raw_bytes
                    scanner.scan_stream(limited, location, size,
                                        archive_hint=PurePosixPath(path).suffix.lower() in ZIP_EXTENSIONS)
                    scanner.history_bytes += scanner.raw_bytes - before
                while limited.remaining:
                    if not limited.read(CHUNK_BYTES):
                        raise OSError("truncated Git object")
                if batch.stdout.read(1) != b"\n":
                    raise OSError("invalid Git object framing")
        except (OSError, ValueError, KeyboardInterrupt):
            aborted = True
            scanner.report("history-stream-incomplete", "git-history", kind="incomplete")
        finally:
            batch.stdin.close()
            # Explicit close prevents Popen.__exit__ from closing it twice.
            batch.stdin = None
            if aborted:
                for process in (objects, batch):
                    if process.poll() is None:
                        process.terminate()
            objects.wait()
            batch.wait()
            if objects.returncode or batch.returncode:
                scanner.report("history-git-command-failed", "git-history", kind="incomplete")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--history", action="store_true", help="also stream every reachable Git blob (may read many GB)")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository directory; defaults to the current directory")
    args = parser.parse_args(argv)
    scanner = Scanner()
    try:
        root = Path(os.fsdecode(git(args.repo, "rev-parse", "--show-toplevel")).strip())
        scan_tree(root, scanner)
        if args.history:
            scan_history(root, scanner)
    except KeyboardInterrupt:
        scanner.report("scan-interrupted", "git-repository", kind="incomplete")
    except (OSError, ValueError, subprocess.CalledProcessError):
        scanner.report("repository-scan-failed", "git-repository", kind="incomplete")
    for diagnostic in sorted(scanner.diagnostics, key=lambda d: (d.location, d.rule, d.byte_offset or -1)):
        print(json.dumps({key: value for key, value in diagnostic.__dict__.items() if value is not None}, ensure_ascii=True))
    incomplete = sum(d.kind == "incomplete" for d in scanner.diagnostics)
    hits = len(scanner.diagnostics) - incomplete
    print(json.dumps({"summary": {"tracked_files": scanner.files, "history_blobs": scanner.blobs,
                                "streamed_bytes": scanner.raw_bytes, "archive_members": scanner.archive_members,
                                "tree_bytes": scanner.tree_bytes, "history_bytes": scanner.history_bytes,
                                "binary_archive_members": scanner.binary_members,
                                "secret_hits": hits, "incomplete_checks": incomplete},
                      "limitations": "ASCII/token and printable-text checks; no OCR or decryption; non-ZIP compression is not decoded; history paths are representative object names; historical Git LFS payloads are not fetched or inspected."}))
    return 2 if incomplete else 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
