#!/usr/bin/env python3
"""Prime a hash-pinned, clip-bounded encoded-video corpus outside the repository.

Requires OpenCV, NumPy and ffprobe. Times are original encoded video PTS seconds,
never UTC. Gray uses the existing BGR2GRAY/centre-nearest replay convention, not
sensor Y. No annotations or independence claims are inferred from the footage.
"""
import argparse
from bisect import bisect_left
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[2]
ID = re.compile(r"^[A-Za-z0-9_-]+$")


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return Fraction(str(value))


def validate(config, base):
    """Resolve inputs and reject leakage/overlap, including aliases of identical bytes."""
    if not isinstance(config.get("sources"), dict) or not config["sources"] or not config.get("clips"):
        raise ValueError("Nonempty sources and clips are required")
    sources, clips, seen, partitions = {}, [], set(), {}
    for sid, source in config["sources"].items():
        if not ID.fullmatch(sid) or not isinstance(source.get("driveGroup"), str) or not source["driveGroup"]:
            raise ValueError("Source IDs must be safe identifiers and driveGroup must be explicit")
        if not re.fullmatch(r"[a-f0-9]{64}", source.get("sha256", "")):
            raise ValueError(f"Missing SHA-256: {sid}")
        path = Path(source["path"])
        path = (base / path).resolve(strict=True) if not path.is_absolute() else path.resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"Not a source file: {sid}")
        sources[sid] = dict(source, path=str(path))
    intervals = {}
    for clip in config["clips"]:
        cid, sid = clip["id"], clip["source"]
        if not isinstance(cid, str) or not ID.fullmatch(cid) or cid in seen:
            raise ValueError(f"Missing/unsafe/duplicate clip ID: {cid}")
        seen.add(cid)
        if sid not in sources:
            raise ValueError(f"Unknown source: {sid}")
        source = sources[sid]
        start, end = number(clip["start"], "start"), number(clip["end"], "end")
        if start < 0 or end <= start:
            raise ValueError(f"Empty/negative clip: {cid}")
        split = clip.get("split", source.get("split", "development"))
        if not isinstance(split, str) or not split:
            raise ValueError("A nonempty split is required")
        if source.get("split", split) != split:
            raise ValueError(f"Cross-split source leakage: {sid}")
        for kind, identity in (("source", sid), ("content", source["sha256"]), ("driveGroup", source["driveGroup"])):
            key = kind, identity
            if key in partitions and partitions[key] != split:
                raise ValueError(f"Cross-split {kind} leakage: {identity}")
            partitions[key] = split
        for lo, hi in intervals.setdefault(source["sha256"], []):
            if max(lo, start) < min(hi, end):
                raise ValueError(f"Overlapping clips, including content aliases: {cid}")
        intervals[source["sha256"]].append((start, end))
        tags = clip.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError("Clip tags must be strings")
        clips.append(dict(clip, split=split, tags=tags))
    return sources, clips


def verify_sources(sources):
    for sid, source in sources.items():
        if sha(source["path"]) != source["sha256"]:
            raise ValueError(f"Source content hash mismatch: {sid}")
        source["bytes"] = Path(source["path"]).stat().st_size


def presentation_table(raw_rows, stream, mode):
    """Validate original timing; packet decode order may differ from presentation order."""
    if not raw_rows:
        raise ValueError("No video timing records")
    rows = []
    for raw in raw_rows:
        values = {}
        for field in ("pts", "duration"):
            value = raw.get(field, raw.get("pkt_duration") if field == "duration" else None)
            if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"-?\d+", str(value)):
                raise ValueError(f"Missing/invalid encoded {field}; invented timestamps are not accepted")
            values[field] = int(value)
        if values["duration"] <= 0:
            raise ValueError("Encoded duration must be positive")
        if mode == "decoded" and (raw.get("width"), raw.get("height")) != (stream["width"], stream["height"]):
            raise ValueError("Changing video dimensions are not supported")
        rows.append(dict(values, width=stream["width"], height=stream["height"]))
    if mode == "packets":
        rows.sort(key=lambda row: row["pts"])
    if any(b["pts"] <= a["pts"] for a, b in zip(rows, rows[1:])):
        raise ValueError("Encoded presentation PTS must be unique and strictly increase")
    return rows


