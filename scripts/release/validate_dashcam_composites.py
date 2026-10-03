#!/usr/bin/env python3
"""Verify the final Dashcam artwork against an independently retained baseline.

Requires Pillow and NumPy. This checks actual output pixels, native UI
preservation, source/output hashes and mirrors; it does not contact a store.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pixels(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.array(image.convert("RGB"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-hashes", type=Path, required=True)
    parser.add_argument("--before-images", type=Path, required=True)
    parser.add_argument("--native-composites", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    baseline = json.loads(args.before_hashes.read_text())
    config = json.loads((ROOT / "store/artwork/dashcam-preview.json").read_text())
    layouts = json.loads((ROOT / "store/artwork/screenshot-layouts.json").read_text())["images"]
    errors, records = [], []
    expected_changes = set()
    for relative, layout in layouts.items():
        composite = layout.get("composite")
        if not composite:
            continue
        target = relative.split("/")[1]
        locale = relative.split("/")[3]
        geometry = config["platforms"][target]
        output, source = ROOT / relative, ROOT / layout["source"]
        before_image = args.before_images / relative
        native_composite = args.native_composites / target / f"{locale}.png"
        expected_changes.add(relative)
        if target == "android":
            mirror = ROOT / "fastlane/metadata/android" / locale / "images/phoneScreenshots/02-dashcam.png"
            expected_changes.add(str(mirror.relative_to(ROOT)))
            if output.read_bytes() != mirror.read_bytes():
                errors.append(f"{relative}: Fastlane mirror differs")
        if digest(output) != layout["output_sha256"] or digest(source) != layout["source_sha256"]:
            errors.append(f"{relative}: retained source/output provenance mismatch")
        if digest(native_composite) != composite["composed_native_sha256"]:
            errors.append(f"{relative}: composed-native provenance mismatch")
        old, new = pixels(before_image), pixels(output)
        native, composed = pixels(source), pixels(native_composite)
        if old.shape != new.shape or native.shape != composed.shape:
            errors.append(f"{relative}: image dimensions changed")
            continue
        diff = np.any(old != new, axis=2)
        native_diff = np.any(native != composed, axis=2)
        left, top, width, height = geometry["viewport"]
        placement = composite["native_placement"]
        bounds = [math.floor(placement["x"] + left * placement["width"] / native.shape[1]),
                  math.floor(placement["y"] + top * placement["height"] / native.shape[0]),
                  math.ceil(placement["x"] + (left + width) * placement["width"] / native.shape[1]),
                  math.ceil(placement["y"] + (top + height) * placement["height"] / native.shape[0])]
        if bounds != composite["rendered_viewport_bounds"]:
            errors.append(f"{relative}: rendered viewport mapping differs")
        outside = diff.copy()
        outside[bounds[1]:bounds[3], bounds[0]:bounds[2]] = False
        native_outside = native_diff.copy()
        native_outside[top:top + height, left:left + width] = False
        changed_ui = native_diff & np.any(native != 0, axis=2)
        protected_changed = 0
        for x, y, w, h in geometry.get("protected_capsules", {}).get(locale, []):
            ys, xs = np.mgrid[y:y+h, x:x+w]
            radius = h / 2
            cx = np.clip(xs + 0.5, x + radius, x + w - radius)
            cy = np.clip(ys + 0.5, y + radius, y + h - radius)
            capsule = (xs + 0.5-cx)**2 + (ys + 0.5-cy)**2 <= radius**2
            protected_changed += int(np.count_nonzero(native_diff[y:y+h, x:x+w] & capsule))
        checks = {"final_pixels_changed_outside_mapped_preview": int(np.count_nonzero(outside)),
                  "native_pixels_changed_outside_preview": int(np.count_nonzero(native_outside)),
                  "native_nonblack_ui_pixels_changed": int(np.count_nonzero(changed_ui)),
                  "native_caption_capsule_pixels_changed": protected_changed}
        if any(checks.values()):
            errors.append(f"{relative}: UI/preview preservation invariant failed {checks}")
        with Image.open(output) as image:
            if image.mode != "RGB" or image.size != ((1320, 2868) if target == "apple" else (1920, 1080)):
                errors.append(f"{relative}: unexpected output mode/dimensions")
        ys, xs = np.where(diff)
        records.append({"path": relative, "sha256": digest(output), "source": layout["source"],
                        "before_sha256": digest(before_image), "mapped_preview_bounds": bounds,
                        "changed_pixel_bounds": [int(xs.min()), int(ys.min()), int(xs.max()+1), int(ys.max()+1)],
                        "changed_pixels": int(diff.sum()), **checks})
    changed = {relative for relative, sha in baseline.items() if digest(ROOT / relative) != sha}
    if changed != expected_changes:
        errors.append(f"Unexpected scope of image changes: {sorted(changed ^ expected_changes)}")
    if digest(ROOT / config["frame"]["path"]) != config["frame"]["sha256"]:
        errors.append("Genuine source frame hash differs")
    report = {"format": "youspeed.dashcam-composite-validation.v1", "date": "2026-10-03",
              "status": "passed" if not errors else "failed", "errors": errors,
              "baseline_files_checked": len(baseline), "changed_files": sorted(changed),
              "source_frame": config["frame"], "composites": records,
              "before_hashes": str(args.before_hashes), "before_images": str(args.before_images),
              "native_composites": str(args.native_composites)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Checked {len(records)} composites and {len(baseline)} baseline image hashes; {len(errors)} errors")
    for error in errors:
        print(error)
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
