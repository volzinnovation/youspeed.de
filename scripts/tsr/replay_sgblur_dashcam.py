#!/usr/bin/env python3
"""Offline, hash-checked YOLO11n/YOLO26s replay of private recorded video.

First extract fixed source-only keyframes for blind annotation. Inference uses
identical upright 1024 windows for both detectors, selects the mobile-compatible
one-to-many head, and records decoder timestamps. No app/device state is used.
"""
import argparse
import hashlib
import json
import math
import platform
import statistics
import time
from pathlib import Path

from compare_sgblur_detectors import CHECKPOINTS


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def video_capture(movie):
    import cv2
    path = Path(movie["local_path"])
    if not path.is_file() or path.stat().st_size != movie["bytes"] or sha(path) != movie["sha256"]:
        raise ValueError(f"Missing or changed video: {path}")
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    if not capture.isOpened():
        raise ValueError(f"Cannot decode {path}")
    capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
    if capture.get(cv2.CAP_PROP_ORIENTATION_AUTO) != 1:
        raise ValueError("Decoder does not support explicit automatic orientation")
    info = {
        "source_sha256": movie["sha256"], "source_bytes": path.stat().st_size,
        "backend": capture.getBackendName(), "fps": capture.get(cv2.CAP_PROP_FPS),
        "reported_frame_count": capture.get(cv2.CAP_PROP_FRAME_COUNT),
        "rotation_metadata_degrees": capture.get(cv2.CAP_PROP_ORIENTATION_META),
        "automatic_orientation": True,
    }
    return capture, info


def read_window(capture, requested_seconds):
    import cv2
    import numpy as np
    if not capture.set(cv2.CAP_PROP_POS_MSEC, requested_seconds * 1000):
        raise ValueError("Decoder seek failed")
    ok, frame = capture.read()
    if not ok:
        raise ValueError(f"Frame decode failed at {requested_seconds}s")
    pts = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
    if not math.isfinite(pts) or (requested_seconds > 1 and pts <= 0):
        raise ValueError("Decoder returned an invalid timestamp")
    height, width = frame.shape[:2]
    scaled_width = round(width * 1024 / height)
    scaled = cv2.resize(frame, (scaled_width, 1024), interpolation=cv2.INTER_LINEAR)
    window = np.full((1024, 1024, 3), 114, dtype=np.uint8)
    if scaled_width >= 1024:
        window[:] = scaled[:, -1024:]
    else:
        window[:, -scaled_width:] = scaled
    return window, {
        "requested_seconds": requested_seconds, "decoder_pts_seconds": pts,
        "decoder_frame_index": int(round(capture.get(cv2.CAP_PROP_POS_FRAMES))) - 1,
        "upright_source_dimensions": [width, height],
        "window_rgb_sha256": hashlib.sha256(window[:, :, ::-1].tobytes()).hexdigest(),
    }


def frame_id(movie_id, seconds):
    return f"{movie_id}-{round(seconds * 1000):07d}"


def extract(plan, output, selected_movies=None):
    import cv2
    existing = output / "blind-frames.json"
    previous = json.loads(existing.read_text()) if existing.exists() else {}
    frames, movies = previous.get("frames", []), previous.get("movies", [])
    for movie in plan["movies"]:
        if selected_movies and movie["id"] not in selected_movies:
            continue
        frames = [f for f in frames if f["movie_id"] != movie["id"]]
        movies = [m for m in movies if m["id"] != movie["id"]]
        capture, info = video_capture(movie)
        info["id"] = movie["id"]
        movies.append(info)
        for seconds in range(0, math.floor(movie["duration_seconds"]), 10):
            window, record = read_window(capture, seconds)
            identifier = frame_id(movie["id"], seconds)
            target = output / "blind-keyframes" / (identifier + ".png")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(target), window):
                raise ValueError("Cannot save keyframe")
            frames.append({"frame_id": identifier, "movie_id": movie["id"],
                           "image_path": str(target), "image_sha256": sha(target),
                           "scored_keyframe": seconds % 30 == 0, **record})
        capture.release()
        save(output / "blind-frames.json", {"movies": movies, "frames": frames})
        print(f"Source-only keyframes extracted: {movie['id']}", flush=True)
    print(f"Fixed blind scoring frames: {sum(f['scored_keyframe'] for f in frames)}", flush=True)


