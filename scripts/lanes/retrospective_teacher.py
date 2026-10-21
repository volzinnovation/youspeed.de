#!/usr/bin/env python3
"""Mine positive-only marking weak labels from flow-aligned retrospective evidence.

The native replay is never changed. Reviewed painted intervals are the preferred
seeds; --bootstrap-from-baseline explicitly uses correlated fresh/fused native
post-temporal, pre-presentation hypotheses. Empty observedSegments are NOT paint.
Outputs are weak labels pending review, never independent evaluation truth.
Requires NumPy and OpenCV; Python 3.9+.
"""
import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import gzip
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class Config:
    mode: str = "retrospective"
    horizon_seconds: float = 0.5
    maximum_adjacent_gap_seconds: float = 0.2
    minimum_source_frames: int = 2
    minimum_future_frames: int = 2
    anchor_step_pixels: float = 2.0
    maximum_anchors_per_frame: int = 1024
    maximum_source_frames: int = 16
    consistency_pixels: float = 1.0
    maximum_lk_error: float = 18.0
    consensus_radius_pixels: float = 2.0
    minimum_brightness: float = 80.0
    minimum_ridge_contrast: float = 18.0
    maximum_positive_points: int = 2048
    reviewed_anchor_radius_pixels: float = 2.0

    def validate(self):
        if self.mode not in ("retrospective", "causal"):
            raise ValueError("Unknown teacher mode")
        values = asdict(self)
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)
               for k, v in values.items() if k != "mode"):
            raise ValueError("Configuration values must be finite numbers")
        if not 0 < self.horizon_seconds <= 2 or not 0 < self.maximum_adjacent_gap_seconds <= 0.8:
            raise ValueError("Horizon must be (0,2] s; adjacent gap must be (0,0.8] s")
        if self.minimum_source_frames < 2 or self.minimum_future_frames < 2:
            raise ValueError("At least two distinct source frames and two retrospective future frames are required")
        if not 0 < self.anchor_step_pixels <= 8 or not 0 < self.consensus_radius_pixels <= 4:
            raise ValueError("Invalid bounded anchor spacing/consensus radius")
        if not 0 < self.consistency_pixels <= 2 or not 0 < self.maximum_lk_error <= 40:
            raise ValueError("Invalid optical-flow thresholds")
        if not 1 <= self.maximum_anchors_per_frame <= 4096 or not 1 <= self.maximum_positive_points <= 4096:
            raise ValueError("Invalid output/anchor capacity")
        if not 3 <= self.maximum_source_frames <= 32:
            raise ValueError("Invalid source-frame capacity")
        if not 0 <= self.minimum_brightness <= 255 or not 0 < self.minimum_ridge_contrast <= 255:
            raise ValueError("Invalid image evidence thresholds")
        if not 0 < self.reviewed_anchor_radius_pixels <= 2:
            raise ValueError("Invalid reviewed-anchor alignment radius")


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def read_ndjson(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        content = handle.read()
    return [json.loads(line) for line in content.splitlines() if line.strip()], sha_bytes(content)


def read_replay(directory):
    directory = Path(directory).resolve()
    manifest_path = directory / "input.normalized.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schemaVersion") != 1 or not manifest.get("frames"):
        raise ValueError("Replay must contain nonempty schemaVersion 1 input.normalized.json")
    replay_path = directory / "frames.ndjson"
    if not replay_path.exists():
        replay_path = directory / "frames.ndjson.gz"
    rows, replay_hash = read_ndjson(replay_path)
    frames = manifest["frames"]
    if len(rows) != len(frames):
        raise ValueError("Replay and manifest frame counts differ")
    seen, closed_sequences, previous_sequence, previous_time = set(), set(), None, -math.inf
    images = []
    for frame, row in zip(frames, rows):
        fid = frame["id"]
        time = frame["time"]
        if fid in seen or not isinstance(fid, str) or not fid:
            raise ValueError("Missing/duplicate frame ID")
        seen.add(fid)
        sequence = frame["sequenceId"]
        if not isinstance(sequence, str) or not sequence:
            raise ValueError("Missing sequence identity")
        if sequence != previous_sequence:
            if sequence in closed_sequences:
                raise ValueError("A sequence cannot reappear after another sequence")
            if previous_sequence is not None:
                closed_sequences.add(previous_sequence)
            previous_sequence, previous_time = sequence, -math.inf
        if isinstance(time, bool) or not isinstance(time, (int, float)) or not math.isfinite(time) or time <= previous_time:
            raise ValueError("PTS must be finite and strictly increasing within a sequence")
        previous_time = time
        w, h = frame["width"], frame["height"]
        if type(w) is not int or type(h) is not int or not (64 <= w <= 384 and 64 <= h <= 216):
            raise ValueError("Unsupported native replay image dimensions")
        path = Path(frame["grayPath"])
        path = path if path.is_absolute() else manifest_path.parent / path
        content = path.read_bytes()
        digest = sha_bytes(content)
        if len(content) != w * h or digest != frame["graySha256"]:
            raise ValueError("Manifest gray bytes/hash mismatch: " + fid)
        if (row.get("id") != fid or row.get("sequenceId") != sequence or row.get("time") != time or
                row.get("width") != w or row.get("height") != h or row.get("inputSha256") != digest):
            raise ValueError("Replay row/source alignment mismatch: " + fid)
        frame["grayPath"] = str(path.resolve())
        images.append(np.frombuffer(content, np.uint8).reshape(h, w))
    return frames, rows, images, dict(manifestPath=str(manifest_path),
        manifestSha256=sha_bytes(manifest_path.read_bytes()), replayPath=str(replay_path),
        replayUncompressedSha256=replay_hash, variant=manifest.get("variant"),
        previewMode=manifest.get("previewMode"),
        replayOptions={k: manifest.get(k) for k in ("groupFragments", "fragmentTracking", "useSearchBands",
            "retainTentativeIdentity", "jointSelection")})


