#!/usr/bin/env python3
"""Check YOLO26's default end-to-end head on the same frozen video keyframes.

Run after the full paired replay to avoid competing with its CPU timings. This
is a quality comparison on the reviewed frames, not a full end-to-end replay.
"""
import argparse
import json
import time
from pathlib import Path

from compare_sgblur_detectors import CHECKPOINTS
from evaluate_sgblur_dashcam import aggregate, evaluate, score_frame, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--freeze-receipt", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--replay", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a new evidence output")
    paired = evaluate(args.labels, args.freeze_receipt, args.replay, args.plan)
    if sha(args.candidate) != CHECKPOINTS["yolo26s"]:
        raise ValueError("Candidate checkpoint changed")
    import cv2
    import numpy as np
    import torch
    from ultralytics import YOLO
    torch.set_num_threads(4)
    model = YOLO(args.candidate)
    assert model.names == {0: "sign", 1: "plate", 2: "face"}
    model.model.end2end = True
    settings = paired["replay_metadata"]["configuration"]
    for _ in range(3):
        model.predict(np.full((1024, 1024, 3), 114, np.uint8), **settings)
    labels = json.loads(args.labels.read_text())
    source = {f["frame_id"]: f for f in json.loads((args.replay / "blind-frames.json").read_text())["frames"]}
    rows = []
    for label in labels["frames"]:
        image_path = Path(source[label["frame_id"]]["image_path"])
        if sha(image_path) != label["image_sha256"]:
            raise ValueError("Frozen source image changed")
        window = cv2.imread(str(image_path))
        started = time.perf_counter()
        result = model.predict(window, **settings)[0]
        elapsed = (time.perf_counter() - started) * 1000
        boxes = result.boxes.data.cpu().tolist()
        rows.append({"frame_id": label["frame_id"], "movie_id": label["movie_id"],
                     "window_rgb_sha256": label["window_rgb_sha256"],
                     "boxes_xyxy_score_class": boxes, "predict_wall_ms": elapsed,
                     "scores": {str(t): score_frame(label, boxes, t, settings["conf"])
                                for t in (.5, .3)}})
    output = {"schema_version": 1, "purpose": "Default end-to-end head quality on 65 frozen keyframes only",
              "candidate_sha256": CHECKPOINTS["yolo26s"], "script_sha256": sha(Path(__file__)),
              "annotation_sha256": paired["annotation_sha256"], "end2end": True,
              "configuration": settings, "frames": rows,
              "scores": {str(t): aggregate([r["scores"][str(t)] for r in rows]) for t in (.5, .3)},
              "by_movie": {m: aggregate([r["scores"]["0.5"] for r in rows if r["movie_id"] == m])
                           for m in sorted({r["movie_id"] for r in rows})},
              "paired_one_to_many_scores": paired["scores"]["0.5"]["overall"],
              "timing_scope": "65 keyframes in a separate run; not directly comparable to full replay latency"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, allow_nan=False) + "\n")
    print(json.dumps(output["scores"], indent=2))


if __name__ == "__main__":
    main()
