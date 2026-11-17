#!/usr/bin/env python3
"""Publish frozen KI bytes from the Mac's existing HF login; dry-run by default.

No credentials are sent to KI. Only explicitly inventoried new-build paths are
allowed. Execute this code locally after reading it over SSH, setting
_PUBLISHER_BYTES_SHA256 to the hash of those exact source bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import math
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import time

REPO = "loffenauer/streetshots"
SCHEMA = "streetshots-ki-publish-inventory-v1"
KI_ROOT = "/home/raphael/streetshots-d5-20261114"
KI_HOST = "wingki01"
PREFIXES = {"model": "detector/d5/", "dataset": "reviews/detector-pilot-2026-11-14/"}
MAX_BATCH_BYTES = 64 * 1024 * 1024
MAX_BATCH_FILES = 200
MAX_INVENTORY_BYTES = 16 * 1024 * 1024
HEX = {40: re.compile(r"[0-9a-f]{40}\Z"), 64: re.compile(r"[0-9a-f]{64}\Z")}


def require_digest(value, length):
    if not isinstance(value, str) or not HEX[length].fullmatch(value):
        raise ValueError(f"Expected lowercase {length}-character digest")
    return value


def safe_path(value, absolute=False):
    if not isinstance(value, str) or not value or "\\" in value or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid path")
    path = PurePosixPath(value)
    if path.is_absolute() != absolute or str(path) != value or ".." in path.parts or "." in path.parts:
        raise ValueError("Noncanonical or unsafe path")
    if absolute and (not value.startswith(KI_ROOT + "/") or value == KI_ROOT):
        raise ValueError("KI path must be inside the fixed job root")
    return value


def validate_inventory(value):
    if not isinstance(value, dict) or value.get("schema") != SCHEMA or value.get("repository") != REPO:
        raise ValueError("Unexpected inventory schema or repository")
    kind = value.get("repo_type")
    if kind not in PREFIXES:
        raise ValueError("Expected model or dataset repository")
    parent = value.get("expected_parent_revision")
    if parent is not None:
        require_digest(parent, 40)
    rows = value.get("files")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20000:
        raise ValueError("Inventory needs 1..20000 explicit files")
    destinations = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("File inventory entry must be an object")
        source = safe_path(row.get("source_path"), absolute=True)
        destination = safe_path(row.get("path_in_repo"))
        if not destination.startswith(PREFIXES[kind]) or destination == PREFIXES[kind].rstrip("/"):
            raise ValueError("Destination is outside the authorized new-build prefix")
        if destination in destinations:
            raise ValueError("Duplicate destination")
        destinations.add(destination)
        if type(row.get("size")) is not int or not 0 <= row["size"] <= MAX_BATCH_BYTES:
            raise ValueError("Individual file exceeds the 64 MiB memory limit or has invalid size")
        require_digest(row.get("sha256"), 64)
        require_digest(row.get("git_blob_sha1"), 40)
    manifest_path = safe_path(value.get("manifest_path_in_repo"))
    if manifest_path not in destinations:
        raise ValueError("Declared manifest must be among the explicit inventoried files")
    return sorted(rows, key=lambda row: row["path_in_repo"])


def content_hashes(data):
    return {
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob_sha1": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def verify_payload(row, data):
    observed = content_hashes(data)
    if any(observed[key] != row[key] for key in observed):
        raise ValueError("Source bytes changed: " + row["path_in_repo"])


def batches(rows):
    pending, size = [], 0
    for row in rows:
        if row["size"] > MAX_BATCH_BYTES:
            raise ValueError("Individual file exceeds batch memory limit")
        if pending and (len(pending) == MAX_BATCH_FILES or size + row["size"] > MAX_BATCH_BYTES):
            yield pending
            pending, size = [], 0
        pending.append(row)
        size += row["size"]
    if pending:
        yield pending


def remote_matches(entry, row):
    if getattr(entry, "size", None) != row["size"]:
        return False
    lfs = getattr(entry, "lfs", None)
    if lfs:
        digest = lfs.get("sha256") if isinstance(lfs, dict) else lfs.sha256
        return digest == row["sha256"]
    return getattr(entry, "blob_id", None) == row["git_blob_sha1"]


# This program has no HF imports, environment reads, credentials or network use.
# Its only writes are exclusive JSON receipt creation inside this task's root.
REMOTE = r'''
import hashlib, json, os, stat, sys
from pathlib import Path, PurePosixPath
ROOT = Path("/home/raphael/streetshots-d5-20261114")
LIMIT = 64 * 1024 * 1024
def checked(value, writing=False):
    p = Path(value)
    if not isinstance(value, str) or not p.is_absolute() or str(PurePosixPath(value)) != value or ".." in p.parts:
        raise ValueError("Unsafe KI path")
    if not p.is_relative_to(ROOT) or p == ROOT or p.resolve() != p:
        raise ValueError("Path escapes job root or follows a symlink")
    if not writing and (not p.is_file() or not stat.S_ISREG(p.stat().st_mode)):
        raise ValueError("Regular KI file required")
    return p
def hashes(p):
    n = p.stat().st_size
    h, g = hashlib.sha256(), hashlib.sha1(b"blob " + str(n).encode() + b"\0")
    observed = 0
    with p.open("rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block: break
            observed += len(block)
            h.update(block); g.update(block)
    if observed != n: raise ValueError("Source size changed while hashing")
    return dict(size=n, sha256=h.hexdigest(), git_blob_sha1=g.hexdigest())
request = json.loads(sys.stdin.buffer.read(16 * 1024 * 1024 + 1))
op = request["operation"]
if op == "inventory":
    p = checked(request["path"])
    if p.stat().st_size > 16 * 1024 * 1024: raise ValueError("Inventory too large")
    sys.stdout.buffer.write(p.read_bytes())
elif op == "audit":
    for row in request["files"]:
        observed = hashes(checked(row["source_path"]))
        if any(observed[k] != row[k] for k in observed):
            raise ValueError("Frozen KI input changed: " + row["source_path"])
    sys.stdout.write(json.dumps({"verified": len(request["files"])}))
elif op == "fetch":
    rows = request["files"]
    if len(rows) > 200 or sum(row["size"] for row in rows) > LIMIT:
        raise ValueError("Batch exceeds memory policy")
    for row in rows:
        p = checked(row["source_path"])
        if p.stat().st_size != row["size"]: raise ValueError("Source size changed")
        with p.open("rb") as f: data = f.read(row["size"] + 1)
        observed = dict(size=len(data), sha256=hashlib.sha256(data).hexdigest(),
            git_blob_sha1=hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest())
        if any(observed[k] != row[k] for k in observed):
            raise ValueError("Frozen KI input changed before transfer")
        sys.stdout.buffer.write(data)
elif op in ("receipt_absent", "receipt"):
    p = checked(request["path"], writing=True)
    receipt_root = ROOT / "publication-receipts"
    if not p.is_relative_to(receipt_root) or p.suffix != ".json":
        raise ValueError("Receipt must be JSON under publication-receipts")
    if p.exists(): raise ValueError("Refusing to overwrite receipt")
    if op == "receipt":
        p.parent.mkdir(parents=True, exist_ok=True)
        # Recheck parent resolution after creation; exclusive creation is immutable.
        checked(str(p), writing=True)
        with p.open("x") as f:
            json.dump(request["receipt"], f, indent=2, allow_nan=False); f.write("\n")
        sys.stdout.write(json.dumps({"receipt_sha256": hashlib.sha256(p.read_bytes()).hexdigest()}))
    else:
        sys.stdout.write("{}")
else:
    raise ValueError("Unknown remote operation")
'''


def ki_call(request, expected_bytes=None):
    payload = json.dumps(request, allow_nan=False).encode()
    if len(payload) > MAX_INVENTORY_BYTES:
        raise ValueError("SSH request exceeds fixed memory budget")
    command = ["ssh", "-T", "-o", "BatchMode=yes", KI_HOST, "python3 -B -c " + shlex.quote(REMOTE)]
    result = subprocess.run(command, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError("KI operation failed: " + result.stderr.decode(errors="replace")[-3000:])
    limit = MAX_INVENTORY_BYTES if expected_bytes is None else expected_bytes
    if len(result.stdout) > limit or (expected_bytes is not None and len(result.stdout) != expected_bytes):
        raise ValueError("Unexpected SSH response length")
    return result.stdout


def call_hub(operation, *args, max_retries=5, **kwargs):
    """Reuse existing StreetShots policy: retry only explicit HTTP429 responses."""
    for attempt in range(max_retries + 1):
        try:
            return operation(*args, **kwargs)
        except Exception as error:
            response = getattr(error, "response", None)
            if response is None or getattr(response, "status_code", None) != 429 or attempt >= max_retries:
                raise
            headers = {str(k).lower(): v for k, v in response.headers.items()}
            advertised = []
            if headers.get("retry-after") is not None:
                try:
                    delay = float(headers["retry-after"])
                except (ValueError, TypeError):
                    try:
                        delay = parsedate_to_datetime(headers["retry-after"]).timestamp() - time.time()
                    except (ValueError, TypeError, OverflowError):
                        delay = None
                if delay is not None and math.isfinite(delay):
                    advertised.append(max(0, delay))
            from huggingface_hub.utils import parse_ratelimit_headers
            try:
                rate = parse_ratelimit_headers(headers)
                if rate is not None:
                    advertised.append(max(0, rate.reset_in_seconds))
            except (ValueError, TypeError, KeyError):
                pass
            remaining = max(1, math.ceil(max(advertised))) if advertised else min(30 * 2**attempt, 300)
            print(json.dumps({"stage": "hf_rate_limit_wait", "retry": attempt + 1, "seconds": remaining}), flush=True)
            while remaining > 0:
                interval = min(30, remaining)
                time.sleep(interval)
                remaining -= interval
                print(json.dumps({"stage": "hf_rate_limit_wait_progress", "remaining": remaining}), flush=True)


def paths_info(api, kind, rows, revision):
    found = {}
    for offset in range(0, len(rows), MAX_BATCH_FILES):
        entries = call_hub(api.get_paths_info, REPO,
            [row["path_in_repo"] for row in rows[offset:offset + MAX_BATCH_FILES]],
            repo_type=kind, revision=revision)
        found.update({entry.path: entry for entry in entries})
    return found


def verify_remote(api, kind, rows, revision):
    found = paths_info(api, kind, rows, revision)
    if set(found) != {row["path_in_repo"] for row in rows} or any(
        not remote_matches(found[row["path_in_repo"]], row) for row in rows
    ):
        raise ValueError("Post-commit remote content verification failed")


def source_sha():
    value = globals().get("_PUBLISHER_BYTES_SHA256")
    if value is None:
        value = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return require_digest(value, 64)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-ki", required=True)
    parser.add_argument("--inventory-sha256", required=True)
    parser.add_argument("--receipt-ki", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--publish", action="store_true", help="Otherwise perform read-only preflight")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise RuntimeError("Execute on the Mac; KI stores source bytes only and receives no HF credentials")
    safe_path(args.inventory_ki, absolute=True)
    safe_path(args.receipt_ki, absolute=True)
    if not args.receipt_ki.startswith(KI_ROOT + "/publication-receipts/") or not args.receipt_ki.endswith(".json"):
        raise ValueError("Receipt must be JSON under this task's publication-receipts directory")
    require_digest(args.inventory_sha256, 64)
    publisher_sha = source_sha()
    inventory_bytes = ki_call({"operation": "inventory", "path": args.inventory_ki})
    if hashlib.sha256(inventory_bytes).hexdigest() != args.inventory_sha256:
        raise ValueError("Frozen inventory hash mismatch")
    inventory = json.loads(inventory_bytes)
    rows = validate_inventory(inventory)
    # Validate every source, including files already present on the Hub.
    for batch in batches(rows):
        response = json.loads(ki_call({"operation": "audit", "files": batch}))
        if response.get("verified") != len(batch):
            raise ValueError("KI source audit is incomplete")
    # Use documented HTTP upload and in-memory IO; Xet may create a disk cache.
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    sys.dont_write_bytecode = True
    import huggingface_hub
    from huggingface_hub import HfApi, CommitOperationAdd, constants
    if not constants.HF_HUB_DISABLE_XET:
        raise RuntimeError("HF was imported before disabling Xet; start a fresh Python process")
    api = HfApi()  # Existing local login only; never serialize this client or token.
    kind = inventory["repo_type"]
    info = call_hub(api.repo_info, REPO, repo_type=kind)
    if not info.private:
        raise ValueError("StreetShots must remain private")
    initial_revision = revision = require_digest(info.sha, 40)
    if inventory.get("expected_parent_revision") not in (None, revision):
        raise ValueError("Repository head differs from frozen expected parent")
    existing = paths_info(api, kind, rows, revision)
    changed = []
    for row in rows:
        entry = existing.get(row["path_in_repo"])
        if entry is not None:
            if not remote_matches(entry, row):
                raise ValueError("Refusing to modify immutable existing path: " + row["path_in_repo"])
        else:
            changed.append(row)
    plan = {"stage": "preflight", "publish": args.publish, "repo_type": kind, "repository": REPO,
            "private": True, "parent_revision": revision, "files": len(rows),
            "new_files": len(changed), "new_bytes": sum(row["size"] for row in changed),
            "inventory_sha256": args.inventory_sha256, "publisher_sha256": publisher_sha}
    print(json.dumps(plan), flush=True)
    if not args.publish:
        return
    receipt_path = PurePosixPath(args.receipt_ki)
    batch_rows = list(batches(changed))
    receipt_paths = [args.receipt_ki] + [
        str(receipt_path.with_name(receipt_path.stem + f".batch-{number:03d}.json"))
        for number in range(1, len(batch_rows) + 1)]
    for path in receipt_paths:
        ki_call({"operation": "receipt_absent", "path": path})
    commits = []
    for number, batch in enumerate(batch_rows, 1):
        data = ki_call({"operation": "fetch", "files": batch}, expected_bytes=sum(row["size"] for row in batch))
        operations, offset = [], 0
        for row in batch:
            content = data[offset:offset + row["size"]]
            verify_payload(row, content)
            operations.append(CommitOperationAdd(path_in_repo=row["path_in_repo"], path_or_fileobj=io.BytesIO(content)))
            offset += row["size"]
        del data
        current = call_hub(api.repo_info, REPO, repo_type=kind)
        if not current.private or current.sha != revision:
            raise ValueError("Repository privacy or head changed during publication")
        commit = call_hub(api.create_commit, REPO, repo_type=kind, parent_commit=revision,
            num_threads=4, operations=operations,
            commit_message=args.message + f" ({number}/{len(batch_rows)})")
        del operations
        revision = require_digest(commit.oid, 40)
        verify_remote(api, kind, batch, revision)
        record = {"schema": "streetshots-ki-publish-batch-receipt-v1", "repository": REPO,
            "repo_type": kind, "private": True, "revision": revision, "batch": number, "postverification": True,
            "inventory_sha256": args.inventory_sha256, "publisher_sha256": publisher_sha,
            "files": [{"path": row["path_in_repo"], **{key: row[key] for key in ("size", "sha256", "git_blob_sha1")}}
                      for row in batch]}
        ki_call({"operation": "receipt", "path": receipt_paths[number], "receipt": record})
        commits.append({"batch": number, "revision": revision, "verified_files": len(batch)})
        print(json.dumps({"stage": "batch_verified", **commits[-1]}), flush=True)
    verify_remote(api, kind, rows, revision)
    if not call_hub(api.repo_info, REPO, repo_type=kind, revision=revision).private:
        raise ValueError("Repository is no longer private")
    manifest_row = next(row for row in rows if row["path_in_repo"] == inventory["manifest_path_in_repo"])
    receipt = {**plan, "schema": "streetshots-ki-publish-receipt-v1", "stage": "complete",
        "prefix": PREFIXES[kind], "postverification": True,
        "manifest": {"path": manifest_row["path_in_repo"], "sha256": manifest_row["sha256"]},
        "initial_revision": initial_revision, "revision": revision, "commits": commits,
        "huggingface_hub": huggingface_hub.__version__, "transport": "HTTP with BytesIO; HF_HUB_DISABLE_XET=1", "verified": "Hub LFS SHA-256 or Git blob SHA-1 plus byte size",
        "paths": {row["path_in_repo"]: {key: row[key] for key in ("size", "sha256", "git_blob_sha1")} for row in rows}}
    result = json.loads(ki_call({"operation": "receipt", "path": args.receipt_ki, "receipt": receipt}))
    print(json.dumps({"stage": "complete", "revision": revision, "repo_type": kind,
        "receipt_ki": args.receipt_ki, **result}), flush=True)


if __name__ == "__main__":
    main()