def partitions(frames, config):
    """No propagation across sequence, split, source, geometry or temporal discontinuities."""
    result, generation, previous, previous_key = [], -1, None, None
    for frame in frames:
        key = tuple(str(frame.get(k, "unspecified")) for k in
            ("sequenceId", "split", "source", "width", "height", "decodedWidth", "decodedHeight", "orientationKey"))
        if previous is None or key != previous_key or frame["time"] - previous["time"] > config.maximum_adjacent_gap_seconds + 1e-9:
            generation += 1
        result.append(generation)
        previous, previous_key = frame, key
    return result


def valid_polyline(points):
    return (isinstance(points, list) and 2 <= len(points) <= 256 and
        all(isinstance(p, list) and len(p) == 2 and
            all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1 for v in p)
            for p in points) and all(b[1] > a[1] for a, b in zip(points, points[1:])))


def clip_interval(points, lo, hi):
    lo, hi = max(lo, points[0][1]), min(hi, points[-1][1])
    if hi <= lo:
        return []
    def at(y):
        for a, b in zip(points, points[1:]):
            if a[1] <= y <= b[1]:
                t = (y - a[1]) / (b[1] - a[1])
                return [a[0] + t * (b[0] - a[0]), y]
        raise ValueError("Interval outside polyline")
    return [at(lo)] + [p for p in points if lo < p[1] < hi] + [at(hi)]


def ridge_evidence(image, point, config):
    """Conservative current-pixel evidence; no semantic or ego-lane assertion."""
    x, y = int(round(float(point[0]))), int(round(float(point[1])))
    h, w = image.shape
    if x < 10 or x >= w - 10 or y < 2 or y >= h - 2:
        return False
    for radius in (1, 2):
        middle = float(image[y-1:y+2, x-radius:x+radius+1].mean())
        offset = radius * 3 + 1
        left = float(image[y-1:y+2, x-offset-radius:x-offset+radius+1].mean())
        right = float(image[y-1:y+2, x+offset-radius:x+offset+radius+1].mean())
        if middle >= config.minimum_brightness and min(middle-left, middle-right) >= config.minimum_ridge_contrast:
            return True
    return False


