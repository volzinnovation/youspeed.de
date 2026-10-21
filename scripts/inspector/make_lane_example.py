#!/usr/bin/env python3
"""Generate tiny synthetic videos, decoded PNGs and lane annotations for all splits."""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("lane_video", ROOT / "inspector/lane_video.py")
lane = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lane)
NOW = "2026-10-08T00:00:00.000Z"
POINTS = {"left": [[.15,.95],[.25,.75],[.35,.55],[.45,.35]],
          "right": [[.85,.95],[.75,.75],[.65,.55],[.55,.35]]}


def rasterize(frame, shade):
    width, height = 128, 72
    image = bytearray([shade] * width * height * 3)
    if frame < 2:
        for side, control in POINTS.items():
            for step in range(201):
                if side == "right" and (step // 20) % 2:
                    continue
                t, u = step / 200, 1 - step / 200
                x, y = [u**3*control[0][a] + 3*u*u*t*control[1][a] + 3*u*t*t*control[2][a] + t**3*control[3][a] for a in (0,1)]
                x, y = round((x + frame * .01) * (width-1)), round(y * (height-1))
                for row in range(max(0,y-1),min(height,y+2)):
                    for col in range(max(0,x-1),min(width,x+2)):
                        at = (row * width + col) * 3
                        image[at:at+3] = b"\xff\xff\xff"
    return b"P6\n128 72\n255\n" + image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tests/inspector/fixtures/lane-dataset-v1")
    output = parser.parse_args().output
    (output / "images").mkdir(parents=True, exist_ok=True)
    (output / "splits").mkdir(exist_ok=True)
    (output / "videos").mkdir(exist_ok=True)
    manifest = {"schema": "youspeed-lane-dataset-v1", "id": "synthetic-lane-example-v1",
                "coordinateConvention": "normalized_pixel_centres_top_left",
                "curveSemantics": "visible_lane_marking_path_including_dashed_gaps", "sources": [], "samples": []}
    decoder = lane.LaneVideos()
    try:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            for split, shade in (("train",55),("validation",65),("test",75)):
                for index in range(3):
                    (temp / f"{index}.ppm").write_bytes(rasterize(index, shade))
                video = output / "videos" / f"{split}.mp4"
                subprocess.run(["ffmpeg", "-v", "error", "-framerate", "25", "-i", str(temp / "%d.ppm"),
                                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(video)], check=True)
                data = video.read_bytes()
                loaded = decoder.upload(io.BytesIO(data), len(data), video.name)
                source = loaded["source"]
                source.update(groupId=f"synthetic-drive-{split}", split=split, sequenceId=source["id"])
                manifest["sources"].append(source)
                sample_ids = []
                for index in range(3):
                    sample_id = f"{source['id']}-{index}"
                    image = decoder.frame(loaded["session"], index)
                    path = f"images/{sample_id}.png"
                    (output / path).write_bytes(image)
                    curves = []
                    if index < 2:
                        for side in POINTS:
                            curves.append({"id":f"{split}-{side}-{index}", "trackId":f"track-{split}-{side}", "degree":3,
                                           "marking":"solid" if side == "left" else "dashed",
                                           "controlPoints":[[x+index*.01,y] for x,y in POINTS[side]],
                                           "copiedFrom":None if index == 0 else {"sampleId":sample_ids[0],"annotationId":f"{split}-{side}-0","revision":1}})
                    sample = {"id":sample_id,"sourceId":source["id"],"sequenceId":source["sequenceId"],
                              "frameIndex":index,"pts":source["frames"][index]["pts"],"timeSeconds":source["frames"][index]["timeSeconds"],
                              "width":source["width"],"height":source["height"],
                              "image":{"path":path,"sha256":hashlib.sha256(image).hexdigest(),"byteLength":len(image)},
                              "revision":1,"status":"draft" if index == 1 else "reviewed", "reviewedAt":None if index == 1 else NOW,
                              "updatedAt":NOW, "draftFrom":None if index != 1 else {"sampleId":sample_ids[0],"revision":1},"curves":curves}
                    manifest["samples"].append(sample); sample_ids.append(sample_id)
                (output / f"splits/{split}.json").write_text(json.dumps([sample_ids[0],sample_ids[2]],indent=2)+"\n")
                decoder.delete(loaded["session"])
    finally:
        decoder.close()
    (output / "manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(output)


if __name__ == "__main__":
    main()
