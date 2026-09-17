#!/usr/bin/env python3
"""Select and download a non-overlapping batch from a Swiss Panoramax catalog."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import threading


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offset", type=int, required=True)
    parser.add_argument("--max-images", type=int, default=10000)
    parser.add_argument("--frame-stride", type=int, default=10)
    parser.add_argument("--distance-stride-m", type=float, default=25)
    parser.add_argument("--max-image-bytes", type=int, default=12 * 1024 * 1024)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    if args.offset < 0 or args.max_images <= 0:
        parser.error("offset must be non-negative and max-images must be positive")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from crawl_ch_panoramax import deduplicate, download

    source = args.source_run / "catalog.jsonl"
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = deduplicate(rows, args.frame_stride, args.distance_stride_m)
    batch = selected[args.offset : args.offset + args.max_images]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "download-queue.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in batch) + "\n",
        encoding="utf-8",
    )
    downloaded = 0
    failures: list[dict[str, str | None]] = []
    import requests

    if args.workers <= 0:
        parser.error("workers must be positive")
    thread_state = threading.local()

    def download_one(row: dict[str, object]) -> tuple[dict[str, object], bool, str | None]:
        session = getattr(thread_state, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": "youspeed-ch-tsr-panoramax-research/1.0"})
            thread_state.session = session
        ok, error = download(session, row, args.output / "images" / f"{row['id']}.jpg", args.max_image_bytes)
        return row, ok, error

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for row, ok, error in executor.map(download_one, batch):
            if ok:
                downloaded += 1
            else:
                failures.append({"picture_id": str(row["id"]), "error": error})
    if failures:
        (args.output / "download-errors.jsonl").write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in failures) + "\n",
            encoding="utf-8",
        )
    summary = {
        "source_catalog": str(source),
        "source_deduplicated_count": len(selected),
        "offset": args.offset,
        "requested_images": args.max_images,
        "selected_images": len(batch),
        "downloaded_images": downloaded,
        "download_failures": len(failures),
        "workers": args.workers,
        "deduplication": {"frame_stride": args.frame_stride, "distance_stride_m": args.distance_stride_m},
        "license_policy": "Only public CC-BY-SA-4.0 features and HTTPS derivatives; no Panoramax writes.",
    }
    (args.output / "batch-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