def sampled_anchors(segments, image, config):
    h, w = image.shape
    found = {}
    for segment_id, points in segments:
        for a, b in zip(points, points[1:]):
            start = np.asarray(a, dtype=np.float64) * [w-1, h-1]
            end = np.asarray(b, dtype=np.float64) * [w-1, h-1]
            count = max(1, int(math.ceil(float(np.linalg.norm(end-start)) / config.anchor_step_pixels)))
            for j in range(count+1):
                p = start + (end-start) * (j/count)
                key = (int(round(p[0])), int(round(p[1])))
                if key not in found and ridge_evidence(image, p, config):
                    found[key] = (p.tolist(), segment_id)
                    if len(found) >= config.maximum_anchors_per_frame:
                        return list(found.values())
    return list(found.values())


def collect_seeds(frames, rows, images, config, seed_labels=None, bootstrap=False):
    diagnostics = Counter()
    labels = {}
    if seed_labels is not None:
        labels = {r["id"]: r for r in seed_labels.get("frames", [])}
        if len(labels) != len(seed_labels.get("frames", [])):
            raise ValueError("Duplicate reviewed seed frame")
        unknown = set(labels) - {f["id"] for f in frames}
        if unknown:
            raise ValueError("Reviewed seed frames absent from replay: " + ", ".join(sorted(unknown)[:5]))
    all_anchors = []
    for frame, row, image in zip(frames, rows, images):
        segments = []
        if bootstrap:
            for bi, boundary in enumerate(row.get("rawBoundaries", [])):
                if boundary.get("cue") != "paint":
                    diagnostics["nonpaint_boundary"] += 1
                    continue
                if boundary.get("provenance") not in ("fresh", "fused"):
                    diagnostics["tracked_or_unknown_provenance"] += 1
                    continue
                age = boundary.get("evidenceAgeSeconds", 0)
                last = boundary.get("lastFreshTimestampSeconds")
                if (not isinstance(age, (int, float)) or not math.isfinite(age) or abs(age) > 1e-9 or
                        last is not None and (not isinstance(last, (int, float)) or not math.isfinite(last) or abs(last-frame["time"]) > 1e-6)):
                    diagnostics["not_current_fresh_evidence"] += 1
                    continue
                observed = boundary.get("observedSegments")
                if not observed:
                    diagnostics["empty_observed_segments"] += 1
                    continue
                for si, points in enumerate(observed):
                    if not valid_polyline(points):
                        diagnostics["invalid_observed_segment"] += 1
                        continue
                    segments.append((f"{frame['id']}:native:{bi}:{si}", points))
        else:
            label = labels.get(frame["id"])
            if label is not None:
                required = {"id", "inputSha256", "time", "sequenceId", "split"}
                if not required.issubset(label):
                    raise ValueError("Reviewed seed missing explicit identity fields: " + frame["id"] +
                        " / " + ", ".join(sorted(required-set(label))))
                if (label["sequenceId"] != frame["sequenceId"] or label["time"] != frame["time"] or
                        label["split"] != frame.get("split", "unspecified")):
                    raise ValueError("Reviewed seed time/sequence/split mismatch: " + frame["id"])
                if label["inputSha256"] != frame["graySha256"]:
                    raise ValueError("Reviewed seed input hash mismatch")
                for bi, border in enumerate(label.get("borders", [])):
                    points = border.get("geometry", [])
                    if not valid_polyline(points):
                        raise ValueError("Invalid reviewed border geometry")
                    for si, interval in enumerate(border.get("paintedYIntervals", [])):
                        if (not isinstance(interval, list) or len(interval) != 2 or
                            not all(isinstance(v, (int, float)) and math.isfinite(v) for v in interval) or
                            not 0 <= interval[0] < interval[1] <= 1):
                            raise ValueError("Invalid reviewed painted interval")
                        points_in_interval = clip_interval(points, *interval)
                        if points_in_interval:
                            segments.append((f"{frame['id']}:reviewed:{bi}:{si}", points_in_interval))
        anchors = sampled_anchors(segments, image, config)
        diagnostics["explicit_source_segments"] += len(segments)
        diagnostics["image_supported_source_anchors"] += len(anchors)
        diagnostics["source_frames_with_anchors"] += bool(anchors)
        all_anchors.append(anchors)
    return all_anchors, diagnostics


