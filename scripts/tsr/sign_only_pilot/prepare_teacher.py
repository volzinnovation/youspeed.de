#!/usr/bin/env python3
"""Prepare original rasters and class-agnostic detector proposals on KI.

Original dataset files must be staged locally by the caller. This program never
accepts credentials or downloads private dataset files. Public model downloads
are pinned, unauthenticated, and SHA-256 verified. Every proposal requires review.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import time

from PIL import Image, ImageDraw, ImageFont


TEACHER = {
    "repo_id": "Panoramax/detect_face_plate_sign",
    "revision": "de311725ddae469c200cce0f86126fd4c043f24b",
    "filename": "yolo11l_panoramax.pt",
    "sha256": "a3205e4a92b3acdaa883c02e09dba439c48f6c5bc8c89aff44da7c2e79f140e7",
}
ARCHITECTURE = {
    "repo_id": "Ultralytics/YOLO26",
    "revision": "070ac3c51435984d992ba92eb3f234daf4e4500d",
    "filename": "yolo26n.pt",
    "sha256": "9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef",
}
D4 = {
    "repo_id": "loffenauer/streetshots",
    "revision": "32f7b519e91df05af24e3b1962aeefd864e033b7",
    "filename": "detector/d4/artifacts/d4.pt",
    "sha256": "f02bf99483c5ad2b79f254b1623b18593ed780c8f3c2df7051331633bb1a2a36",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    pending.replace(path)


def safe_id(value) -> str:
    value = str(value)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Unsafe picture ID")
    return value


def validate_manifest(document):
    if document.get("dataset_repo") != "loffenauer/streetshots":
        raise ValueError("Unexpected dataset repository")
    if not re.fullmatch(r"[0-9a-f]{40}", str(document.get("dataset_revision", ""))):
        raise ValueError("An immutable dataset commit is required")
    frames = document["frames"]
    if not frames:
        raise ValueError("Empty frame selection")
    ids = set()
    groups, original_hashes = {}, {}
    for row in frames:
        uid = safe_id(row["picture_id"])
        if uid in ids:
            raise ValueError(f"Duplicate picture ID: {uid}")
        ids.add(uid)
        if not row.get("split") or not row.get("group_id"):
            raise ValueError(f"Missing frozen split/group: {uid}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", ""))):
            raise ValueError(f"Missing original SHA-256: {uid}")
        for key, table in ((row["group_id"], groups), (row["sha256"], original_hashes)):
            if key in table and table[key] != row["split"]:
                raise ValueError(f"Group or original bytes cross frozen splits: {uid}")
            table[key] = row["split"]
        relative = PurePosixPath(row["hf_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Unsafe source path: {uid}")
        dims = row["dimensions"]
        if len(dims) != 2 or any(type(v) is not int or v <= 0 for v in dims):
            raise ValueError(f"Invalid dimensions: {uid}")
    # Neither this function nor mining changes split/group membership.
    return frames


def find_original(row, roots: list[Path]) -> Path:
    uid = safe_id(row["picture_id"])
    relative = Path(row["hf_path"])
    possible = [relative, Path(relative.name), Path(f"{uid}.jpg"),
                Path("images") / f"{uid}.jpg", Path("images") / relative.name]
    mismatches = []
    for root in roots:
        for name in possible:
            candidate = root / name
            if not candidate.is_file():
                continue
            if sha256(candidate) == row["sha256"]:
                return candidate.resolve()
            mismatches.append(str(candidate))
    raise ValueError(f"No staged original matches SHA-256 for {uid}; mismatching files: {mismatches}")


def canonicalize(source: Path, destination: Path, dimensions) -> dict:
    with Image.open(source) as image:
        if list(image.size) != list(dimensions):
            raise ValueError(f"Registered raster dimensions differ: {source.name}")
        orientation = image.getexif().get(274)
        # Coordinates refer to the registered raster, so do not EXIF-transpose.
        rgb = image.convert("RGB")
        canonical = Image.new("RGB", rgb.size)
        canonical.paste(rgb)
    pending = destination.with_suffix(".pending")
    canonical.save(pending, format="PNG", optimize=False)
    pending.replace(destination)
    pixel_hash = hashlib.sha256(canonical.tobytes()).hexdigest()
    with Image.open(destination) as check:
        if check.size != tuple(dimensions) or check.mode != "RGB" or check.getexif():
            raise ValueError("Canonical raster contract failed")
        if hashlib.sha256(check.tobytes()).hexdigest() != pixel_hash:
            raise ValueError("Canonical PNG changed RGB pixels")
    return {"path": str(destination.resolve()), "sha256": sha256(destination),
            "rgb_sha256": pixel_hash, "dimensions": list(dimensions),
            "original_exif_orientation": orientation,
            "transform": "registered raster; RGB conversion; no EXIF transpose; no resize; no EXIF/ICC copied"}


def model_file(spec, directory: Path) -> Path:
    local = directory / spec["filename"]
    if local.is_file():
        if sha256(local) != spec["sha256"]:
            raise ValueError(f"Unexpected existing model bytes: {local.name}")
        return local
    from huggingface_hub import hf_hub_download
    path = Path(hf_hub_download(repo_id=spec["repo_id"], revision=spec["revision"],
                               filename=spec["filename"], local_dir=directory, token=False))
    if sha256(path) != spec["sha256"]:
        raise ValueError(f"Downloaded model SHA mismatch: {path.name}")
    return path


def sign_index(names) -> int:
    entries = names.items() if isinstance(names, dict) else enumerate(names)
    matches = [int(key) for key, value in entries if str(value).strip().lower() == "sign"]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one 'sign' output, received {names}")
    return matches[0]


def load_models(directory: Path, d4_path: Path, device: int):
    import torch
    import ultralytics
    from ultralytics import YOLO
    from ultralytics.nn.tasks import DetectionModel
    if ultralytics.__version__ != "8.4.56":
        raise ValueError(f"Expected Ultralytics 8.4.56, received {ultralytics.__version__}")
    if not torch.cuda.is_available():
        raise ValueError("CUDA is required for the KI mining run")
    if sha256(d4_path) != D4["sha256"]:
        raise ValueError("Unexpected d4 checkpoint")
    teacher_path = model_file(TEACHER, directory)
    architecture_path = model_file(ARCHITECTURE, directory)
    teacher = YOLO(str(teacher_path))
    student = YOLO(str(architecture_path))
    architecture = deepcopy(student.model.yaml)
    architecture["end2end"] = False
    restored = DetectionModel(architecture, nc=1, verbose=False)
    restored.end2end = False
    restored.names = {0: "sign"}
    state = torch.load(d4_path, map_location="cpu", weights_only=True)
    restored.load_state_dict(state["model"], strict=True)
    restored.eval()
    student.model = restored
    student.task = "detect"
    student.overrides = {"task": "detect", "imgsz": 1024, "end2end": False}
    student.predictor = None
    models = {"teacher": teacher, "d4": student}
    channels = {key: sign_index(model.names) for key, model in models.items()}
    info = {"teacher": {**TEACHER, "path": str(teacher_path.resolve()), "names": teacher.names},
            "architecture": {**ARCHITECTURE, "path": str(architecture_path.resolve())},
            "d4": {**D4, "path": str(d4_path.resolve()), "names": restored.names, "end2end": False},
            "environment": {"torch": torch.__version__, "ultralytics": ultralytics.__version__,
                            "cuda": torch.version.cuda, "device": device,
                            "device_name": torch.cuda.get_device_name(device)},
            "sign_channels": channels}
    return models, channels, info


def checked_box(values, dimensions):
    if len(values) != 4 or any(isinstance(v, bool) or not isinstance(v, (float, int))
                             or not math.isfinite(v) for v in values):
        raise ValueError("Invalid proposal box")
    width, height = dimensions
    x1, y1, x2, y2 = map(float, values)
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError(f"Proposal box outside registered raster: {values}")
    return [x1, y1, x2, y2]


def iou(left, right) -> float:
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    overlap = max(0., x2-x1) * max(0., y2-y1)
    union = (left[2]-left[0])*(left[3]-left[1]) + (right[2]-right[0])*(right[3]-right[1]) - overlap
    return overlap/union if union > 0 else 0.


def axis_starts(length: int, tile: int, overlap: float):
    if length <= tile:
        return [0]
    stride = max(1, int(round(tile * (1-overlap))))
    return sorted(set([*range(0, length-tile+1, stride), length-tile]))


def tile_views(size, tile=1536, overlap=.25):
    width, height = size
    return [(x, y, min(x+tile, width), min(y+tile, height))
            for y in axis_starts(height, tile, overlap)
            for x in axis_starts(width, tile, overlap)]


def infer(model, image, channel, *, source, view_id, offset, input_size,
          confidence, nms_iou, max_det, device, dimensions):
    import torch
    torch.cuda.synchronize(device)
    start = time.monotonic()
    result = model.predict(source=image, imgsz=input_size, batch=1, device=device,
                           conf=confidence, iou=nms_iou, classes=[channel], max_det=max_det,
                           half=True, rect=False, verbose=False, save=False)
    torch.cuda.synchronize(device)
    elapsed = time.monotonic()-start
    if len(result) != 1:
        raise ValueError("Expected a single-frame inference result")
    boxes = result[0].boxes
    rows = []
    if boxes is not None:
        for index, (box, score) in enumerate(zip(boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist())):
            x1, y1, x2, y2 = box
            mapped = [min(max(x1+offset[0], 0), dimensions[0]),
                      min(max(y1+offset[1], 0), dimensions[1]),
                      min(max(x2+offset[0], 0), dimensions[0]),
                      min(max(y2+offset[1], 0), dimensions[1])]
            rows.append({"observation_id": f"{source}:{view_id}:{index+1:04d}",
                         "source": source, "view_id": view_id, "score": float(score),
                         "box_xyxy": checked_box(mapped, dimensions), "input_size": input_size})
    return rows, {"source": source, "view_id": view_id, "input_size": input_size,
                  "view_dimensions": list(image.size), "offset_xy": list(offset),
                  "wall_seconds_including_prepost": elapsed,
                  "proposal_count": len(rows), "max_det_reached": len(rows) >= max_det,
                  "ultralytics_speed_ms": result[0].speed}


def nms_groups(observations, threshold):
    """Merge same-teacher views by score; retain every suppressed observation."""
    groups = []
    for observation in sorted(observations, key=lambda row: (-row["score"], row["observation_id"])):
        match = next((g for g in groups if iou(g["box_xyxy"], observation["box_xyxy"]) >= threshold), None)
        if match is None:
            groups.append({"box_xyxy": observation["box_xyxy"], "representative_source": observation["source"],
                           "observations": [observation]})
        else:
            match["observations"].append(observation)
    return groups


def source_annotations(row):
    result = []
    for index, item in enumerate(row.get("source_annotations") or []):
        if item.get("label", "sign") != "sign":
            continue
        raw_box = item.get("box_xyxy", item.get("bbox_xyxy"))
        if raw_box is None:
            raise ValueError("Source annotation is missing pixel box")
        result.append({"observation_id": f"hf:{item.get('annotation_id') or index}",
                       "source": "hf_annotation", "annotation_id": item.get("annotation_id"),
                       "label_origin": item.get("label_origin"),
                       "score": None, "box_xyxy": checked_box(raw_box, row["dimensions"])})
    return result


def review_groups(old, teacher, d4, threshold):
    """Create review clusters, not training labels or cross-model confidence."""
    groups = []
    incoming = [{"box_xyxy": row["box_xyxy"], "representative_source": "hf_annotation", "observations": [row]}
                for row in old] + teacher + d4
    for candidate in incoming:
        eligible = [(iou(group["box_xyxy"], candidate["box_xyxy"]), group) for group in groups]
        best = max(eligible, key=lambda pair: pair[0], default=(0, None))
        if best[0] >= threshold:
            best[1]["observations"].extend(candidate["observations"])
        else:
            groups.append(deepcopy(candidate))
    for index, group in enumerate(groups, 1):
        group["proposal_id"] = f"p{index:04d}"
        group["review_status"] = "unreviewed"
        group["sources"] = sorted({row["source"] for row in group["observations"]})
        group["all_three_sources_agree"] = set(group["sources"]) == {"hf_annotation", "teacher", "d4"}
    return groups


def font(size=18):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_review(image, record, directory: Path, long_edge=1600):
    directory.mkdir(parents=True, exist_ok=True)
    width, height = image.size
    scale = min(1., long_edge/max(width, height))
    preview = image.resize((round(width*scale), round(height*scale)), Image.Resampling.LANCZOS)
    preview.save(directory/"clean.jpg", quality=92, subsampling=0)
    native_tiles = []
    for index, region in enumerate(tile_views(image.size, tile=1536, overlap=.25)):
        tile_path = directory/f"clean-native-{index:03d}.jpg"
        tile = image.crop(region)
        tile.save(tile_path, quality=94, subsampling=0)
        native_tiles.append({"path": str(tile_path.resolve()), "sha256": sha256(tile_path),
                             "source_region_xyxy": list(region), "offset_xy": list(region[:2]),
                             "dimensions": list(tile.size), "pixel_scale": 1,
                             "encoding": "JPEG quality94 chroma444; canonical PNG retained separately"})
    overlay = preview.copy()
    draw = ImageDraw.Draw(overlay)
    label_font = font(18)
    for proposal in record["proposals"]:
        box = [round(v*scale) for v in proposal["box_xyxy"]]
        color = (255, 203, 46) if "hf_annotation" in proposal["sources"] else (45, 235, 200)
        draw.rectangle(box, outline=color, width=2)
        text = proposal["proposal_id"]
        extent = draw.textbbox((box[0], box[1]), text, font=label_font)
        draw.rectangle(extent, fill=(10, 10, 10))
        draw.text((box[0], box[1]), text, fill=color, font=label_font)
    overlay.save(directory/"proposals.jpg", quality=93, subsampling=0)
    # Preserve all native (or exactly 2x) crops. Paginate contact sheets, so no
    # tiny object is reduced to fit a fixed contact-sheet cell.
    sheet_width, sheet_height = 1800, 1800
    sheet = Image.new("RGB", (sheet_width, sheet_height), (238, 238, 238))
    page, x, y, row_height, used = 1, 12, 12, 0, False
    contact_paths, crop_records = [], []

    def save_sheet():
        path = directory/f"crops-{page:03d}.jpg"
        sheet.save(path, quality=93, subsampling=0)
        contact_paths.append(str(path.resolve()))

    for proposal in record["proposals"]:
        box = proposal["box_xyxy"]
        region = (max(0, math.floor(box[0])-8), max(0, math.floor(box[1])-8),
                  min(width, math.ceil(box[2])+8), min(height, math.ceil(box[3])+8))
        crop = image.crop(region)
        enlargement = 2 if max(crop.size) <= 256 else 1
        if enlargement == 2:
            crop = crop.resize((crop.width*2, crop.height*2), Image.Resampling.NEAREST)
        path = directory/f"{proposal['proposal_id']}-crop.png"
        crop.save(path)
        crop_records.append({"proposal_id": proposal["proposal_id"], "path": str(path.resolve()),
                             "source_region_xyxy": list(region), "display_scale": enlargement})
        tile_width, tile_height = crop.width+16, crop.height+42
        if tile_width > sheet_width-24 or tile_height > sheet_height-24:
            # Give large proposals their own native-scale contact page.
            large = Image.new("RGB", (tile_width, tile_height), (238, 238, 238))
            ImageDraw.Draw(large).text((4, 2), f"{proposal['proposal_id']}  {enlargement}x", font=label_font, fill="black")
            large.paste(crop, (4, 30))
            large_path = directory/f"crops-large-{proposal['proposal_id']}.jpg"
            large.save(large_path, quality=93, subsampling=0)
            contact_paths.append(str(large_path.resolve()))
            continue
        if x+tile_width > sheet_width-12:
            x, y, row_height = 12, y+row_height+12, 0
        if y+tile_height > sheet_height-12:
            if used:
                save_sheet()
            page += 1
            sheet = Image.new("RGB", (sheet_width, sheet_height), (238, 238, 238))
            x, y, row_height, used = 12, 12, 0, False
        ImageDraw.Draw(sheet).text((x+4, y+2), f"{proposal['proposal_id']}  {enlargement}x", font=label_font, fill="black")
        sheet.paste(crop, (x+4, y+30))
        x += tile_width+12
        row_height = max(row_height, tile_height)
        used = True
    if used:
        save_sheet()
    info = {"picture_id": record["picture_id"], "split": record["split"], "group_id": record["group_id"],
            "mapillary_candidate_count": record.get("mapillary_candidate_count"),
            "proposal_count": len(record["proposals"]), "review_required": True,
            "source_raster_dimensions": [width, height],
            "review_instructions": "Inspect the clean overview and every native clean tile, then all proposal crops/overlays. Add missing signs and correct/remove proposed boxes. Report boxes in original raster pixels: tile coordinates plus offset_xy. Unresolved sign-like objects require incomplete/excluded status pending adjudication. No proposal is preaccepted.",
            "clean": str((directory/"clean.jpg").resolve()),
            "clean_native_tiles": native_tiles,
            "overlay": str((directory/"proposals.jpg").resolve()),
            "contact_sheets": contact_paths, "crops": crop_records}
    write_json(directory/"review.json", info)
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--reuse-image-dir", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models-directory", type=Path)
    parser.add_argument("--d4-checkpoint", type=Path, required=True)
    parser.add_argument("--device", type=int, default=0, choices=[0])
    parser.add_argument("--confidence", type=float, default=.10)
    parser.add_argument("--nms-iou", type=float, default=.50)
    parser.add_argument("--tile-size", type=int, default=1536)
    parser.add_argument("--tile-overlap", type=float, default=.25)
    parser.add_argument("--max-det", type=int, default=1000)
    parser.add_argument("--prepare-only", action="store_true", help="Verify staged bytes and canonicalize, without downloading/loading models")
    args = parser.parse_args()
    if not 0 < args.confidence < 1 or not 0 < args.nms_iou < 1 or not 0 <= args.tile_overlap < 1:
        parser.error("Invalid confidence, IoU or overlap")
    if args.tile_size < 32 or args.tile_size % 32 or args.max_det < 1:
        parser.error("Tile size must be a positive multiple of32 and max-det positive")
    document = json.loads(args.selection.read_text())
    frames = validate_manifest(document)
    args.output.mkdir(parents=True, exist_ok=True)
    raster_dir, review_dir = args.output/"canonical", args.output/"review"
    raster_dir.mkdir(exist_ok=True)
    review_dir.mkdir(exist_ok=True)
    selection_sha = sha256(args.selection)
    config = {"teacher_full_input": 2048, "teacher_tile_input": args.tile_size,
              "tile_overlap": args.tile_overlap, "d4_full_input": 1024,
              "confidence": args.confidence, "nms_iou": args.nms_iou, "max_det_per_view": args.max_det,
              "batch": 1, "device": args.device, "half": True,
              "representative_policy": "HF box first, then teacher NMS, then d4; grouping is for review only, no averaged confidence or autoacceptance"}
    model_info = None
    models = channels = None
    if not args.prepare_only:
        directory = args.models_directory or args.output/"models"
        directory.mkdir(parents=True, exist_ok=True)
        models, channels, model_info = load_models(directory, args.d4_checkpoint, args.device)
        write_json(args.output/"known-models.json", model_info)
    prepared = {"format": "streetshots.sign-only-pilot.prepared.v1", "dataset_repo": document["dataset_repo"],
                "dataset_revision": document["dataset_revision"], "selection_sha256": selection_sha,
                "selection_seed": document.get("selection_seed"), "script_sha256": sha256(Path(__file__)),
                "mining_config": config, "models": model_info, "frames": [], "completed": False,
                "notes": ["Mapillary is used as class-blind review metadata only, never as a pixel label.",
                          "Original annotations and all detector predictions are proposals, not accepted training labels.",
                          "No private dataset downloads or credentials are supported by this program."]}
    start = time.monotonic()
    pixel_splits = {}
    for index, row in enumerate(frames, 1):
        uid = safe_id(row["picture_id"])
        original = find_original(row, [args.originals, *args.reuse_image_dir])
        canonical = canonicalize(original, raster_dir/f"{uid}.png", row["dimensions"])
        if canonical["rgb_sha256"] in pixel_splits and pixel_splits[canonical["rgb_sha256"]] != row["split"]:
            raise ValueError(f"Canonical pixels cross frozen splits: {uid}")
        pixel_splits[canonical["rgb_sha256"]] = row["split"]
        record = {key: row.get(key) for key in ("picture_id", "sample_id", "split", "group_id", "hf_path",
                  "coordinates", "sequence_ids", "mapillary_candidate_count", "mapillary_cone_eligible",
                  "selection_reason", "review_status", "prefill_boxes", "existing_truth_boxes", "existing_truth_complete")}
        record.update({"original": {"path": str(original), "sha256": row["sha256"], "dimensions": row["dimensions"]},
                       "canonical": canonical, "dimensions": row["dimensions"], "proposals": [], "timings": []})
        old = source_annotations(row)
        if not args.prepare_only:
            import torch
            torch.cuda.reset_peak_memory_stats(args.device)
            with Image.open(canonical["path"]) as source:
                image = source.convert("RGB")
            teacher_raw, timing = infer(models["teacher"], image, channels["teacher"], source="teacher", view_id="full2048",
                offset=(0,0), input_size=2048, confidence=args.confidence, nms_iou=args.nms_iou, max_det=args.max_det,
                device=args.device, dimensions=image.size)
            record["timings"].append(timing)
            for tile_index, region in enumerate(tile_views(image.size, args.tile_size, args.tile_overlap)):
                predictions, timing = infer(models["teacher"], image.crop(region), channels["teacher"], source="teacher",
                    view_id=f"tile{tile_index:03d}", offset=region[:2], input_size=args.tile_size,
                    confidence=args.confidence, nms_iou=args.nms_iou, max_det=args.max_det, device=args.device, dimensions=image.size)
                timing["source_region_xyxy"] = list(region)
                record["timings"].append(timing)
                teacher_raw.extend(predictions)
            d4_raw, timing = infer(models["d4"], image, channels["d4"], source="d4", view_id="full1024",
                offset=(0,0), input_size=1024, confidence=args.confidence, nms_iou=args.nms_iou, max_det=args.max_det,
                device=args.device, dimensions=image.size)
            record["timings"].append(timing)
            record["peak_cuda_allocated_bytes"] = torch.cuda.max_memory_allocated(args.device)
            record["peak_cuda_reserved_bytes"] = torch.cuda.max_memory_reserved(args.device)
            record["raw_observations"] = old + teacher_raw + d4_raw
            record["proposals"] = review_groups(old, nms_groups(teacher_raw, args.nms_iou), nms_groups(d4_raw, args.nms_iou), args.nms_iou)
            record["review_pack"] = render_review(image, record, review_dir/uid)
            record["mining_complete"] = not any(t["max_det_reached"] for t in record["timings"])
        else:
            record["raw_observations"] = old
            record["proposals"] = review_groups(old, [], [], args.nms_iou)
            record["mining_complete"] = False
        prepared["frames"].append(record)
        write_json(args.output/f"frame-{uid}.json", record)
        write_json(args.output/"prepared.json", prepared)
        print(json.dumps({"progress": [index, len(frames)], "picture_id": uid,
                          "proposal_count": len(record["proposals"]), "mining_complete": record["mining_complete"]}), flush=True)
    prepared["completed"] = True
    prepared["mining_complete"] = not args.prepare_only and all(row["mining_complete"] for row in prepared["frames"])
    prepared["elapsed_seconds"] = time.monotonic()-start
    write_json(args.output/"prepared.json", prepared)
    print(json.dumps({"completed": True, "mining_complete": prepared["mining_complete"], "frames": len(frames),
                      "elapsed_seconds": prepared["elapsed_seconds"], "prepared_sha256": sha256(args.output/"prepared.json")}), flush=True)


if __name__ == "__main__":
    main()
