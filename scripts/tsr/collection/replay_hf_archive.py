#!/usr/bin/env python3
"""Restore pinned original videos, verify hashes, replay, and optionally upload.

The input archive plan lists only selected original records from backup manifests.
Private pixels, source evidence, upload plans and resumable acknowledgments remain
in OUTPUT, outside Git. One source is restored at a time. --release-video-copies
removes only this run's verified restored object after successful replay.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def run(command, log, env=None):
    with log.open("a") as stream:
        subprocess.run([str(x) for x in command], stdout=stream,
                       stderr=subprocess.STDOUT, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-pack", type=Path, required=True)
    parser.add_argument("--replay-binary", type=Path, required=True)
    parser.add_argument("--probe-binary", type=Path, required=True)
    parser.add_argument("--results-name", default="results.json",
                        help="Separate checkpoint filename for a disjoint archive partition")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--release-video-copies", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    plan = json.loads(args.plan.read_text())
    assert plan["dataset"] == "loffenauer/youspeed.de"
    assert re.fullmatch(r"[0-9a-f]{40}", plan["revision"])
    assert len({r["sha256"] for r in plan["records"]}) == len(plan["records"])
    env = dict(os.environ, SSL_CERT_FILE="/etc/ssl/cert.pem")
    env.setdefault("REQUESTS_CA_BUNDLE", "/etc/ssl/cert.pem")
    assert Path(args.results_name).name == args.results_name
    results_path = args.output / args.results_name
    results = json.loads(results_path.read_text()) if results_path.exists() else {}
    restore = args.output / "restore"
    for index, record in enumerate(plan["records"]):
        sha = record["sha256"]
        assert re.fullmatch(r"[0-9a-f]{64}", sha)
        remote = Path(record["remotePath"])
        assert not remote.is_absolute() and ".." not in remote.parts
        assert remote.parts[0] == "device-backups" and sha in remote.name
        previous = results.get(sha, {})
        if previous.get("state") in ("uploaded", "no_sightings", "replayed"):
            if previous["state"] != "replayed" or not args.upload:
                continue
        entry = dict(source_sha256=sha, remote_path=str(remote),
                     source=record["source"], recording_platform=record["recording_platform"])
        results[sha] = entry
        output = args.output / sha[:16]
        output.mkdir(exist_ok=True)
        video = restore / remote
        try:
            print(f"[{index + 1}/{len(plan['records'])}] {sha[:12]} {record['bytes'] / 1e6:.1f} MB", flush=True)
            report_path = output / "report.json"
            if not report_path.exists():
                incoming = 0 if video.exists() and video.stat().st_size == record["bytes"] else record["bytes"]
                if shutil.disk_usage(args.output).free < incoming + 4 * 1024**3:
                    raise RuntimeError("Insufficient free space for one video plus 4 GiB reserve")
                run(["hf", "download", plan["dataset"], remote, "--type", "dataset",
                     "--revision", plan["revision"], "--local-dir", restore, "--quiet"],
                    output / "download.log", env)
                assert video.stat().st_size == record["bytes"]
                assert digest(video) == sha, "Restored SHA-256 mismatch"
                write_json(output / "restore-verification.json", dict(dataset=plan["dataset"], revision=plan["revision"],
                    remote_path=str(remote), sha256=sha, bytes=record["bytes"], restored_sha256_verified=True))
                probe = subprocess.run([str(args.probe_binary), str(video)], capture_output=True, text=True)
                if probe.returncode:
                    (output / "probe-error.txt").write_text(probe.stderr)
                    raise RuntimeError("Native video probe failed; see probe-error.txt")
                metadata = json.loads(probe.stdout)
                write_json(output / "video-info.json", metadata)
                duration = float(metadata["duration_seconds"])
                name = Path(record["source"]).name
                match = re.match(r"dashcam-(\d{13})-", name)
                if match:
                    anchor = datetime.fromtimestamp(int(match[1]) / 1000, timezone.utc)
                    method = "android_filename_start_milliseconds"
                else:
                    anchor = datetime.fromtimestamp(record["mtimeNs"] / 1e9, timezone.utc) - timedelta(seconds=duration)
                    method = "backup_source_mtime_minus_duration"
                evidence = dict(dataset=plan["dataset"], revision=plan["revision"],
                                remote_path=str(remote), sha256=sha, bytes=record["bytes"],
                                original_source=record["source"], source_aliases=record["source_aliases"],
                                recording_platform=record["recording_platform"],
                                maximum_parallel_replays=plan.get("maximum_parallel_replays", 1),
                                estimated_start_utc=anchor.isoformat(), time_estimation_method=method,
                                interval_seconds=0.1, restored_sha256_verified=True)
                write_json(output / "source-evidence.json", evidence)
                # Preserve any interrupted trace before retrying; never append duplicate frames.
                if (output / "frames.ndjson").exists():
                    interrupted = output / ("interrupted-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
                    interrupted.mkdir()
                    for child in list(output.iterdir()):
                        if child.name == "frames.ndjson" or child.suffix == ".png":
                            child.rename(interrupted / child.name)
                entry["state"] = "replaying"
                write_json(results_path, results)
                run([args.replay_binary, video, args.model_pack, output, "0.1"], output / "replay.log")
                report = json.loads(report_path.read_text())
                report["source_evidence"] = evidence
                if evidence["maximum_parallel_replays"] > 1:
                    report["limitations"].append("Mac timing may include contention from two concurrent archive replay workers.")
                write_json(report_path, report)
            report = json.loads(report_path.read_text())
            evidence = report["source_evidence"]
            run([sys.executable, HERE / "summarize_replay.py", report_path], output / "summary.log")
            metrics = json.loads((output / "metrics.json").read_text())
            entry.update(metrics=metrics, source_evidence=evidence, state="replayed")
            write_json(results_path, results)
            if args.release_video_copies and video.exists():
                assert video.stat().st_size == record["bytes"] and digest(video) == sha
                video.unlink()
                entry["temporary_source_removed"] = True
            if not report["sightings"]:
                entry["state"] = "no_sightings"
            elif args.upload:
                upload_plan = output / "upload-plan.json"
                if not upload_plan.exists():
                    run([sys.executable, HERE / "upload_replay.py", "--report", report_path,
                         "--model-pack", args.model_pack, "--recorded-start-utc", evidence["estimated_start_utc"]],
                        output / "prepare.log", env)
                prepared = json.loads(upload_plan.read_text())
                entry["installation_id"] = prepared["installation_id"]
                entry["state"] = "uploading"
                write_json(results_path, results)
                run([sys.executable, HERE / "upload_replay.py", "--upload", upload_plan], output / "upload.log", env)
                acknowledgments = [json.loads(line) for line in (output / "upload-acknowledgments.ndjson").read_text().splitlines()]
                assert {a["index"] for a in acknowledgments} == set(range(len(prepared["requests"])))
                assert all(200 <= a["status"] < 300 for a in acknowledgments)
                entry.update(state="uploaded", acknowledged_requests=len(acknowledgments),
                             crop_count=prepared["crop_count"], observation_count=prepared["observation_count"])
            write_json(results_path, results)
            print(f"  {entry['state']}: {metrics['sightings']} sightings, {metrics['sequence_crops']} crops", flush=True)
        except Exception as error:
            entry.update(state="failed", error=str(error))
            write_json(results_path, results)
            print(f"  FAILED: {error}; details in {output}", flush=True)
    failures = [r for r in results.values() if r["state"] == "failed"]
    print(f"Finished {len(results)} recordings; {len(failures)} failures. Results: {results_path}", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