def align_anchors(source, target, anchors, config):
    if not anchors:
        return []
    initial = np.asarray([a[0] for a in anchors], dtype=np.float32).reshape(-1, 1, 2)
    if source is target:
        return [(a[0], a[1], 0.0, 0.0) for a in anchors]
    options = dict(winSize=(15, 15), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, .01))
    projected, status, error = cv2.calcOpticalFlowPyrLK(source, target, initial, None, **options)
    if projected is None or status is None or error is None:
        return []
    finite = np.isfinite(projected).all(axis=(1, 2))
    # The reverse API must not receive nonfinite endpoints even when status is 0.
    safe = projected.copy()
    safe[~finite] = initial[~finite]
    returned, reverse, reverse_error = cv2.calcOpticalFlowPyrLK(target, source, safe, None, **options)
    if returned is None or reverse is None or reverse_error is None:
        return []
    disagreement = np.linalg.norm(returned[:, 0]-initial[:, 0], axis=1)
    valid = (finite & (status[:, 0] > 0) & (reverse[:, 0] > 0) &
        np.isfinite(disagreement) & (disagreement <= config.consistency_pixels) &
        np.isfinite(error[:, 0]) & (error[:, 0] <= config.maximum_lk_error) &
        np.isfinite(reverse_error[:, 0]) & (reverse_error[:, 0] <= config.maximum_lk_error))
    result = []
    for i in np.flatnonzero(valid):
        point = projected[i, 0].tolist()
        if ridge_evidence(target, point, config):
            result.append((point, anchors[i][1], float(disagreement[i]), float(error[i, 0])))
    return result


def source_indices(frames, partition_ids, index, config):
    time = frames[index]["time"]
    indices = []
    per_side = config.maximum_source_frames if config.mode == "causal" else config.maximum_source_frames // 2
    for other in range(index, max(-1, index-per_side), -1):
        if partition_ids[other] != partition_ids[index] or time-frames[other]["time"] > config.horizon_seconds+1e-9:
            break
        indices.append(other)
    if config.mode == "retrospective":
        for other in range(index+1, min(len(frames), index+1+config.maximum_source_frames-per_side)):
            if partition_ids[other] != partition_ids[index] or frames[other]["time"]-time > config.horizon_seconds+1e-9:
                break
            indices.append(other)
    return sorted(indices)


def consensus_points(proposals, frame, image, frames, config):
    """Multiple anchors from one exposure count as exactly one temporal support."""
    radius = config.consensus_radius_pixels
    cells = {}
    candidates = set()
    for proposal in proposals:
        x, y = proposal["point"]
        key = (int(math.floor(x/radius)), int(math.floor(y/radius)))
        cells.setdefault(key, []).append(proposal)
        candidates.add((int(round(x)), int(round(y))))
    accepted = []
    for x, y in sorted(candidates, key=lambda p: (p[1], p[0])):
        if not ridge_evidence(image, (x, y), config):
            continue
        key = (int(math.floor(x/radius)), int(math.floor(y/radius)))
        support = {}
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for p in cells.get((key[0]+dx, key[1]+dy), []):
                    distance = (p["point"][0]-x)**2 + (p["point"][1]-y)**2
                    if distance > radius*radius:
                        continue
                    old = support.get(p["sourceIndex"])
                    if old is None or (distance, p["segmentId"]) < (old[0], old[1]["segmentId"]):
                        support[p["sourceIndex"]] = (distance, p)
        future = [i for i in support if frames[i]["time"] > frame["time"]]
        if len(support) < config.minimum_source_frames or (config.mode == "retrospective" and len(future) < config.minimum_future_frames):
            continue
        ordered = [support[i][1] for i in sorted(support)]
        accepted.append(dict(pixel=[x, y], point=[x/(frame["width"]-1), y/(frame["height"]-1)],
            sourceFrameIds=[frames[p["sourceIndex"]]["id"] for p in ordered],
            sourceSegmentIds=[p["segmentId"] for p in ordered], futureSupportCount=len(future),
            maximumForwardBackwardErrorPixels=max(p["fbError"] for p in ordered)))
        if len(accepted) >= config.maximum_positive_points:
            break
    return accepted


def diagnostic_agreement(points, boundaries, width, height, tolerance=3.0):
    count = 0
    for p in points:
        x, y = p["point"]
        matched = False
        for b in boundaries:
            geometry = b.get("points", [])
            if not valid_polyline(geometry):
                continue
            for a, z in zip(geometry, geometry[1:]):
                if a[1] <= y <= z[1]:
                    bx = a[0] + (z[0]-a[0]) * (y-a[1])/(z[1]-a[1])
                    if abs(bx-x)*(width-1) <= tolerance:
                        matched = True
                        break
            if matched:
                break
        count += matched
    return count


