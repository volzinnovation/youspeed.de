#!/usr/bin/env python3
"""Offline line-extractor comparison. No lane or sign-applicability decisions.

Accepts reviewed image corpora, an actual-PTS extracted-frame manifest, or a
video (ffprobe/ffmpeg required). All timings are host measurements, not mobile
qualification. ELSED is intentionally reported as not run by this probe.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
METHODS = ("canny_hough_p", "fast_line_detector", "edge_drawing_lines", "lsd")
SETTINGS = {
    "canny_hough_p": {"canny": [50, 150], "aperture": 3, "rho": 1,
                       "theta_degrees": 1, "threshold": 20,
                       "min_line_length": 12, "max_line_gap": 5},
    "fast_line_detector": {"length_threshold": 12, "distance_threshold": 1.41421356,
                           "canny_th1": 50, "canny_th2": 150,
                           "canny_aperture_size": 3, "do_merge": False},
    "edge_drawing_lines": {"GradientThresholdValue": 36, "AnchorThresholdValue": 8,
                           "ScanInterval": 1, "MinPathLength": 10,
                           "MinLineLength": 12, "NFAValidation": True,
                           "PFmode": False, "Sigma": 1.0,
                           "EdgeDetectionOperator": 1},
    "lsd": {"refine": "LSD_REFINE_STD", "scale": 0.8},
}


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def resolve(path, root):
    path = Path(path)
    return path if path.is_absolute() else root / path


def resize_dimensions(width, height, max_edge, max_height=None):
    if min(width, height, max_edge) <= 0:
        raise ValueError("Positive image dimensions and max edge required")
    scale = min(1.0, max_edge / max(width, height), (max_height / height) if max_height else 1.0)
    return max(1, round(width * scale)), max(1, round(height * scale))


def actual_pts(frame):
    """Never substitute requested time, frame number/fps, or UTC for actual PTS."""
    if frame.get("pts_value") is not None and frame.get("pts_timescale") is not None:
        scale = frame["pts_timescale"]
        if not isinstance(scale, (int, float)) or scale <= 0:
            raise ValueError("Invalid PTS timescale")
        value = frame["pts_value"] / scale
        if frame.get("pts_seconds") is not None and abs(value - frame["pts_seconds"]) > 1e-6:
            raise ValueError("PTS rational and seconds disagree")
    elif frame.get("pts_seconds") is not None:
        value = float(frame["pts_seconds"])
    else:
        raise ValueError("Actual presentation timestamp missing")
    if not math.isfinite(value):
        raise ValueError("Non-finite PTS")
    return value


def sample_pts(frames, interval, start=None, end=None, maximum=None):
    """Select first original frame at/after each cadence bin, preserving PTS."""
    if interval <= 0:
        raise ValueError("Positive sample interval required")
    selected, last, next_at = [], None, start
    for frame in frames:
        pts = actual_pts(frame)
        if last is not None and pts <= last:
            raise ValueError("Frame PTS must strictly increase; duplicates need explicit resolution")
        last = pts
        if start is not None and pts < start:
            continue
        if end is not None and pts > end:
            break
        if next_at is None:
            next_at = pts
        if pts + 1e-9 >= next_at:
            selected.append(frame)
            next_at += (math.floor((pts + 1e-9 - next_at) / interval) + 1) * interval
            if maximum and len(selected) >= maximum:
                break
    return selected


def stats(values):
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    def percentile(p):
        index = (len(ordered) - 1) * p
        low = math.floor(index)
        return ordered[low] + (ordered[math.ceil(index)] - ordered[low]) * (index - low)
    return {"count": len(values), "p50_ms": percentile(.5), "p95_ms": percentile(.95),
            "p99_ms": percentile(.99), "max_ms": max(values)}


def load_corpus(path, image_root):
    doc = json.loads(path.read_text())
    return [{**frame, "image_path": str(resolve(frame["image_path"], image_root)),
             "projection": "rectilinear" if frame.get("projection") == "perspective" else frame.get("projection"),
             "source_projection": frame.get("projection"),
             "input_kind": "still", "manifest_path": str(path)} for frame in doc["frames"]]


def load_frame_manifest(path, image_root):
    doc = json.loads(path.read_text())
    frames = doc["frames"]
    previous = None
    for frame in frames:
        pts = actual_pts(frame)
        if previous is not None and pts <= previous:
            raise ValueError("Extracted-frame manifest PTS must strictly increase")
        previous = pts
    return [{**frame, "image_path": str(resolve(frame["image_path"], image_root)),
             "input_kind": "video_frame", "manifest_path": str(path)} for frame in frames], doc


def checked_process(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{command[0]} failed ({result.returncode}): {result.stderr[-1500:]}")
    return result.stdout


def video_frames(path, directory, args):
    """Decode selected original frames without an fps filter or time synthesis."""
    raw = checked_process([args.ffprobe, "-v", "error", "-select_streams", "v:0",
                           "-show_frames", "-show_streams", "-show_entries",
                           "frame=pts,pts_time:stream=time_base,side_data_list", "-of", "json", str(path)])
    probe = json.loads(raw)
    time_base = probe.get("streams", [{}])[0].get("time_base")
    source = []
    for index, frame in enumerate(probe.get("frames", [])):
        if "pts_time" not in frame:
            raise ValueError("ffprobe frame lacks actual PTS; no fps-based substitution allowed")
        source.append({"frame_id": f"video-{index:08d}", "decode_index": index,
                       "pts_seconds": float(frame["pts_time"]), "source_pts": frame.get("pts"),
                       "source_time_base": time_base,
                       "projection": args.video_projection, "input_kind": "video_frame"})
    selected = sample_pts(source, args.cadence, args.start, args.end, args.max_frames)
    if not selected:
        return [], {"path": str(path), "sha256": sha256(path), "probe": probe.get("streams", [])}
    expression = "+".join(f"eq(n\\,{f['decode_index']})" for f in selected)
    checked_process([args.ffmpeg, "-v", "error", "-i", str(path), "-map", "0:v:0",
                     "-vf", f"select={expression}", "-fps_mode", "vfr", "-frames:v", str(len(selected)),
                     str(directory / "frame-%08d.png")])
    extracted = sorted(directory.glob("frame-*.png"))
    if len(extracted) != len(selected):
        raise ValueError("Extracted frame count differs from original-PTS selection")
    for frame, image in zip(selected, extracted):
        frame["image_path"] = str(image)
        frame["orientation_applied"] = "ffmpeg default autorotate"
    return selected, {"path": str(path), "sha256": sha256(path),
                      "timestamp_source": "ffprobe decoded frame pts_time; no inferred capture UTC",
                      "streams": probe.get("streams", [])}


def make_extractors(cv):
    available, unavailable = {}, {}
    def hough(image):
        edges = cv.Canny(image, 50, 150, apertureSize=3, L2gradient=False)
        return cv.HoughLinesP(edges, 1, math.pi / 180, 20, minLineLength=12, maxLineGap=5)
    available["canny_hough_p"] = hough
    factories = {
        "fast_line_detector": lambda: cv.ximgproc.createFastLineDetector(12, 1.41421356, 50, 150, 3, False).detect,
        "lsd": lambda: (lambda detector: lambda image: detector.detect(image)[0])(
            cv.createLineSegmentDetector(cv.LSD_REFINE_STD, .8)),
    }
    def ed_factory():
        detector = cv.ximgproc.createEdgeDrawing()
        parameters = cv.ximgproc_EdgeDrawing_Params()
        for key, value in SETTINGS["edge_drawing_lines"].items():
            setattr(parameters, key, value)
        detector.setParams(parameters)
        def detect(image):
            detector.detectEdges(image)
            return detector.detectLines()
        return detect
    factories["edge_drawing_lines"] = ed_factory
    for name, factory in factories.items():
        try:
            available[name] = factory()
        except (AttributeError, RuntimeError, TypeError) as error:
            unavailable[name] = str(error)
    unavailable["elsed"] = "Author implementation is not installed or wrapped; not run, no substituted timing"
    return available, unavailable


def run(frames, args):
    import cv2 as cv
    import numpy as np
    from PIL import Image, ImageOps
    # Zero explicitly disables OpenCV parallel regions. On this macOS GCD build,
    # setNumThreads(1) still reports the system worker count (16), unlike zero.
    cv.setNumThreads(0)
    cv.setRNGSeed(0)
    cv.ocl.setUseOpenCL(False)
    extractors, unavailable = make_extractors(cv)
    if cv.getNumThreads() != 1:
        raise RuntimeError("Unable to verify sequential OpenCV configuration")
    durations, preparation = defaultdict(list), []
    records, warmed, overlay_indices = [], set(), set()
    groups = defaultdict(list)
    for index, frame in enumerate(frames):
        if frame.get("projection") == "rectilinear" and Path(frame["image_path"]).is_file():
            groups[frame.get("clip_id", "stills")].append(index)
    for indices in groups.values():
        if args.overlays:
            overlay_indices.update(indices[round(i)] for i in np.linspace(0, len(indices) - 1, min(args.overlays, len(indices))))
    for frame_number, frame in enumerate(frames):
        record = {key: frame[key] for key in ("frame_id", "clip_id", "input_kind", "manifest_path", "projection", "source_projection",
                  "pts_seconds", "pts_value", "pts_timescale", "source_pts", "source_time_base", "decode_index",
                  "requested_seconds", "orientation_applied") if key in frame}
        path = Path(frame["image_path"])
        record["image_path"] = str(path)
        if frame.get("projection") != "rectilinear":
            record.update(status="skipped", reason="Projection is not explicitly rectilinear; panoramas require a calibrated view extraction")
            records.append(record)
            continue
        if not path.is_file():
            record.update(status="skipped", reason="Image bytes missing")
            records.append(record)
            continue
        image_sha = sha256(path)
        record["image_sha256"] = image_sha
        if frame.get("image_sha256") and frame["image_sha256"] != image_sha:
            record.update(status="skipped", reason="Image hash differs from manifest")
            records.append(record)
            continue
        begin = time.perf_counter_ns()
        with Image.open(path) as raw:
            record["stored_size"] = list(raw.size)
            record["exif_orientation"] = raw.getexif().get(274, 1)
            upright = ImageOps.exif_transpose(raw).convert("RGB")
            rgb = np.asarray(upright)
        decode_end = time.perf_counter_ns()
        height, width = rgb.shape[:2]
        size = resize_dimensions(width, height, args.max_edge, args.max_height)
        small = cv.resize(rgb, size, interpolation=cv.INTER_AREA) if size != (width, height) else rgb.copy()
        gray = cv.cvtColor(small, cv.COLOR_RGB2GRAY)
        top = min(gray.shape[0] - 1, round(gray.shape[0] * args.roi_top))
        roi = np.ascontiguousarray(gray[top:, :])
        prep_end = time.perf_counter_ns()
        record.update(status="processed", upright_size=[width, height], analysis_size=list(size),
                      roi_xywh=[0, top, size[0], size[1] - top],
                      upright_to_analysis={"scale_x": size[0] / width, "scale_y": size[1] / height,
                                           "roi_origin_xy": [0, top], "exif_transpose_applied": record["exif_orientation"]},
                      transform_note="Isotropic resize with integer rounding, then vertical ROI crop; no mount calibration",
                      image_decode_and_exif_ms=(decode_end - begin) / 1e6,
                      resize_gray_roi_ms=(prep_end - decode_end) / 1e6,
                      preprocessing_ms=(prep_end - begin) / 1e6, methods={})
        preparation.append(record["preprocessing_ms"])
        # Rotate method order between frames to reduce systematic thermal/order bias.
        names = list(extractors)
        shift = frame_number % len(names)
        for name in names[shift:] + names[:shift]:
            extractor = extractors[name]
            try:
                cv.setNumThreads(0)
                threads_before = cv.getNumThreads()
                if threads_before != 1:
                    raise RuntimeError("Extractor thread configuration is not sequential")
                if name not in warmed:
                    for _ in range(args.warmup):
                        extractor(roi)
                    warmed.add(name)
                samples = []
                for _ in range(args.repeats):
                    start = time.perf_counter_ns()
                    lines = extractor(roi)
                    samples.append((time.perf_counter_ns() - start) / 1e6)
                threads_after = cv.getNumThreads()
                if threads_after != 1:
                    raise RuntimeError("Extractor changed thread configuration; timings not accepted")
                durations[name].extend(samples)
                segments = np.empty((0, 4)) if lines is None else np.asarray(lines).reshape(-1, 4)
                lengths = np.linalg.norm(segments[:, :2] - segments[:, 2:], axis=1)
                chosen = segments[np.argsort(-lengths, kind="stable")[:args.max_segments]].copy()
                if len(chosen):
                    chosen[:, [1, 3]] += top
                record["methods"][name] = {"status": "ran", "extractor_samples_ms": samples,
                    "opencv_threads_before": threads_before, "opencv_threads_after": threads_after,
                    "segments_detected": len(segments), "segments_retained": len(chosen),
                    "segments_analysis_xyxy": [[round(float(value), 3) for value in line] for line in chosen]}
                if frame_number in overlay_indices:
                    overlay = cv.cvtColor(small, cv.COLOR_RGB2BGR)
                    cv.line(overlay, (0, top), (size[0] - 1, top), (0, 180, 255), 1)
                    for x1, y1, x2, y2 in chosen:
                        cv.line(overlay, (round(x1), round(y1)), (round(x2), round(y2)), (80, 255, 80), 1)
                    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(frame.get("frame_id", frame_number)))
                    overlay_path = args.output.parent / "overlays" / f"{frame_number:04d}-{safe_id}-{name}.png"
                    overlay_path.parent.mkdir(parents=True, exist_ok=True)
                    if not cv.imwrite(str(overlay_path), overlay):
                        raise OSError("Overlay write failed")
                    record["methods"][name]["overlay_path"] = str(overlay_path.resolve())
            except Exception as error:
                record["methods"][name] = {"status": "error", "reason": str(error)}
        records.append(record)
    packages = {}
    for package in ("opencv-contrib-python-headless", "opencv-contrib-python", "opencv-python-headless", "numpy", "Pillow"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    processor = platform.processor()
    if platform.system() == "Darwin":
        try:
            processor = checked_process(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        except (OSError, RuntimeError):
            pass
    return {"schema_version": 1, "probe": "classical-road-geometry-extractor-only",
            "script_sha256": sha256(__file__),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "host": {"platform": platform.platform(), "machine": platform.machine(),
                     "processor": processor, "python": platform.python_version(),
                     "opencv": cv.__version__, "packages": packages,
                     "opencv_threads": cv.getNumThreads(), "opencv_set_num_threads_argument": 0,
                     "opencv_parallel_framework": next((line.strip().split(":", 1)[1].strip() for line in cv.getBuildInformation().splitlines() if "Parallel framework:" in line), "unknown"),
                     "opencl_enabled": cv.ocl.useOpenCL(), "opencv_rng_seed": 0},
            "settings": {"max_edge": args.max_edge, "max_height": args.max_height, "roi_top_fraction": args.roi_top,
                         "repeats": args.repeats, "warmup_per_method": args.warmup,
                         "max_output_segments": args.max_segments, "extractors": SETTINGS},
            "limitations": ["Host extractor-only timings, not Android or iPhone measurements or a 200 ms guarantee.",
                "No lane grouping, physical tracking, governing-road association, sign suppression or recognition accuracy is evaluated.",
                "Preprocessing is separate; extractor times include internal Canny/gradient operations but exclude output sorting and overlays.",
                "Output segment cap bounds serialized future grouping input, not extractor runtime.",
                "Road ROI is a fixed generous crop, not inferred road geometry; unpainted roads and curves remain unsupported semantic cases.",
                "Warmup excluded; each frame repeated locally. No mobile thermal/concurrent-TSR qualification.",
                "Actual video PTS is retained when provided; no UTC or physical track is inferred from image order."],
            "not_run": unavailable, "preprocessing_summary": stats(preparation),
            "extractor_summary": {name: stats(values) for name, values in durations.items()},
            "frames": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--corpus", type=Path, action="append", help="Reviewed image-road corpus JSON; repeatable")
    inputs.add_argument("--frame-manifest", type=Path, help="Extracted video frames with actual pts_seconds or rational PTS")
    inputs.add_argument("--video", type=Path)
    parser.add_argument("--image-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-edge", type=int, default=384)
    parser.add_argument("--max-height", type=int, default=216, help="Additional height bound; resize remains isotropic")
    parser.add_argument("--roi-top", type=float, default=.35)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--max-segments", type=int, default=64)
    parser.add_argument("--overlays", type=int, default=3, help="Maximum diagnostic overlays per method per video clip (or all stills)")
    parser.add_argument("--cadence", type=float, default=.2)
    parser.add_argument("--start", type=float)
    parser.add_argument("--end", type=float)
    parser.add_argument("--max-frames", type=int, default=120)
    parser.add_argument("--video-projection", choices=("rectilinear", "unknown", "equirectangular"), default="unknown")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    if not 0 <= args.roi_top < 1 or min(args.max_edge, args.max_height, args.repeats, args.max_segments, args.max_frames) <= 0 or args.warmup < 0 or args.overlays < 0:
        parser.error("Invalid dimensions, repetitions, crop or bounds")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="youspeed-line-probe-") as temp:
        provenance = {}
        try:
            if args.corpus:
                frames = [frame for path in args.corpus for frame in load_corpus(path, args.image_root)]
                provenance["corpora"] = [{"path": str(path), "sha256": sha256(path)} for path in args.corpus]
            elif args.frame_manifest:
                frames, metadata = load_frame_manifest(args.frame_manifest, args.image_root)
                provenance["frame_manifest"] = {"path": str(args.frame_manifest), "sha256": sha256(args.frame_manifest),
                    "metadata": {key: value for key, value in metadata.items() if key != "frames"}}
            else:
                frames, provenance["video"] = video_frames(args.video, Path(temp), args)
            report = run(frames, args)
            report["inputs"] = provenance
        except Exception as error:
            report = {"schema_version": 1, "status": "blocked", "reason": str(error), "inputs": provenance,
                      "limitation": "No extraction or timing claim can be made from a blocked run"}
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"report": str(args.output), "status": report.get("status", "finished"),
                      "frames": len(report.get("frames", [])), "extractors": report.get("extractor_summary", {})}))
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
