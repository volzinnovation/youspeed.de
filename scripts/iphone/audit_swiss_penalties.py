#!/usr/bin/env python3
"""Audit actual simulator country selection and penalty output; no legal approval.

Run against a built Debug app. Synthetic Zürich GPS and road/speed inputs enter
the normal country selector/reference/resolver. Original pixels are preserved.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

BUNDLE = "de.youspeed.SpeedConsumer"
CASES = [(50, 5, True), (80, 10, False), (120, 10, False),
         (120, 32, False), (30, 40, True), (80, 60, False), (120, 80, False)]


def sim(*args, **kwargs):
    return subprocess.run(["xcrun", "simctl", *args], check=True,
                          capture_output=True, text=True, **kwargs).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sim("install", args.device, str(args.app))
    sim("privacy", args.device, "grant", "location", BUNDLE)
    container = Path(sim("get_app_container", args.device, BUNDLE, "data"))
    report_path = container / "Documents/country-review.json"
    reports = []
    try:
        for index, (limit, delta, urban) in enumerate(CASES):
            subprocess.run(["xcrun", "simctl", "terminate", args.device, BUNDLE], capture_output=True)
            report_path.unlink(missing_ok=True)
            env = dict(os.environ, SIMCTL_CHILD_YOUSPEED_SCREENSHOT_STATE="country-penalty",
                       SIMCTL_CHILD_YOUSPEED_SCREENSHOT_COUNTRY="CH",
                       SIMCTL_CHILD_YOUSPEED_SCREENSHOT_DELTA=str(delta),
                       SIMCTL_CHILD_YOUSPEED_SCREENSHOT_LIMIT=str(limit),
                       SIMCTL_CHILD_YOUSPEED_SCREENSHOT_HIGHWAY=["residential", "primary", "motorway", "motorway", "residential", "primary", "motorway"][index],
                       SIMCTL_CHILD_YOUSPEED_SCREENSHOT_INSIDE_CITY="1" if urban else "0")
            sim("launch", args.device, BUNDLE, "-AppleLanguages", "(en)", env=env)
            deadline = time.monotonic() + 20
            while not report_path.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            report = json.loads(report_path.read_text())
            assert report["country"] == "CHE" and report["country_resolved"], report
            assert report["rules_file"] == "CHE-rules.json" and report["penalty_present"], report
            assert report["money_fine_eur"] == [40, 100, 60, None, None, None, None][index], report
            assert report["driving_ban_months"] == [None, None, None, 1, 24, 24, 24][index], report
            assert report["advisory_caption"], report
            time.sleep(0.8)
            sim("io", args.device, "screenshot", str(args.output / f"case-{index}.png"))
            reports.append(report)
        (args.output / "report.json").write_text(json.dumps(reports, indent=2) + "\n")
        print(json.dumps({"cases": len(reports), "country": "CHE",
                          "rules_sha256": hashlib.sha256((args.app / "CHE-rules.json").read_bytes()).hexdigest()}))
    finally:
        subprocess.run(["xcrun", "simctl", "terminate", args.device, BUNDLE], capture_output=True)


if __name__ == "__main__":
    main()