def reviewed_anchor_guard(positives, aligned_reviewed, frames, config):
    """Semantic seed constraint only: anchors never add temporal consensus votes."""
    accepted = []
    radius_squared = config.reviewed_anchor_radius_pixels ** 2
    for point in positives:
        x, y = point["pixel"]
        matches = {}
        for anchor in aligned_reviewed:
            distance = (anchor["point"][0]-x)**2 + (anchor["point"][1]-y)**2
            if distance > radius_squared:
                continue
            # Keep the closest verified correspondence for each reviewed segment.
            key = (anchor["sourceIndex"], anchor["segmentId"])
            old = matches.get(key)
            if old is None or distance < old[0]:
                matches[key] = (distance, anchor)
        if not matches:
            continue
        ordered = [matches[key] for key in sorted(matches)]
        result = dict(point)
        result["reviewedAnchorFrameIds"] = sorted({frames[p["sourceIndex"]]["id"] for _, p in ordered})
        result["reviewedAnchorSegmentIds"] = [p["segmentId"] for _, p in ordered]
        result["minimumReviewedAnchorDistancePixels"] = math.sqrt(min(d for d, _ in ordered))
        result["maximumReviewedAnchorForwardBackwardErrorPixels"] = max(p["fbError"] for _, p in ordered)
        # sourceFrameIds / futureSupportCount deliberately remain unchanged.
        accepted.append(result)
    return accepted