def infer(plan, output, baseline, candidate):
    import cv2
    import numpy as np
    import torch
    import ultralytics
    from ultralytics import YOLO
    for key, path in (("yolo11n", baseline), ("yolo26s", candidate)):
        if sha(path) != CHECKPOINTS[key]:
            raise ValueError(f"Unexpected {key} weights")
    source_frames = json.loads((output / "blind-frames.json").read_text())
    blind = {f["frame_id"]: f for f in source_frames["frames"]}
    torch.set_num_threads(4)
    models = {"yolo11n": YOLO(baseline), "yolo26s": YOLO(candidate)}
    settings = dict(imgsz=1024, rect=False, conf=plan["confidence_threshold"],
                    iou=plan["nms_iou"], max_det=300, device="cpu", verbose=False)
    for model in models.values():
        assert model.names == {0: "sign", 1: "plate", 2: "face"}
        model.model.end2end = False
        for _ in range(3):
            model.predict(np.full((1024, 1024, 3), 114, np.uint8), **settings)
    metadata = {
        "schema_version": 1, "script_sha256": sha(Path(__file__)),
        "plan_sha256": hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
        "checkpoints": CHECKPOINTS, "device": "Mac CPU", "threads": 4,
        "torch": torch.__version__, "ultralytics": ultralytics.__version__,
        "opencv": cv2.__version__, "platform": platform.platform(),
        "configuration": settings, "end2end": False,
        "preprocessing": "OpenCV orientation-auto once, proportional full-height linear resize, rightmost1024, left pad114",
        "timestamp_scope": "Decoder-reported video PTS; no capture-UTC or GPS mapping inferred",
        "latency_scope": "predict wall time; excludes decode, window resize and evidence writing; not phone latency",
    }
    metadata_path = output / "replay-metadata.json"
    if metadata_path.exists() and json.loads(metadata_path.read_text()) != metadata:
        raise ValueError("Existing replay metadata changed; use a new output directory")
    save(metadata_path, metadata)
    summaries = []
    for movie in plan["movies"]:
        capture, info = video_capture(movie)
        target = output / (movie["id"] + ".predictions.ndjson")
        existing = {}
        if target.exists():
            for line in target.read_text().splitlines():
                row = json.loads(line)
                existing[row["frame_id"]] = row
        total = math.floor(movie["duration_seconds"] * plan["sampling_hz"])
        rows = list(existing.values())
        with target.open("a") as stream:
            for index in range(total):
                seconds = index / plan["sampling_hz"]
                identifier = frame_id(movie["id"], seconds)
                if identifier in existing:
                    continue
                if identifier in blind:
                    record = blind[identifier]
                    image_path = Path(record["image_path"])
                    if sha(image_path) != record["image_sha256"]:
                        raise ValueError("Changed blind keyframe")
                    window = cv2.imread(str(image_path))
                    details = {key: record[key] for key in (
                        "requested_seconds", "decoder_pts_seconds", "decoder_frame_index",
                        "upright_source_dimensions", "window_rgb_sha256")}
                else:
                    window, details = read_window(capture, seconds)
                arms = {}
                # Rotate order to avoid consistently timing one model first.
                order = list(models) if index % 2 == 0 else list(reversed(models))
                for arm in order:
                    started = time.perf_counter()
                    result = models[arm].predict(window, **settings)[0]
                    elapsed = (time.perf_counter() - started) * 1000
                    arms[arm] = {"boxes_xyxy_score_class": result.boxes.data.cpu().tolist(),
                                 "predict_wall_ms": elapsed, "stages_ms": result.speed}
                row = {"frame_id": identifier, "movie_id": movie["id"], **details, "arms": arms}
                stream.write(json.dumps(row, allow_nan=False) + "\n")
                stream.flush()
                rows.append(row)
                if index % 4 == 0 and identifier not in blind:
                    preview = output / "review-windows" / (identifier + ".jpg")
                    preview.parent.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(preview), window, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if (index + 1) % 100 == 0:
                    print(f"Replay progress: {movie['id']} {index+1}/{total} samples", flush=True)
        capture.release()
        summaries.append({
            "movie_id": movie["id"], "frames": len(rows), "expected_samples": total,
            "source": info, "unique_decoder_frames": len({r["decoder_frame_index"] for r in rows}),
            "decoder_pts_max_abs_request_difference_seconds": max(abs(r["decoder_pts_seconds"] - r["requested_seconds"]) for r in rows),
            "arms": {arm: {
                "sign_proposals": sum(sum(int(b[5]) == 0 for b in r["arms"][arm]["boxes_xyxy_score_class"]) for r in rows),
                "frames_with_sign_proposals": sum(any(int(b[5]) == 0 for b in r["arms"][arm]["boxes_xyxy_score_class"]) for r in rows),
                "predict_wall_median_ms": statistics.median(r["arms"][arm]["predict_wall_ms"] for r in rows),
                "predict_wall_p95_ms": sorted(r["arms"][arm]["predict_wall_ms"] for r in rows)[math.ceil(.95 * len(rows)) - 1],
            } for arm in models},
        })
        save(output / "replay-summary.json", {"movies": summaries, "raw_counts_are_not_accuracy": True})
        print(f"Replay completed: {movie['id']}, {len(rows)} samples", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("extract", "infer"))
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--movie", action="append", help="Extract only this preselected movie; may be repeated")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == "extract":
        requested = set(args.movie or [])
        if not requested.issubset({m["id"] for m in plan["movies"]}):
            parser.error("--movie must name a movie in the fixed plan")
        extract(plan, args.output, requested)
    else:
        if args.movie:
            parser.error("--movie applies only to source extraction")
        if args.baseline is None or args.candidate is None:
            parser.error("infer requires --baseline and --candidate")
        infer(plan, args.output, args.baseline, args.candidate)


if __name__ == "__main__":
    main()
