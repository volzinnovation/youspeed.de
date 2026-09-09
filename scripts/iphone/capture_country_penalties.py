#!/usr/bin/env python3
"""Capture original simulator pixels for every national penalty band.

Build SpeedConsumer first. The app replays a country GPS fix through its normal
selector and resolves its real bundled rules; its JSON report supplies expected
penalty values. No image editing or store screenshot replacement is performed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ID = "de.youspeed.SpeedConsumer"
MATRIX = [("FR", "FRA", "fr", "fr_FR"), ("NL", "NLD", "nl", "nl_NL"),
          ("BE", "BEL", "nl", "nl_BE"), ("BE", "BEL", "fr", "fr_BE"),
          ("BE", "BEL", "de", "de_BE")]
DELTAS = {"FRA": [2, 10, 25, 35, 45, 55], "NLD": [2, 10, 35, 45, 55], "BEL": [5, 15, 25, 35, 45]}


def simctl(*args, **kwargs):
    return subprocess.run(["xcrun", "simctl", *args], check=True, text=True,
                          capture_output=True, **kwargs).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--app", type=Path, default=ROOT / "iphone/.derived/SpeedConsumerBuild/Build/Products/Debug-iphonesimulator/SpeedConsumer.app")
    args = parser.parse_args()
    simctl("install", args.device, str(args.app))
    # Keep system permission dialogs out of deterministic simulator captures.
    simctl("privacy", args.device, "grant", "location", BUNDLE_ID)
    simctl("status_bar", args.device, "override", "--time", "9:41", "--dataNetwork", "wifi", "--wifiMode", "active", "--wifiBars", "3", "--batteryState", "charged", "--batteryLevel", "100")
    container = Path(simctl("get_app_container", args.device, BUNDLE_ID, "data"))
    report_path = container / "Documents/country-review.json"
    manifest = []
    try:
        for country, code, language, locale in MATRIX:
            rules_path = ROOT / f"iphone/SpeedConsumerApp/Rules/{code}-rules.json"
            rules_bytes = rules_path.read_bytes()
            rules = json.loads(rules_bytes)
            scenarios = [("00-safe", 0, 50, True, None)]
            for index, band in enumerate(rules["bands"], 1):
                lower, upper = band["min_delta_kmh"], band.get("max_delta_kmh")
                delta = DELTAS[code][index - 1]
                assert lower <= delta and (upper is None or delta <= upper)
                scenarios.append((f"{index:02}-band-{lower}-{upper if upper is not None else 'plus'}", delta, 50, True, index))
            if code == "FRA":
                scenarios += [("07-limit70-delta2", 2, 70, False, 1), ("08-limit70-delta10", 10, 70, False, 2)]
            output = args.output / f"{country}-{language}"
            output.mkdir(parents=True, exist_ok=True)
            for name, delta, limit, inside, band_index in scenarios:
                subprocess.run(["xcrun", "simctl", "terminate", args.device, BUNDLE_ID], capture_output=True)
                report_path.unlink(missing_ok=True)
                env = dict(os.environ, SIMCTL_CHILD_YOUSPEED_SCREENSHOT_STATE="country-penalty",
                           SIMCTL_CHILD_YOUSPEED_SCREENSHOT_COUNTRY=country,
                           SIMCTL_CHILD_YOUSPEED_SCREENSHOT_DELTA=str(delta),
                           SIMCTL_CHILD_YOUSPEED_SCREENSHOT_LIMIT=str(limit),
                           SIMCTL_CHILD_YOUSPEED_SCREENSHOT_INSIDE_CITY="1" if inside else "0")
                simctl("launch", args.device, BUNDLE_ID, "-AppleLanguages", f"({language})", "-AppleLocale", locale, env=env)
                deadline = time.monotonic() + 20
                while not report_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.2)
                report = json.loads(report_path.read_text())
                assert report["country"] == code and report["country_resolved"], report
                assert report["locale"] == language and report["delta_kmh"] == delta, report
                assert report["penalty_present"] == (delta > 0), report
                time.sleep(2)
                screenshot = output / f"{name}.png"
                simctl("io", args.device, "screenshot", str(screenshot))
                report.update(screenshot=str(screenshot), country_locale=f"{country}-{language}",
                              band_index=band_index, rules_sha256=hashlib.sha256(rules_bytes).hexdigest(),
                              screenshot_sha256=hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                              capture="original simctl simulator pixels")
                screenshot.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
                manifest.append(report)
                print(f"Captured {country}-{language}/{name}: {report['title'] or 'safe'}", flush=True)
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    finally:
        subprocess.run(["xcrun", "simctl", "terminate", args.device, BUNDLE_ID], capture_output=True)
        subprocess.run(["xcrun", "simctl", "status_bar", args.device, "clear"], capture_output=True)


if __name__ == "__main__":
    main()
