#!/usr/bin/env python3
"""Replay raw-luma manifests through a frozen native production lane pipeline.

Uses macOS Swift/AVFoundation. No camera, device, model inference, GPS or invented
calibration is used. Each fresh output directory preserves exact source snapshots,
input hashes, NDJSON geometry/presentation output, and a compact timing summary.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    "LaneDetection.swift", "RoadBoundaryDetector.swift", "VisualRoadCalibration.swift",
    "RoadBoundaryTemporalTracker.swift", "RoadBoundaryPresentationGate.swift",
    "RoadBoundaryMotionHint.swift", "RoadPathEvidence.swift", "TrafficSignApplicability.swift",
    "RoadPathSession.swift",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_manifest(path, variant):
    original = json.loads(path.read_text())
    if original.get("schemaVersion") != 1 or not original.get("frames"):
        raise ValueError("Expected schemaVersion 1 and a nonempty frames array")
    frames, seen, closed = [], set(), set()
    sequence, previous = None, -math.inf
    for frame in original["frames"]:
        fid = frame["id"]
        seq = frame.get("sequenceId", frame.get("clipId"))
        if not isinstance(fid, str) or not fid or fid in seen or not isinstance(seq, str) or not seq:
            raise ValueError(f"Missing/duplicate frame ID or missing sequenceId: {fid!r}")
        seen.add(fid)
        width, height = frame["width"], frame["height"]
        if type(width) is not int or type(height) is not int or not (64 <= width <= 384 and 64 <= height <= 216):
            raise ValueError(f"Frame outside production analysis dimensions (64..384 x 64..216): {fid}")
        pts = frame.get("time", frame.get("actualVideoSeconds"))
        if isinstance(pts, bool) or not isinstance(pts, (int, float)) or not math.isfinite(pts):
            raise ValueError(f"Missing finite actual PTS: {fid}")
        if sequence != seq:
            if seq in closed:
                raise ValueError(f"Sequence frames must be contiguous: {seq}")
            if sequence is not None:
                closed.add(sequence)
            sequence, previous = seq, -math.inf
        if pts <= previous:
            raise ValueError(f"Actual PTS must strictly increase within a sequence: {fid}")
        previous = pts
        if frame.get("variant", "raw") not in (None, "raw", "luma"):
            raise ValueError(f"Input must be unfiltered luma; production filter runs inside the session: {fid}")
        gray = Path(frame["grayPath"])
        gray = (path.parent / gray).resolve() if not gray.is_absolute() else gray.resolve()
        if gray.stat().st_size != width * height:
            raise ValueError(f"Luma byte count differs from width*height: {fid}")
        actual_hash = digest(gray)
        for key in ("graySha256", "rawSha256", "sha256"):
            if frame.get(key) is not None and frame[key] != actual_hash:
                raise ValueError(f"{key} does not match supplied bytes: {fid}")
        decoded_width = frame.get("decodedWidth", width)
        decoded_height = frame.get("decodedHeight", height)
        if any(type(x) is not int or x < 1 for x in (decoded_width, decoded_height)):
            raise ValueError(f"Invalid decoded dimensions: {fid}")
        if abs(decoded_width / decoded_height - width / height) > 0.015:
            raise ValueError(f"Analysis/decoded aspect ratios differ: {fid}")
        frames.append(dict(id=fid, sequenceId=seq, grayPath=str(gray), graySha256=actual_hash,
                           width=width, height=height, decodedWidth=decoded_width, decodedHeight=decoded_height,
                           time=pts, source=frame.get("source"), sourceFrameId=frame.get("sourceFrameId")))
    return dict(schemaVersion=1, variant=variant, frames=frames)


def summarize(rows):
    def quantile(field):
        values = sorted(row[field] for row in rows)
        return dict(p50=values[len(values) // 2], p95=values[min(len(values) - 1, int(len(values) * .95))],
                    maximum=values[-1])
    return dict(frames=len(rows), rawBoundaries=sum(len(r["rawBoundaries"]) for r in rows),
                visibleBoundaries=sum(len(r["confirmedBoundaries"]) for r in rows),
                framesWithRawBoundaries=sum(bool(r["rawBoundaries"]) for r in rows),
                framesWithVisibleBoundaries=sum(bool(r["confirmedBoundaries"]) for r in rows),
                geometryBudgetExceeded=sum(r["geometryBudgetExceeded"] for r in rows),
                deadlineExceeded=sum(r["deadlineExceeded"] for r in rows),
                provenance=dict(Counter(b["provenance"] for r in rows for b in r["rawBoundaries"])),
                preparationMs=quantile("preparationMs"), componentMs=quantile("componentMs"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory; existing results are never overwritten")
    parser.add_argument("--source-dir", type=Path, default=ROOT / "iphone/SpeedConsumerApp",
                        help="Production sources or an archived/experimental directory containing all nine Swift files")
    parser.add_argument("--variant", default="production", help="Output label; does not alter production preprocessing")
    args = parser.parse_args()
    try:
        manifest_path = args.manifest.resolve(strict=True)
        normalized = normalized_manifest(manifest_path, args.variant)
        source_paths = [(args.source_dir / name).resolve(strict=True) for name in SOURCES]
        if args.output_dir.exists():
            raise ValueError("Output directory already exists; choose a new name")
        if not shutil.which("swiftc"):
            raise ValueError("swiftc is required on PATH")
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    work = args.output_dir.resolve()
    work.mkdir(parents=True, exist_ok=False)
    sources = work / "sources"
    sources.mkdir()
    for source in source_paths:
        shutil.copy2(source, sources / source.name)
    runner = Path(__file__).with_name("RecordedPipelineReplay.swift")
    shutil.copy2(runner, sources / runner.name)
    shutil.copy2(Path(__file__), sources / Path(__file__).name)
    hashes = {p.name: digest(p) for p in sorted(sources.iterdir())}
    input_file = work / "input.normalized.json"
    input_file.write_text(json.dumps(normalized, indent=2, allow_nan=False) + "\n")
    metadata = dict(schemaVersion=1, variant=args.variant, manifest=str(manifest_path),
                    manifestSha256=digest(manifest_path), normalizedManifestSha256=digest(input_file),
                    sourceHashes=hashes, frameCount=len(normalized["frames"]),
                    swiftVersion=subprocess.check_output(["swiftc", "--version"], text=True).strip(),
                    qualification="Offline encoded-pixel engineering replay, not live camera equivalence or device performance",
                    gpsSupplied=False, metricCalibrationSupplied=False, visualCalibrationSupplied=False)
    (work / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    binary = work / "pipeline-replay"
    compile_command = ["swiftc", "-O", "-module-cache-path", str(work / "swift-cache"),
                       *(str(sources / name) for name in SOURCES), str(sources / runner.name), "-o", str(binary)]
    with (work / "compile.log").open("w") as log:
        subprocess.run(compile_command, stdout=log, stderr=subprocess.STDOUT, check=True)
    partial = work / "frames.ndjson.part"
    with (work / "run.log").open("w") as log:
        subprocess.run([str(binary), str(input_file), str(partial)], stdout=log, stderr=subprocess.STDOUT, check=True)
    frames_file = work / "frames.ndjson"
    partial.rename(frames_file)
    rows = [json.loads(line) for line in frames_file.read_text().splitlines()]
    if len(rows) != len(normalized["frames"]):
        raise RuntimeError("Incomplete output: frame count differs from manifest")
    groups = defaultdict(list)
    for row in rows:
        groups[row["sequenceId"]].append(row)
    report = dict(schemaVersion=1, variant=args.variant, total=summarize(rows),
                  sequences={key: summarize(value) for key, value in groups.items()},
                  framesSha256=digest(frames_file), timingScope=rows[0]["timingScope"],
                  executionHost=rows[0]["executionHost"])
    (work / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(outputDir=str(work), **report["total"]), indent=2))


if __name__ == "__main__":
    main()