def probe(path, executable, pts_mode="packets"):
    metadata = subprocess.run([executable, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                              check=True, capture_output=True, text=True)
    raw = json.loads(metadata.stdout)
    videos = [stream for stream in raw["streams"] if stream["codec_type"] == "video"]
    if len(videos) != 1:
        raise ValueError("Exactly one video stream is supported")
    stream = videos[0]
    if stream.get("sample_aspect_ratio", "1:1") not in ("1:1", "0:1", "N/A"):
        raise ValueError("Non-square pixels require a separately validated transform")
    for side in stream.get("side_data_list", []):
        if "displaymatrix" not in side:
            continue
        matrix = [int(value) for line in side["displaymatrix"].strip().splitlines()
                  for value in line.split(":", 1)[1].split()]
        if len(matrix) != 9:
            raise ValueError("Unrecognized video display matrix")
        a, b, u, c, d, v, x, y, scale = matrix
        w, h = stream["width"], stream["height"]
        canonical_translation = (-min(0, a * w, c * h, a * w + c * h),
                                 -min(0, b * w, d * h, b * w + d * h))
        if (any(value not in (-65536, 0, 65536) for value in (a, b, c, d))
                or a * d - b * c != 65536 ** 2 or a * a + b * b != 65536 ** 2
                or any((u, v)) or (x, y) not in ((0, 0), canonical_translation) or scale != 1073741824):
            raise ValueError("Mirrored/non-quarter-turn display matrix requires explicit support")
    time_base = Fraction(stream["time_base"])
    if time_base <= 0:
        raise ValueError("Invalid encoded time base")
    if pts_mode not in ("packets", "decoded"):
        raise ValueError("pts-mode must be packets or decoded")
    timing_options = (["-show_packets", "-show_entries", "packet=pts,duration"] if pts_mode == "packets" else
                      ["-show_frames", "-show_entries", "frame=pts,duration,pkt_duration,width,height"])
    result = subprocess.run([executable, "-v", "error", "-select_streams", "v:0", *timing_options,
                             "-of", "json", str(path)],
                            check=True, capture_output=True, text=True)
    if metadata.stderr.strip() or result.stderr.strip():
        raise ValueError("ffprobe reported a decode error: " + metadata.stderr + result.stderr)
    rows = presentation_table(json.loads(result.stdout).get("packets" if pts_mode == "packets" else "frames", []), stream, pts_mode)
    duration = rows[-1]["duration"]
    return raw, rows, time_base, (int(rows[-1]["pts"]) + duration) * time_base


def select_frames(rows, time_base, coverage_end, clip, fps, diagnostics=None):
    times = [int(row["pts"]) * time_base for row in rows]
    start, end = Fraction(str(clip["start"])), Fraction(str(clip["end"]))
    if start < times[0] or end > coverage_end:
        raise ValueError(f"Clip {clip['id']} exceeds actual encoded coverage")
    selected, target, previous, target_index, skipped = [], start, -1, 0, []
    while target < end:
        index = bisect_left(times, target)
        if index >= len(times) or times[index] >= end or index <= previous:
            skipped.append(float(target))
        else:
            selected.append((index, target))
            previous = index
        target_index += 1
        target = start + target_index / fps
    if not selected:
        raise ValueError(f"No encoded exposure in clip {clip['id']}")
    if diagnostics is not None:
        diagnostics.update(targetCount=target_index, extractedCount=len(selected),
                           skippedTargetTimes=skipped, skippedTargets=len(skipped),
                           maximumTargetDelaySeconds=max(float(times[index] - target) for index, target in selected))
    return selected


def dimensions(width, height, max_width=384, max_height=216):
    scale = min(max_width / width, max_height / height, 1.0)
    # Int truncation matches current RoadPathCameraCapture.frame.
    return max(1, int(width * scale)), max(1, int(height * scale))


def center_gray(bgr):
    import cv2
    import numpy as np
    h, w = bgr.shape[:2]
    width, height = dimensions(w, h)
    if min(width, height) < 64:
        raise ValueError("Upright image cannot fit native replay's minimum 64-pixel dimensions")
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    xs = np.minimum(w - 1, ((np.arange(width) + .5) * w / width).astype(int))
    ys = np.minimum(h - 1, ((np.arange(height) + .5) * h / height).astype(int))
    return gray[np.ix_(ys, xs)]


def decode_clock_offset(samples, time_base):
    """Require several initial presentation timestamps to agree on one clock.

    OpenCV can report a negative sentinel for its first decoded picture. That
    picture must not define an offset applied to every later timestamp.
    """
    tolerance = float(time_base) / 4
    usable = [row for row in samples if not row.get("ignoredInitialSentinel")]
    if len(usable) < 3:
        raise ValueError("At least three valid initial timestamps are required to verify the decoder clock")
    if any(not math.isfinite(row["decoderTime"]) for row in usable):
        raise ValueError("Non-finite initial decoder timestamp")
    if any(b["decoderTime"] <= a["decoderTime"] for a, b in zip(usable, usable[1:])):
        raise ValueError("Initial decoder timestamps must strictly increase")
    deltas = [row["encodedTime"] - row["decoderTime"] for row in usable]
    offset = statistics.median(deltas)
    if any(abs(delta - offset) > tolerance for delta in deltas):
        raise ValueError("Initial decoder timestamps do not match one encoded presentation clock")
    return 0.0 if abs(offset) <= tolerance else offset


def calibrate_decode_clock(cap, rows, time_base):
    import cv2
    samples = []
    for index, row in enumerate(rows[:6]):
        ok, _ = cap.read()
        if not ok:
            raise ValueError("Cannot decode initial exposures for timestamp verification")
        encoded = float(int(row["pts"]) * time_base)
        reported = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        samples.append(dict(sourcePresentationIndex=index, encodedTime=encoded, decoderTime=reported,
                            ignoredInitialSentinel=index == 0 and reported < 0 <= encoded))
    return decode_clock_offset(samples, time_base), samples


def extract(source, clip, rows, time_base, selected, out, rgb, sample_every):
    import cv2
    cap = cv2.VideoCapture(source["path"], cv2.CAP_FFMPEG)
    try:
        if not cap.isOpened() or not cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1):
            raise ValueError("Cannot open video with explicit auto-orientation")
        rotation = cap.get(cv2.CAP_PROP_ORIENTATION_META)
        if not math.isfinite(rotation) or rotation % 90:
            raise ValueError("Only quarter-turn video orientation is supported")
        rotation = int(rotation) % 360
        matrices = {0: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    90: [[0, -1, 1], [1, 0, 0], [0, 0, 1]],
                    180: [[-1, 0, 1], [0, -1, 1], [0, 0, 1]],
                    270: [[0, 1, 0], [-1, 0, 1], [0, 0, 1]]}
        clock_offset, calibration = calibrate_decode_clock(cap, rows, time_base)
        first_time = float(int(rows[0]["pts"]) * time_base)
        # VFR seeks can overshoot the requested frame. Decode a short pre-roll,
        # then require the selected exposure to match within a quarter PTS tick.
        relative_seek = max(0.0, float(Fraction(str(clip["start"]))) - first_time - 1.0)
        if not cap.set(cv2.CAP_PROP_POS_MSEC, relative_seek * 1000):
            raise ValueError(f"Seek failed: {clip['id']}")
        tolerance = float(time_base) / 4
        previous = -math.inf
        frames, samples = [], []
        for ordinal, (source_index, target) in enumerate(selected):
            pts_value = int(rows[source_index]["pts"])
            actual = float(pts_value * time_base)
            while True:
                ok, bgr = cap.read()
                if not ok:
                    raise ValueError(f"Unexpected EOF/truncated decode: {clip['id']}")
                decoded_time = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000 + clock_offset
                if not math.isfinite(decoded_time) or decoded_time <= previous:
                    raise ValueError("Decoder returned duplicate/out-of-order timestamps")
                previous = decoded_time
                if decoded_time >= actual - tolerance:
                    break
            if abs(decoded_time - actual) > tolerance:
                raise ValueError(f"Seek/decode PTS mismatch: expected {actual}, got {decoded_time}")
            h, w = bgr.shape[:2]
            encoded_w, encoded_h = rows[source_index]["width"], rows[source_index]["height"]
            expected_size = (encoded_h, encoded_w) if rotation in (90, 270) else (encoded_w, encoded_h)
            if (w, h) != expected_size:
                raise ValueError("Auto-oriented dimensions disagree with encoded metadata")
            gray = center_gray(bgr)
            height, width = gray.shape
            fid = f"{clip['id']}-{ordinal:06d}"
            gray_path = out / "frames" / (fid + ".gray")
            gray_path.write_bytes(gray.tobytes())
            transform = dict(encodedWidth=encoded_w, encodedHeight=encoded_h,
                             uprightWidth=w, uprightHeight=h, rotationClockwiseDegrees=rotation,
                             encodedToUprightNormalized=matrices[rotation], crop=None,
                             analysisWidth=width, analysisHeight=height,
                             analysisPixelCenterToUprightIndex="floor((index+0.5)*uprightSize/analysisSize)",
                             analysisToUprightPixelCenter=[[w / width, 0, w / (2 * width) - .5],
                                                          [0, h / height, h / (2 * height) - .5], [0, 0, 1]])
            row = dict(id=fid, sequenceId=clip["id"], clipId=clip["id"], sourceId=clip["source"],
                       source=source["path"], sourceVideoSha256=source["sha256"], sourcePresentationIndex=source_index,
                       sourceFrameId=f"{source['sha256']}:{pts_value}:{time_base}", driveGroup=source["driveGroup"],
                       split=clip["split"], sceneTags=clip["tags"], time=actual, actualPTS=actual,
                       actualVideoSeconds=actual, ptsValue=pts_value, timeBase=str(time_base),
                       targetTime=float(target), requestedTime=float(target), decoderReportedTime=decoded_time,
                       decoderRawTime=decoded_time - clock_offset,
                       decoderToEncodedOffset=clock_offset, decodeTimestampToleranceSeconds=tolerance,
                       grayPath=str(gray_path), graySha256=sha(gray_path), width=width, height=height,
                       decodedWidth=w, decodedHeight=h, transform=transform,
                       orientationKey=f"encoded-upright:clockwise-{rotation}", variant="raw",
                       supportStartSeconds=clip["start"], supportEndSeconds=clip["end"])
            if rgb:
                rgb_w, rgb_h = dimensions(w, h, 960, 1_000_000)
                image = cv2.resize(bgr, (rgb_w, rgb_h), interpolation=cv2.INTER_AREA)
                rgb_path = out / "rgb" / (fid + ".png")
                if not cv2.imwrite(str(rgb_path), image):
                    raise ValueError("RGB image export failed")
                row.update(rgbPath=str(rgb_path), rgbSha256=sha(rgb_path), rgbWidth=rgb_w, rgbHeight=rgb_h)
                transform["rgbSampling"] = "OpenCV INTER_AREA; aspect-preserving integer-rounded fit, no crop"
                transform["rgbToUprightPixelCenter"] = [[w / rgb_w, 0, w / (2 * rgb_w) - .5],
                                                         [0, h / rgb_h, h / (2 * rgb_h) - .5], [0, 0, 1]]
            frames.append(row)
            if ordinal % sample_every == 0 or ordinal == len(selected) - 1:
                samples.append(dict(row))
        return frames, samples, dict(rotationClockwiseDegrees=rotation, decoderToEncodedOffset=clock_offset,
                                     initialTimestampSamples=calibration,
                                     timestampToleranceSeconds=tolerance, seekPreRollSeconds=1.0)
    finally:
        cap.release()