def run(replay_dir, output_dir, config, seed_labels_path=None, bootstrap=False, baseline_replay_dir=None,
        reviewed_anchor_labels_path=None):
    config.validate()
    if bool(seed_labels_path) == bool(bootstrap):
        raise ValueError("Choose exactly one: --seed-labels or --bootstrap-from-baseline")
    if reviewed_anchor_labels_path and not bootstrap:
        raise ValueError("--reviewed-anchor-labels is a separate guard for bootstrap mode only")
    output = Path(output_dir).resolve()
    if output.exists():
        raise ValueError("Output directory already exists; use a fresh directory")
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0)
    cv2.ocl.setUseOpenCL(False)
    frames, rows, images, replay_meta = read_replay(replay_dir)
    baseline_rows, baseline_meta = rows, replay_meta
    if baseline_replay_dir:
        baseline_frames, baseline_rows, _, baseline_meta = read_replay(baseline_replay_dir)
        if [(f["id"], f["graySha256"], f["time"]) for f in baseline_frames] != [(f["id"], f["graySha256"], f["time"]) for f in frames]:
            raise ValueError("Baseline and teacher-source replays must contain the same ordered exposures")
    seed_labels = json.loads(Path(seed_labels_path).read_text()) if seed_labels_path else None
    anchors, seed_diagnostics = collect_seeds(frames, rows, images, config, seed_labels, bootstrap)
    guard_labels = json.loads(Path(reviewed_anchor_labels_path).read_text()) if reviewed_anchor_labels_path else None
    guard_anchors, guard_diagnostics = (collect_seeds(frames, rows, images, config, guard_labels, False)
        if guard_labels is not None else (None, Counter()))
    partition_ids = partitions(frames, config)
    output.mkdir(parents=True, exist_ok=False)
    (output / "masks").mkdir()
    caveats = [
        "Positive-only marking weak labels pending review; not evaluation ground truth or calibrated probabilities.",
        "Sources named rawBoundaries are native post-temporal, pre-presentation hypotheses, not all raw ridge candidates.",
        "Multiple source frames provide temporal support, not statistically independent semantic evidence.",
        "No ego-lane, road-area, negative/background or invisible-paint label is inferred.",
        "All pixels except accepted marking points are unknown. Separate reviewed/public negative/background supervision is necessary for segmentation training.",
        "Current target-image ridge evidence is required; no target detector hypothesis is required.",
        "Optical flow and brightness agreement can still preserve wrong semantic structures; independent reviewed truth is required to assess correctness.",
        "Source observations never cross sequence/split/source/geometry boundaries or adjacent-frame gaps above the configured limit.",
        "Teacher support metadata/future frames must not be input features of a causal student; student-inputs.json contains target-only fields.",
        "Host replay and offline teacher timings are not live-device performance evidence.",
    ]
    if bootstrap:
        caveats.append("Bootstrap seeds are correlated with the recognizer being evaluated. Agreement measures are circular diagnostics, never accuracy.")
    if guard_labels is not None:
        caveats.append("Reviewed-anchor guarding is a separate semantic-supervision arm on development evidence, not an independently evaluated accuracy improvement. Guard anchors add no temporal support votes.")
    metadata = dict(schemaVersion=1, teacher="retrospective-marking-point-miner-v1", config=asdict(config),
        usesFutureFrames=config.mode == "retrospective", sourceMode="native_bootstrap" if bootstrap else "reviewed_interval_seeds",
        sourceQualification="fresh/fused explicit observedSegments with local source-image evidence" if bootstrap else "explicit reviewed paintedYIntervals with local source-image evidence",
        seedLabelsSha256=sha_bytes(Path(seed_labels_path).read_bytes()) if seed_labels_path else None,
        seedReviewer=seed_labels.get("reviewer") if seed_labels else None,
        seedQualification=seed_labels.get("qualification") if seed_labels else None,
        reviewedAnchorGuardEnabled=guard_labels is not None,
        reviewedAnchorLabelsSha256=sha_bytes(Path(reviewed_anchor_labels_path).read_bytes()) if reviewed_anchor_labels_path else None,
        reviewedAnchorReviewer=guard_labels.get("reviewer") if guard_labels else None,
        reviewedAnchorQualification=guard_labels.get("qualification") if guard_labels else None,
        replay=replay_meta, diagnosticBaseline=baseline_meta, codeSha256=sha_bytes(Path(__file__).read_bytes()),
        versions=dict(opencv=cv2.__version__, numpy=np.__version__), maskValues={"0": "unknown", "1": "observed_marking_positive_weak_label"},
        coordinateSystem="upright analysis image; normalized by width-1 and height-1", caveats=caveats)
    write_json(output / "metadata.json", metadata)
    summary = Counter()
    sequence_summary = {}
    student_frames = []
    with (output / "annotations.ndjson").open("w") as handle:
        for index, (frame, image) in enumerate(zip(frames, images)):
            proposals, support_sources = [], []
            for source_index in source_indices(frames, partition_ids, index, config):
                if not anchors[source_index]:
                    continue
                aligned = align_anchors(images[source_index], image, anchors[source_index], config)
                if not aligned:
                    continue
                source = frames[source_index]
                support_sources.append(dict(id=source["id"], time=source["time"], inputSha256=source["graySha256"],
                    offsetSeconds=source["time"]-frame["time"], alignedPointCount=len(aligned)))
                proposals.extend(dict(point=p, segmentId=s, fbError=e, lkError=lk, sourceIndex=source_index) for p, s, e, lk in aligned)
            positives = consensus_points(proposals, frame, image, frames, config)
            before_guard = len(positives)
            reviewed_sources = []
            if guard_anchors is not None:
                aligned_reviewed = []
                for source_index in source_indices(frames, partition_ids, index, config):
                    if not guard_anchors[source_index]:
                        continue
                    aligned = align_anchors(images[source_index], image, guard_anchors[source_index], config)
                    if not aligned:
                        continue
                    source = frames[source_index]
                    reviewed_sources.append(dict(id=source["id"], time=source["time"], inputSha256=source["graySha256"],
                        offsetSeconds=source["time"]-frame["time"], alignedPointCount=len(aligned)))
                    aligned_reviewed.extend(dict(point=p, segmentId=s, fbError=e, sourceIndex=source_index)
                        for p, s, e, _ in aligned)
                positives = reviewed_anchor_guard(positives, aligned_reviewed, frames, config)
            mask = np.zeros(image.shape, np.uint8)
            for p in positives:
                x, y = p["pixel"]
                mask[y, x] = 1
            relative = "masks/" + sha_bytes(frame["id"].encode())[:24] + ".png"
            if not cv2.imwrite(str(output / relative), mask, [cv2.IMWRITE_PNG_COMPRESSION, 9]):
                raise RuntimeError("Mask export failed")
            baseline = baseline_rows[index]
            agreement = dict(prePresentationGeometryPoints=diagnostic_agreement(positives, baseline.get("rawBoundaries", []), frame["width"], frame["height"]),
                publishedGeometryPoints=diagnostic_agreement(positives, baseline.get("confirmedBoundaries", []), frame["width"], frame["height"]),
                qualification="within three analysis pixels horizontally of baseline geometry; diagnostic agreement, NOT accuracy")
            row = dict(schemaVersion=1, id=frame["id"], sequenceId=frame["sequenceId"], split=frame.get("split", "unspecified"),
                time=frame["time"], inputSha256=frame["graySha256"], width=frame["width"], height=frame["height"],
                partitionId=partition_ids[index], status="positive_points" if positives else "unknown",
                usesFutureFrames=any(p["futureSupportCount"] > 0 for p in positives), positivePoints=positives,
                supportSources=support_sources, maskPath=relative, maskSha256=sha_bytes((output/relative).read_bytes()),
                unknownPixelCount=int(mask.size-np.count_nonzero(mask)), negativePixelCount=0,
                sourceMode=metadata["sourceMode"], diagnosticAgreement=agreement,
                reviewedAnchorGuardEnabled=guard_anchors is not None, reviewedAnchorSources=reviewed_sources,
                positivePointsBeforeReviewedGuard=before_guard, rejectedByReviewedAnchorGuard=before_guard-len(positives),
                unknownReason=None if positives else "no_qualified_reviewed_anchor" if before_guard and guard_anchors is not None
                    else "insufficient_qualified_multiframe_marking_support")
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
            student_frames.append({k: frame[k] for k in ("id", "sequenceId", "time", "grayPath", "graySha256", "width", "height")})
            student_frames[-1]["split"] = frame.get("split", "unspecified")
            counts = dict(frames=1, framesWithPositivePoints=int(bool(positives)), positivePoints=len(positives),
                framesWithPositivePointsBeforeReviewedGuard=int(bool(before_guard)), positivePointsBeforeReviewedGuard=before_guard,
                rejectedByReviewedAnchorGuard=before_guard-len(positives),
                inputPixels=int(mask.size), pointsNearBaselinePrePresentationGeometry=agreement["prePresentationGeometryPoints"],
                pointsNearBaselinePublishedGeometry=agreement["publishedGeometryPoints"])
            summary.update(counts)
            sequence_summary.setdefault(frame["sequenceId"], Counter()).update(counts)
    write_json(output / "student-inputs.json", dict(schemaVersion=1,
        qualification="Causal student input index: target exposure only; no future frames, teacher outputs or support metadata.", frames=student_frames))
    report = dict(schemaVersion=1, qualification="Coverage and diagnostic agreement only; no accuracy claim.",
        total=dict(summary), sequences={k: dict(v) for k, v in sorted(sequence_summary.items())},
        seedDiagnostics=dict(seed_diagnostics), partitionCount=len(set(partition_ids)),
        reviewedAnchorDiagnostics=dict(guard_diagnostics),
        artifacts={name: sha_bytes((output/name).read_bytes()) for name in ("metadata.json", "annotations.ndjson", "student-inputs.json")})
    write_json(output / "summary.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    seeds = parser.add_mutually_exclusive_group(required=True)
    seeds.add_argument("--seed-labels", type=Path)
    seeds.add_argument("--bootstrap-from-baseline", action="store_true")
    parser.add_argument("--baseline-replay-dir", type=Path)
    parser.add_argument("--reviewed-anchor-labels", type=Path,
        help="Optional bootstrap-only semantic guard: explicit reviewed paint within two flow-aligned pixels")
    parser.add_argument("--mode", choices=("retrospective", "causal"), default="retrospective")
    parser.add_argument("--horizon-seconds", type=float, default=0.5)
    args = parser.parse_args()
    try:
        report = run(args.replay_dir, args.output_dir, Config(mode=args.mode, horizon_seconds=args.horizon_seconds),
            args.seed_labels, args.bootstrap_from_baseline, args.baseline_replay_dir, args.reviewed_anchor_labels)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(dict(outputDir=str(args.output_dir.resolve()), **report), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
