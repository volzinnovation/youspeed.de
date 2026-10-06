#!/usr/bin/env python3
"""Read-only inspector verification of uploaded archive replay plans and pixels."""
import argparse
import concurrent.futures
import hashlib
import json
import urllib.request
from pathlib import Path


def verify(root, base, source, result):
    directory = root / source[:16]
    plan = json.loads((directory / "upload-plan.json").read_text())
    expected = {}
    expected_events = set()
    for request in plan["requests"]:
        if request["endpoint"] == "capture-sightings":
            body = (directory / request["file"]).read_bytes()
            assert hashlib.sha256(body).hexdigest() == request["sha256"]
            expected_events.update(event["event_id"] for event in json.loads(body)["events"])
        if request["endpoint"] != "capture-crops":
            continue
        body = (directory / request["file"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == request["sha256"]
        length = int.from_bytes(body[:4], "big")
        manifest = json.loads(body[4:4 + length])
        expected[manifest["crop_id"]] = manifest
    assert len(expected_events) == plan["observation_count"]
    crop_sightings = {value["observation_id"] for value in expected.values()}
    assert crop_sightings <= expected_events
    rows = []
    while True:
        url = f"{base}/inspector/api/crops?installation={plan['installation_id']}&limit=100&offset={len(rows)}"
        with urllib.request.urlopen(url, timeout=30) as response:
            page = json.load(response)
        rows.extend(page["crops"])
        if not page["has_more"]:
            break
        assert page["crops"], "Pagination made no progress"
    for row in rows:
        assert row["crop_id"] in expected
        assert row["manifest"] == expected[row["crop_id"]]
        assert row["observation"]["event_id"] == row["manifest"]["observation_id"]
        assert row["digest"] == expected[row["crop_id"]]["encoded_sha256"]
        assert row["manifest"]["local_frame_token"].startswith("hf-replay:" + source + ":")
        flags = row["observation"]["evidence"]["quality_flags"]
        assert "hf_archive_replay" in flags and "model_country_assumed" in flags
        assert "recording_source_" + result["recording_platform"] in flags
        assert row["observation"]["vehicle_position"] is None
        assert row["observation"]["app"]["build"] == "dashcam-replay"
    checked = []
    for row in rows[:1]:
        with urllib.request.urlopen(base + row["image_url"], timeout=30) as response:
            image = response.read()
        assert len(image) == row["manifest"]["byte_length"]
        assert hashlib.sha256(image).hexdigest() == row["digest"]
        checked.append(row["crop_id"])
    value = dict(source_sha256=source, installation_id=plan["installation_id"],
                 expected=len(expected), imported=len(rows),
                 complete=len(rows) == len(expected) and set(expected) == {row["crop_id"] for row in rows},
                 linked_sightings=len({row["manifest"]["observation_id"] for row in rows}),
                 expected_crop_sightings=len(crop_sightings),
                 expected_sightings=plan["observation_count"], manifest_match=True,
                 image_byte_hash_checks=checked)
    (directory / "inspector-verification.json").write_text(json.dumps(value, indent=2) + "\n")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--base", default="http://localhost:18080")
    args = parser.parse_args()
    results = json.loads((args.root / "results.json").read_text())
    for name in ("extra-results.json", "parallel-results.json", "retry-results.json"):
        extra = args.root / name
        if extra.exists():
            results.update(json.loads(extra.read_text()))
    uploaded = [(source, result) for source, result in results.items() if result["state"] == "uploaded"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        checks = list(pool.map(lambda item: verify(args.root, args.base.rstrip("/"), *item), uploaded))
    value = dict(recordings_checked=len(checks), expected_crops=sum(v["expected"] for v in checks),
                 imported_crops=sum(v["imported"] for v in checks),
                 complete=all(v["complete"] and v["linked_sightings"] == v["expected_crop_sightings"] for v in checks),
                 checks=checks)
    (args.root / "inspector-verification.json").write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps({k: v for k, v in value.items() if k != "checks"}))
    if not value["complete"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