def prime(config_path, output_dir, fps=10, rgb=True, ffprobe="ffprobe", sample_every=30, pts_mode="packets"):
    config_path, out = Path(config_path).resolve(strict=True), Path(output_dir).resolve()
    rate = number(fps, "fps")
    if not 0 < rate <= 60 or type(sample_every) is not int or sample_every < 1:
        raise ValueError("fps must be >0 and <=60; sample-every must be positive")
    if out == ROOT or ROOT in out.parents:
        raise ValueError("Corpus output must be outside the repository")
    if out.exists():
        raise ValueError("Output directory exists; never overwrite evidence")
    config = json.loads(config_path.read_text())
    sources, clips = validate(config, config_path.parent)
    verify_sources(sources)  # Must happen before ffprobe or any pixel decoder opens sources.
    import cv2
    cv2.setNumThreads(1)
    out.mkdir(parents=True, exist_ok=False)
    for name in ("frames", "rgb", "rawmetadata"):
        (out / name).mkdir()
    write_json(out / "config.json", config)
    try:
        metadata, frame_tables, frames, samples = {}, {}, [], []
        for sid, source in sources.items():
            raw, rows, time_base, coverage = probe(source["path"], ffprobe, pts_mode)
            write_json(out / "rawmetadata" / (sid + ".ffprobe.json"), raw)
            write_json(out / "rawmetadata" / (sid + ".pts.json"), rows)
            frame_tables[sid] = rows, time_base, coverage
            metadata[sid] = dict(source, encodedTimeBase=str(time_base), encodedCoverageEnd=float(coverage),
                                ptsTableKind="packet_presentation_order" if pts_mode == "packets" else "decoded_frame_presentation_order")
        for clip in clips:
            sid = clip["source"]
            rows, time_base, coverage = frame_tables[sid]
            sampling = {}
            selected = select_frames(rows, time_base, coverage, clip, rate, sampling)
            clip["sampling"] = sampling
            extracted, chosen, orientation = extract(sources[sid], clip, rows, time_base, selected, out, rgb, sample_every)
            for row in extracted + chosen:
                row["sourcePresentationIndexKind"] = metadata[sid]["ptsTableKind"]
            frames.extend(extracted); samples.extend(chosen)
            metadata[sid]["decodeMapping"] = orientation
            print(f"{clip['id']}: {len(extracted)} verified exposures", flush=True)
        verify_sources(sources)
        provenance = dict(schemaVersion=1, sources=metadata, clips=clips, requestedFPS=float(rate),
                          configSha256=sha(config_path), extractorSha256=sha(__file__), opencvVersion=cv2.__version__,
                          grayscale="OpenCV BGR2GRAY then center-nearest; encoded RGB conversion, not sensor Y",
                          timeDomain="original encoded video PTS seconds; no UTC or GNSS mapping inferred",
                          splitQualification="Only declared source/content/drive groups checked; unknown route identity is not independent geography",
                          annotationStatus="unlabelled input corpus; no predictions treated as truth", ptsMode=pts_mode,
                          decodeQualification="Selected exposures decoded and matched to original PTS; packet inventory is not a full-video decode integrity scan" if pts_mode == "packets" else
                          "ffprobe decoded-frame timing audit plus selected OpenCV exposures; not a live-camera equivalence claim")
        write_json(out / "provenance.json", provenance)
        write_json(out / "samples.json", samples)
        write_json(out / "corpus.json", dict(schemaVersion=1, sources=metadata, clips=clips, frames=frames))
        artifacts = {str(path.relative_to(out)): dict(sha256=sha(path), bytes=path.stat().st_size)
                     for path in sorted(out.rglob("*")) if path.is_file()}
        write_json(out / "artifacts.json", artifacts)
        # Success marker comes last; failed runs retain diagnostics, never a usable manifest.
        write_json(out / "manifest.json", dict(schemaVersion=1, frames=frames, provenanceSha256=sha(out / "provenance.json"),
                                               artifactsSha256=sha(out / "artifacts.json")))
        return dict(outputDir=str(out), frames=len(frames), clips=len(clips), sources=len(sources))
    except Exception as error:
        write_json(out / "failure.json", dict(status="incomplete", error=str(error)))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path, help="New directory outside the repository")
    parser.add_argument("--fps", type=float, default=10)
    parser.add_argument("--no-rgb", action="store_true", help="Omit every-frame RGB PNGs")
    parser.add_argument("--sample-every", type=int, default=30, help="Index every Nth frame for QA, plus each clip's last frame")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--pts-mode", choices=("packets", "decoded"), default="packets",
                        help="Fast original packet PTS inventory (default), or full decoded-frame audit")
    args = parser.parse_args()
    try:
        print(json.dumps(prime(args.config, args.output_dir, args.fps, not args.no_rgb, args.ffprobe, args.sample_every, args.pts_mode)))
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Corpus extraction failed: {error}\n")


if __name__ == "__main__":
    main()
