#!/usr/bin/env python3
"""Verify a pinned Hub backup before removing explicitly manifested local files.

Run with the authenticated Hugging Face CLI Python environment. No remote
mutation or token output. --delete-local is deliberately opt-in.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from huggingface_hub import HfApi, hf_hub_download


def digest(path, algorithm="sha256", prefix=b""):
    h = hashlib.new(algorithm)
    h.update(prefix)
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def local_matches(path, record):
    return (not path.is_symlink() and path.is_file()
            and path.stat().st_size == record["bytes"]
            and digest(path) == record["sha256"])


def allowed(path, roots):
    absolute = path.absolute()
    return (absolute == path.resolve()
            and any(root in absolute.parents for root in roots))


def verify(manifest_path, stage, report_path, roots, delete_local=False):
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    api = HfApi()
    info = api.repo_info(manifest["dataset"], repo_type="dataset")
    if not info.private:
        raise ValueError("Expected private evidence dataset")
    revision = info.sha
    remote_manifest = str(manifest_path.relative_to(stage))
    objects = manifest["objects"]
    paths = [remote_manifest] + [obj["relativePath"] for obj in objects]
    entries = {}
    for start in range(0, len(paths), 64):
        for entry in api.get_paths_info(manifest["dataset"], paths[start:start + 64],
                                       repo_type="dataset", revision=revision):
            entries[entry.path] = entry
    missing = [path for path in paths if path not in entries]
    if missing:
        return {"complete": False, "revision": revision, "missingObjects": len(missing)}
    downloaded = Path(hf_hub_download(manifest["dataset"], remote_manifest,
                                      repo_type="dataset", revision=revision))
    if downloaded.read_bytes() != raw:
        raise ValueError("Remote manifest differs from local manifest")
    prior = json.loads(report_path.read_text()) if report_path.exists() else {}
    prior_git = prior.get("gitBlobIDs", {}) if prior.get("manifestSHA256") == hashlib.sha256(raw).hexdigest() else {}
    git_blobs = {}
    for obj in objects:
        entry = entries[obj["relativePath"]]
        if entry.size != obj["bytes"]:
            raise ValueError(f"Remote size mismatch: {entry.path}")
        if entry.lfs:
            if entry.lfs.sha256 != obj["sha256"]:
                raise ValueError(f"Remote LFS hash mismatch: {entry.path}")
        else:
            local = stage / obj["relativePath"]
            if not local.exists() and prior.get("complete") and prior_git.get(entry.path) == entry.blob_id:
                git_blobs[entry.path] = entry.blob_id
                continue
            if not local_matches(local, obj):
                raise ValueError(f"Local staged object differs: {entry.path}")
            prefix = f"blob {obj['bytes']}\0".encode()
            if digest(local, "sha1", prefix) != entry.blob_id:
                raise ValueError(f"Remote Git blob mismatch: {entry.path}")
            git_blobs[entry.path] = entry.blob_id
    report = {"complete": True, "dataset": manifest["dataset"],
              "revision": revision, "manifestPath": remote_manifest,
              "manifestSHA256": hashlib.sha256(raw).hexdigest(),
              "verifiedObjects": len(objects), "verifiedBytes": manifest["uniqueUploadBytes"],
              "verifiedAtUnix": time.time(), "deleted": [], "retained": [],
              "gitBlobIDs": git_blobs,
              "alreadyAbsent": [], "stagedObjectsDeleted": []}
    # Persist proof before the first deletion. Keep reports/manifests for restore.
    def save():
        temporary = report_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n")
        temporary.replace(report_path)
    save()
    if delete_local:
        for record in manifest["records"]:
            path = Path(record["source"])
            if not allowed(path, roots):
                report["retained"].append({"source": str(path), "reason": "outside allowed roots or symlink"})
            elif not path.exists():
                report["alreadyAbsent"].append(str(path))
            else:
                # Recheck the file identity immediately before unlinking.
                before = path.stat()
                matches = local_matches(path, record)
                after = path.stat()
                stable = lambda stat: (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                if not matches or stable(after) != stable(before):
                    report["retained"].append({"source": str(path), "reason": "changed during verification"})
                else:
                    path.unlink()
                    report["deleted"].append({"source": str(path), "bytes": record["bytes"]})
            save()
        for obj in objects:
            path = stage / obj["relativePath"]
            if stage.resolve() not in path.resolve().parents or path.is_symlink():
                raise ValueError("Invalid staged object path")
            if path.exists():
                if not local_matches(path, obj):
                    raise ValueError("Staged object changed after remote verification")
                path.unlink()
                report["stagedObjectsDeleted"].append(obj["relativePath"])
                save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allowed-root", type=Path, action="append", default=[])
    parser.add_argument("--delete-local", action="store_true")
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    if args.delete_local and not args.allowed_root:
        parser.error("Deletion requires explicit allowed roots")
    while True:
        try:
            result = verify(args.manifest, args.stage, args.report,
                            [root.resolve() for root in args.allowed_root], args.delete_local)
        except Exception as error:
            # Never delete on failed verification; retry transient network errors.
            if not args.wait:
                raise
            print(json.dumps({"complete": False, "errorType": type(error).__name__}), flush=True)
            time.sleep(60)
            continue
        print(json.dumps({k: result[k] for k in ("complete", "revision", "missingObjects", "verifiedObjects") if k in result}), flush=True)
        if result["complete"] or not args.wait:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
